"""Train the win-probability calibrator from recorded trade outcomes.

Usage:
    python -m strategy.train_calibrator
    python -m strategy.train_calibrator --data data/decisions.db --out data/models/probability_calibrator_v1.pkl

Reads labelled decision rows (those with a win/loss outcome) from the decisions
store, fits a logistic-regression calibrator with a held-out evaluation split,
prints calibration metrics, and saves the production model. Safe to run nightly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config.settings import settings
from data.decisions_store import all_records, reset_cache
from strategy.probability_calibrator import (
    DEFAULT_MODEL_PATH,
    ProbabilityCalibrator,
    train,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATA = _PROJECT_ROOT / settings.decisions_db_path


def _load_rows(path: Path) -> list[dict]:
    if not path.exists():
        print(f"[train_calibrator] no data file at {path}", file=sys.stderr)
        return []
    if path.suffix == ".db":
        reset_cache(path)
        return all_records(path)
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=_DEFAULT_DATA)
    ap.add_argument("--out", type=Path, default=DEFAULT_MODEL_PATH)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--min-auc", type=float, default=0.55,
                    help="minimum test AUC required before saving")
    ap.add_argument("--force-save", action="store_true",
                    help="save even when held-out metrics miss the quality floor")
    args = ap.parse_args(argv)

    rows = _load_rows(args.data)
    labelled = [r for r in rows if r.get("outcome") in ("win", "loss")]
    print(f"[train_calibrator] {len(rows)} rows, {len(labelled)} labelled (win/loss)")

    try:
        cal: ProbabilityCalibrator = train(labelled, test_frac=args.test_frac)
    except ValueError as e:
        print(f"[train_calibrator] cannot train yet: {e}", file=sys.stderr)
        return 1

    print(f"[train_calibrator] {cal.metrics.summary()}")
    print("[train_calibrator] coefficients:")
    for feat, c in cal.metrics.coef.items():
        print(f"    {feat:<18} {c:+.3f}")

    auc = cal.metrics.auc
    if auc is not None and auc < args.min_auc:
        print(f"[train_calibrator] test AUC {auc:.3f} < target {args.min_auc:.2f} "
              "— not saving weak production model.", file=sys.stderr)
        if not args.force_save:
            return 2

    saved = cal.save(args.out)
    print(f"[train_calibrator] saved model → {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
