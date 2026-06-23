from __future__ import annotations

import importlib
import json

rs = importlib.import_module("tools.analyze_regime_surface")


def _row(pair: str, direction: str, outcome: str, metrics: dict, pnl: float | None = None):
    return {
        "ts": "2026-06-23T00:00:00+00:00",
        "pair_api": pair,
        "our_direction": direction,
        "expiry_seconds": 5,
        "outcome": outcome,
        "pnl": pnl,
        "flip_metrics": json.dumps(metrics),
    }


def test_build_trades_derives_regime_buckets():
    base = {
        "entry_kind": "flip",
        "plus_di": 60,
        "minus_di": 20,
        "rsi": 62,
        "atr_bps": 0.2,
        "bb_width_bps": 1.0,
        "macd_gap_std": 0.05,
        "gap_expansion": 0.1,
        "macd_sign_consistency": 1.0,
        "adx": 30,
        "bars_in_trend": 5,
    }
    rows = [
        _row("A", "CALL", "win", base, 1.38),
        _row("A", "CALL", "loss", {**base, "atr_bps": 2.0, "bb_width_bps": 6.0}, -1.5),
        _row("B", "PUT", "win", {**base, "plus_di": 20, "minus_di": 60}, 1.38),
        _row("B", "PUT", "loss", {**base, "gap_expansion": -0.2}, -1.5),
    ]

    trades = rs.build_trades(rows)

    assert len(trades) == 4
    assert {t.direction for t in trades} == {"CALL", "PUT"}
    assert all(t.regime for t in trades)
    assert all(t.vol_bucket.startswith("vol-") for t in trades)
    assert all(t.momentum_bucket.startswith("mom-") for t in trades)


def test_stats_counts_draw_as_non_loss_and_uses_real_pnl():
    metrics = {
        "entry_kind": "flip",
        "plus_di": 60,
        "minus_di": 20,
        "rsi": 62,
        "atr_bps": 0.2,
        "bb_width_bps": 1.0,
        "macd_gap_std": 0.05,
        "gap_expansion": 0.1,
        "macd_sign_consistency": 1.0,
        "adx": 30,
        "bars_in_trend": 5,
    }
    trades = rs.build_trades([
        _row("A", "CALL", "win", metrics, 2.0),
        _row("A", "CALL", "draw", metrics, 0.0),
        _row("A", "CALL", "loss", metrics, -1.0),
    ])

    stats = rs._stats(trades)

    assert stats["n"] == 3
    assert round(stats["wr"], 4) == 0.6667
    assert stats["pnl"] == 1.0
