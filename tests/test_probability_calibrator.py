"""Tests for the win-probability calibrator."""
from __future__ import annotations

import math

import pytest

from strategy.probability_calibrator import (
    FEATURES,
    ProbabilityCalibrator,
    featurize,
    train,
    _heuristic,
)


def _rec(bot=0.6, conf=0.4, agree=True, signals=3, payout=92, top=True, outcome=None):
    return {
        "bot_win_rate": bot,
        "our_confluence": conf,
        "agreement": agree,
        "agreeing_signals": signals,
        "payout_pct": payout,
        "bot_is_top_pick": top,
        "outcome": outcome,
    }


def test_featurize_length_and_order():
    v = featurize(_rec())
    assert len(v) == len(FEATURES)
    # payout 92 should be scaled into 0-1 range
    assert 0.0 <= v[FEATURES.index("payout_pct")] <= 1.0
    assert v[FEATURES.index("agreement")] == 1.0
    assert v[FEATURES.index("bot_is_top_pick")] == 1.0


def test_featurize_accepts_jsonl_schema():
    rec = {
        "bot_win_rate": 0.7,
        "our_confluence_score": 0.5,   # long key from decisions.jsonl
        "agreement": False,
        "our_signal_breakdown": {"a": ["CALL", 0.9, "x"], "b": ["PUT", 0.8, "y"]},
        "our_direction": "CALL",
        "payout_pct": 0.85,            # already 0-1
        "bot_is_top_pick": False,
    }
    v = featurize(rec)
    assert v[FEATURES.index("our_confluence")] == 0.5
    # one signal agrees with CALL
    assert v[FEATURES.index("agreeing_signals")] == 1.0
    assert v[FEATURES.index("payout_pct")] == 0.85


def test_featurize_accepts_signal_assessment_features():
    rec = _rec(bot=0.564, conf=1.0)
    rec["signal_assessment"] = {
        "pair_recent_wr": 0.51,
        "direction_wr": 0.564,
        "rsi": 89.7,
        "rsi_extreme": True,
        "reversal_against_entry": True,
        "stake_ratio": 4.84,
        "martingale_escalated": True,
    }

    v = featurize(rec)

    assert v[FEATURES.index("pair_recent_wr")] == pytest.approx(0.51)
    assert v[FEATURES.index("direction_wr")] == pytest.approx(0.564)
    assert v[FEATURES.index("rsi")] == pytest.approx(0.897)
    assert v[FEATURES.index("rsi_extreme")] == 1.0
    assert v[FEATURES.index("reversal_against_entry")] == 1.0
    assert v[FEATURES.index("stake_ratio")] == pytest.approx(4.84)
    assert v[FEATURES.index("martingale_escalated")] == 1.0


def test_unfitted_predict_falls_back_to_heuristic():
    cal = ProbabilityCalibrator(model=None)
    assert not cal.is_ready
    p = cal.predict(_rec(bot=0.6, conf=0.4))
    assert p == pytest.approx(_heuristic(0.6, 0.4))
    assert p == pytest.approx(0.5)


def test_predict_always_in_unit_interval():
    cal = ProbabilityCalibrator(model=None)
    for r in (_rec(bot=2.0, conf=2.0), _rec(bot=-1.0, conf=-1.0)):
        p = cal.predict(r)
        assert 0.0 <= p <= 1.0 and not math.isnan(p)


def test_train_too_few_samples_raises():
    with pytest.raises(ValueError):
        train([_rec(outcome="win")] * 5)


def test_train_single_class_raises():
    recs = [_rec(outcome="win") for _ in range(40)]
    with pytest.raises(ValueError):
        train(recs)


def test_train_and_predict_roundtrip(tmp_path):
    # Synthetic separable data: high bot_win_rate -> win, low -> loss.
    recs = []
    for i in range(120):
        win = i % 2 == 0
        recs.append(_rec(
            bot=0.75 if win else 0.45,
            conf=0.6 if win else 0.3,
            signals=4 if win else 1,
            top=win,
            outcome="win" if win else "loss",
        ))
    cal = train(recs)
    assert cal.is_ready
    assert cal.metrics.n_train + cal.metrics.n_test == len(recs)

    p_win = cal.predict(_rec(bot=0.8, conf=0.7, signals=5, top=True))
    p_loss = cal.predict(_rec(bot=0.4, conf=0.2, signals=0, top=False))
    assert 0.0 <= p_loss <= 1.0 and 0.0 <= p_win <= 1.0
    assert p_win > p_loss  # model learned the direction

    # Persistence round-trip.
    path = tmp_path / "model.pkl"
    cal.save(path)
    loaded = ProbabilityCalibrator.load(path)
    assert loaded.is_ready
    assert loaded.predict(_rec(bot=0.8, conf=0.7, signals=5, top=True)) == pytest.approx(p_win)


def test_load_missing_file_returns_fallback(tmp_path):
    cal = ProbabilityCalibrator.load(tmp_path / "nope.pkl")
    assert not cal.is_ready
    assert cal.predict(_rec(bot=0.6, conf=0.4)) == pytest.approx(0.5)
