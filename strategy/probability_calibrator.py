"""Calibrated win-probability model.

The trade-decision combiner (strategy/decision.py) produces a *heuristic*
``combined_probability`` = mean(bot_win_rate, our_confluence). It is a
confidence score, NOT a calibrated probability. This module learns a real
P(win) from historical outcomes recorded in ``data/decisions.jsonl``.

Design choices (kept deliberately conservative for a small dataset):
- Features are numeric only. ``pair_api`` is intentionally excluded for v1:
  with a few hundred labelled trades, one-hot encoding dozens of pairs would
  overfit badly. Revisit once the dataset is larger.
- Model is L2-regularised logistic regression — interpretable, low-variance,
  and it outputs a true probability via ``predict_proba``.
- ``predict()`` always degrades gracefully: if scikit-learn is missing or no
  model has been trained/loaded, it returns the simple heuristic average so the
  live bot never crashes or blocks on this feature.

The persisted model is a plain pickle dict holding the fitted estimator, the
feature order, and the training metrics — no joblib dependency required.
"""
from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

# Numeric features, in a fixed order. Anything missing falls back to 0.0.
FEATURES: tuple[str, ...] = (
    "bot_win_rate",       # 0-1, the bot's claimed win rate for the pair
    "our_confluence",     # 0-1, our adaptive confluence score
    "agreement",          # 0/1, bot direction == our direction
    "agreeing_signals",   # int, how many of our signals back the direction
    "payout_pct",         # broker payout %, scaled to 0-1 in featurize()
    "bot_is_top_pick",    # 0/1, was this the bot's top-ranked pair
    "pair_recent_wr",     # 0-1, pair-level resolved WR at entry time
    "direction_wr",       # 0-1, pair+direction+expiry resolved WR at entry time
    "rsi",                # 0-1, RSI scaled from 0-100
    "rsi_extreme",        # 0/1, CALL overbought or PUT oversold
    "reversal_against_entry",  # 0/1, newest candle closed against entry
    "stake_ratio",        # prospective stake / base stake
    "martingale_escalated",    # 0/1, stake_ratio >= 2
)

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "models" / "probability_calibrator_v1.pkl"


def _heuristic(bot_win_rate: float, our_confluence: float) -> float:
    """The existing fallback combiner: mean of bot win-rate and our confluence."""
    return max(0.0, min(1.0, (float(bot_win_rate) + float(our_confluence)) / 2.0))


def featurize(rec: Mapping[str, Any]) -> list[float]:
    """Map a decision record (or a feature dict) to the ordered feature vector.

    Accepts the raw ``decisions.jsonl`` schema as well as a loose dict using the
    short FEATURES keys, so both training and live inference can call it.
    """
    def g(*keys: str, default: float = 0.0) -> float:
        for k in keys:
            if k in rec and rec[k] is not None:
                return float(rec[k])
        return default

    agreeing = rec.get("agreeing_signals")
    if agreeing is None:
        # derive from our_signal_breakdown if present
        breakdown = rec.get("our_signal_breakdown") or {}
        our_dir = rec.get("our_direction")
        agreeing = sum(
            1 for v in breakdown.values()
            if isinstance(v, (list, tuple)) and v and v[0] == our_dir
        )

    assessment = rec.get("signal_assessment") or {}
    flip_metrics = rec.get("flip_metrics") or {}
    rsi = rec.get("rsi")
    if rsi is None:
        rsi = assessment.get("rsi")
    if rsi is None:
        rsi = flip_metrics.get("rsi")
    rsi_f = float(rsi) if isinstance(rsi, (int, float)) else 50.0

    payout = g("payout_pct")
    stake_ratio = rec.get("stake_ratio")
    if stake_ratio is None:
        stake_ratio = assessment.get("stake_ratio")
    if stake_ratio is None:
        stake_ratio = flip_metrics.get("prospective_stake_ratio", 1.0)

    return [
        g("bot_win_rate"),
        g("our_confluence", "our_confluence_score"),
        1.0 if rec.get("agreement") else 0.0,
        float(agreeing or 0),
        payout / 100.0 if payout > 1.5 else payout,   # accept 92 or 0.92
        1.0 if rec.get("bot_is_top_pick") else 0.0,
        g("pair_recent_wr", default=float(assessment.get("pair_recent_wr") or 0.0)),
        g("direction_wr", default=float(assessment.get("direction_wr") or rec.get("bot_win_rate") or 0.0)),
        max(0.0, min(1.0, rsi_f / 100.0)),
        1.0 if rec.get("rsi_extreme") or assessment.get("rsi_extreme") else 0.0,
        1.0 if rec.get("reversal_against_entry") or assessment.get("reversal_against_entry") else 0.0,
        float(stake_ratio or 1.0),
        1.0 if rec.get("martingale_escalated") or assessment.get("martingale_escalated") else 0.0,
    ]


@dataclass
class CalibratorMetrics:
    n_train: int = 0
    n_test: int = 0
    log_loss: float | None = None
    auc: float | None = None
    accuracy: float | None = None
    brier: float | None = None
    base_rate: float | None = None
    coef: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        def f(x: float | None) -> str:
            return f"{x:.4f}" if isinstance(x, (int, float)) else "—"
        return (
            f"n_train={self.n_train} n_test={self.n_test} "
            f"base_rate={f(self.base_rate)} | "
            f"AUC={f(self.auc)} log_loss={f(self.log_loss)} "
            f"brier={f(self.brier)} acc={f(self.accuracy)}"
        )


class ProbabilityCalibrator:
    """Loads/holds a fitted logistic model and predicts a calibrated P(win)."""

    def __init__(self, model: Any = None, metrics: CalibratorMetrics | None = None):
        self._model = model
        self.metrics = metrics or CalibratorMetrics()

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    # ── inference ────────────────────────────────────────────────────────────
    def predict(self, rec: Mapping[str, Any]) -> float:
        """Return calibrated P(win) in [0,1]; fall back to the heuristic mean."""
        if self._model is None:
            return _heuristic(
                rec.get("bot_win_rate", 0.0),
                rec.get("our_confluence", rec.get("our_confluence_score", 0.0)),
            )
        try:
            x = [featurize(rec)]
            p = float(self._model.predict_proba(x)[0][1])
            if math.isnan(p):
                raise ValueError("nan probability")
            return max(0.0, min(1.0, p))
        except Exception:
            return _heuristic(
                rec.get("bot_win_rate", 0.0),
                rec.get("our_confluence", rec.get("our_confluence_score", 0.0)),
            )

    # ── persistence ──────────────────────────────────────────────────────────
    def save(self, path: str | Path = DEFAULT_MODEL_PATH) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as fh:
            pickle.dump(
                {"model": self._model, "features": FEATURES, "metrics": self.metrics},
                fh,
            )
        return p

    @classmethod
    def load(cls, path: str | Path = DEFAULT_MODEL_PATH) -> "ProbabilityCalibrator":
        """Load a saved model, or return an unfitted (fallback-only) calibrator."""
        p = Path(path)
        if not p.exists():
            return cls(model=None)
        try:
            with p.open("rb") as fh:
                blob = pickle.load(fh)
            return cls(model=blob.get("model"), metrics=blob.get("metrics"))
        except Exception:
            return cls(model=None)


def train(records: list[Mapping[str, Any]], *, test_frac: float = 0.2,
          seed: int = 42) -> ProbabilityCalibrator:
    """Fit a calibrator on labelled decision records.

    Only records with a win/loss ``outcome`` are used. Raises ValueError if
    there are too few labelled samples or only one class is present.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, log_loss, accuracy_score, brier_score_loss

    labelled = [r for r in records if r.get("outcome") in ("win", "loss")]
    if len(labelled) < 30:
        raise ValueError(f"need >=30 labelled trades to train, have {len(labelled)}")

    X = np.array([featurize(r) for r in labelled], dtype=float)
    y = np.array([1 if r.get("outcome") == "win" else 0 for r in labelled], dtype=int)
    if y.min() == y.max():
        raise ValueError("only one outcome class present; cannot train")

    # Deterministic shuffle + split (no sklearn train_test_split to keep seeds explicit).
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    n_test = max(1, int(len(y) * test_frac))
    test_idx, train_idx = idx[:n_test], idx[n_test:]
    Xtr, ytr = X[train_idx], y[train_idx]
    Xte, yte = X[test_idx], y[test_idx]

    clf = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
    clf.fit(Xtr, ytr)

    m = CalibratorMetrics(
        n_train=int(len(ytr)), n_test=int(len(yte)),
        base_rate=float(y.mean()),
        coef={f: float(c) for f, c in zip(FEATURES, clf.coef_[0])},
    )
    # Test-set metrics are only meaningful if both classes appear in the test split.
    if len(set(yte.tolist())) == 2:
        proba = clf.predict_proba(Xte)[:, 1]
        m.auc = float(roc_auc_score(yte, proba))
        m.log_loss = float(log_loss(yte, proba, labels=[0, 1]))
        m.brier = float(brier_score_loss(yte, proba))
        m.accuracy = float(accuracy_score(yte, (proba >= 0.5).astype(int)))

    # Refit on ALL labelled data for the production model (test split was eval only).
    final = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
    final.fit(X, y)
    return ProbabilityCalibrator(model=final, metrics=m)
