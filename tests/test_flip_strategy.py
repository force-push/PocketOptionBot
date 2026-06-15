"""Offline tests for the SuperTrend-flip strategy + indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.supertrend import compute_supertrend
from strategy.flip_strategy import evaluate_flip, FlipParams


def _df(closes, spread: float = 0.02) -> pd.DataFrame:
    c = np.asarray(closes, dtype=float)
    df = pd.DataFrame({"o": c, "h": c + spread, "l": c - spread, "c": c, "v": [1] * len(c)})
    df.index = pd.date_range("2026-01-01", periods=len(c), freq="1s")
    return df


def test_supertrend_flips_on_reversal():
    prices = list(np.linspace(100, 90, 60)) + list(np.linspace(90, 100, 60))
    _st, trend = compute_supertrend(_df(prices), period=10, multiplier=3.0)
    assert int(trend.iloc[-1]) == 1          # ends in uptrend
    assert set(trend.unique()) == {1, -1}    # flipped down then up


def test_supertrend_downtrend_is_put_side():
    prices = list(np.linspace(110, 90, 120))
    _st, trend = compute_supertrend(_df(prices), period=10, multiplier=3.0)
    assert int(trend.iloc[-1]) == -1


_PERMISSIVE = FlipParams(adx_flip_min=0, adx_trend_min=0,
                         require_adx_rising=False, atr_distance_min=0)


def test_flip_enters_call_on_clear_uptrend():
    prices = list(np.linspace(90, 110, 120))
    fd = evaluate_flip(_df(prices), _PERMISSIVE)
    assert fd.direction == "CALL"
    assert fd.entry_kind in ("flip", "trend")
    # diagnostics captured for loss analysis
    assert fd.metrics is not None
    assert fd.metrics["entry_kind"] == fd.entry_kind
    assert fd.metrics["plus_di"] > fd.metrics["minus_di"]  # CALL → +DI dominant


def test_flip_enters_put_on_clear_downtrend():
    prices = list(np.linspace(110, 90, 120))
    fd = evaluate_flip(_df(prices), _PERMISSIVE)
    assert fd.direction == "PUT"


def test_continuation_rejected_when_adx_below_threshold():
    # Same clear uptrend, but require an impossibly high ADX for continuation.
    prices = list(np.linspace(90, 110, 120))
    strict = FlipParams(adx_flip_min=999, adx_trend_min=999,
                        require_adx_rising=False, atr_distance_min=0)
    fd = evaluate_flip(_df(prices), strict)
    assert fd.direction is None


def test_flat_market_no_trade():
    fd = evaluate_flip(_df([100.0] * 120), _PERMISSIVE)
    assert fd.direction is None  # MACD line == signal → no agreement


def test_metrics_include_volatility_and_bars():
    fd = evaluate_flip(_df(list(np.linspace(90, 110, 120))), _PERMISSIVE)
    assert fd.metrics is not None
    assert fd.metrics.get("atr_bps") is not None
    assert fd.metrics.get("bb_width_bps") is not None
    assert fd.metrics.get("bars_in_trend", 0) >= 1


def test_flip_window_classification():
    # Downtrend then a sharp 8-bar reversal up — the flip is recent at the end.
    prices = list(np.linspace(110, 95, 50)) + list(np.linspace(95, 110, 8))
    base = dict(adx_flip_min=0, adx_trend_min=0, require_adx_rising=False, atr_distance_min=0)
    narrow = evaluate_flip(_df(prices), FlipParams(**base, flip_window_bars=1))
    bit = narrow.metrics["bars_in_trend"]
    # A window >= bars_in_trend classifies the recent flip as 'flip'.
    wide = evaluate_flip(_df(prices), FlipParams(**base, flip_window_bars=bit))
    assert wide.entry_kind == "flip"
    if bit > 1:
        assert narrow.entry_kind == "trend"   # narrow window → established


def test_adx_max_cap_blocks_overextended():
    # Clear uptrend that would otherwise trade CALL; a low adx_max blocks it.
    prices = list(np.linspace(90, 110, 120))
    capped = FlipParams(adx_flip_min=0, adx_trend_min=0, require_adx_rising=False,
                        atr_distance_min=0, adx_max=1.0)
    fd = evaluate_flip(_df(prices), capped)
    assert fd.direction is None
    assert "ADX" in fd.reason and "max" in fd.reason
    # With the cap effectively off, the same setup trades.
    open_cap = FlipParams(adx_flip_min=0, adx_trend_min=0, require_adx_rising=False,
                          atr_distance_min=0, adx_max=999.0)
    assert evaluate_flip(_df(prices), open_cap).direction == "CALL"


def test_metrics_include_macd_gap_atr():
    fd = evaluate_flip(_df(list(np.linspace(90, 110, 120))), _PERMISSIVE)
    assert fd.metrics is not None
    assert fd.metrics.get("macd_gap_atr") is not None


def test_cont_macd_gap_min_blocks_weak_continuation():
    # Strong steady uptrend = established trend (continuation). A huge MACD-gap
    # requirement blocks it; zero requirement lets it through.
    prices = list(np.linspace(90, 110, 200))
    blocked = FlipParams(adx_flip_min=0, adx_trend_min=0, require_adx_rising=False,
                         atr_distance_min=0, flip_window_bars=1, cont_macd_gap_min=999.0)
    fd_b = evaluate_flip(_df(prices), blocked)
    # last bar is deep in the trend (continuation), so the MACD-gap gate applies
    if fd_b.entry_kind != "flip":
        assert fd_b.direction is None
        assert "MACD gap" in fd_b.reason
    opened = FlipParams(adx_flip_min=0, adx_trend_min=0, require_adx_rising=False,
                        atr_distance_min=0, flip_window_bars=1, cont_macd_gap_min=0.0)
    assert evaluate_flip(_df(prices), opened).direction == "CALL"


# ── flip wait-and-confirm ──────────────────────────────────────────────────────

def _flip_df() -> pd.DataFrame:
    """Downtrend then a short reversal up → a recent flip at the last bar."""
    prices = list(np.linspace(110, 95, 50)) + list(np.linspace(95, 110, 8))
    return _df(prices)


# Permissive flip baseline with a wide window so the recent reversal is a 'flip'.
_FLIP_BASE = dict(adx_flip_min=0, adx_trend_min=0, require_adx_rising=False,
                  atr_distance_min=0, flip_window_bars=12)


def test_flip_gap_metrics_captured():
    fd = evaluate_flip(_flip_df(), FlipParams(**_FLIP_BASE))
    assert fd.entry_kind == "flip"
    assert "gap_at_flip" in fd.metrics
    assert "gap_expansion" in fd.metrics
    # gap_expansion = macd_gap_atr − gap_at_flip when both are present
    if fd.metrics["gap_at_flip"] is not None:
        assert fd.metrics["gap_expansion"] == round(
            fd.metrics["macd_gap_atr"] - fd.metrics["gap_at_flip"], 3
        )


def test_flip_confirm_bars_waits_for_confirmation():
    df = _flip_df()
    base = evaluate_flip(df, FlipParams(**_FLIP_BASE))
    assert base.entry_kind == "flip"
    bit = base.metrics["bars_in_trend"]
    # Requiring more bars than have elapsed since the flip → pending, no entry.
    waited = evaluate_flip(df, FlipParams(**{**_FLIP_BASE, "flip_confirm_bars": bit + 1}))
    assert waited.direction is None
    assert "pending confirmation" in waited.reason
    # confirm_bars ≤ bars_in_trend → enters.
    ready = evaluate_flip(df, FlipParams(**{**_FLIP_BASE, "flip_confirm_bars": bit}))
    assert ready.direction == "CALL"


def test_flip_adx_dead_zone_excludes():
    df = _flip_df()
    base = evaluate_flip(df, FlipParams(**_FLIP_BASE))
    assert base.entry_kind == "flip"
    adx = base.metrics["adx"]
    # Bracket the actual ADX → flip falls in the dead zone, excluded.
    dead = evaluate_flip(df, FlipParams(**{**_FLIP_BASE,
                         "flip_adx_dead_lo": adx - 1, "flip_adx_dead_hi": adx + 1}))
    assert dead.direction is None
    assert "dead zone" in dead.reason
    # Zone disabled (lo ≥ hi) → enters.
    assert evaluate_flip(df, FlipParams(**{**_FLIP_BASE,
                         "flip_adx_dead_lo": 0, "flip_adx_dead_hi": 0})).direction == "CALL"


def test_flip_gap_expansion_min_gate():
    df = _flip_df()
    # Impossible expansion requirement → blocked.
    blocked = evaluate_flip(df, FlipParams(**{**_FLIP_BASE, "flip_gap_expansion_min": 999.0}))
    assert blocked.direction is None
    assert "not expanding" in blocked.reason
    # Disabled (0) → enters.
    assert evaluate_flip(df, FlipParams(**{**_FLIP_BASE,
                         "flip_gap_expansion_min": 0.0})).direction == "CALL"


def test_macd_consistency_metrics_captured():
    # A clean steady uptrend should yield consistent MACD width (low std) and a
    # high same-side fraction. Capture-only — never affects the decision.
    prices = list(np.linspace(90, 110, 120))
    fd = evaluate_flip(_df(prices), _PERMISSIVE)
    m = fd.metrics
    assert "macd_gap_std" in m and m["macd_gap_std"] is not None
    assert "macd_gap_mean" in m and m["macd_gap_mean"] is not None
    assert m["macd_sign_consistency"] is not None
    assert 0.0 <= m["macd_sign_consistency"] <= 1.0
    # steady trend → MACD stays on one side the whole window
    assert m["macd_sign_consistency"] == 1.0


def test_macd_consistency_does_not_gate():
    # Even with erratic width the metric is recorded, not a filter — direction
    # still comes from the rule, not the consistency value.
    prices = list(np.linspace(90, 110, 120))
    fd = evaluate_flip(_df(prices), _PERMISSIVE)
    assert fd.direction == "CALL"   # unaffected by the new capture-only metric


def test_bb_width_gate_blocks_chop_and_whipsaw():
    prices = list(np.linspace(90, 110, 120))
    base = evaluate_flip(_df(prices), _PERMISSIVE)
    assert base.direction == "CALL"
    bbw = base.metrics["bb_width_bps"]
    assert bbw is not None
    # Require a band tighter than reality → chop block.
    chop = evaluate_flip(_df(prices), FlipParams(
        adx_flip_min=0, adx_trend_min=0, require_adx_rising=False, atr_distance_min=0,
        bb_width_min=bbw + 5))
    assert chop.direction is None and "chop" in chop.reason
    # Require a band wider than reality → whipsaw block.
    whip = evaluate_flip(_df(prices), FlipParams(
        adx_flip_min=0, adx_trend_min=0, require_adx_rising=False, atr_distance_min=0,
        bb_width_max=max(bbw - 1, 0.1)))
    assert whip.direction is None and "whipsaw" in whip.reason
    # Band that brackets reality → trades.
    ok = evaluate_flip(_df(prices), FlipParams(
        adx_flip_min=0, adx_trend_min=0, require_adx_rising=False, atr_distance_min=0,
        bb_width_min=max(bbw - 2, 0.0), bb_width_max=bbw + 2))
    assert ok.direction == "CALL"


def test_insufficient_candles():
    fd = evaluate_flip(_df(list(np.linspace(90, 100, 20))), FlipParams())
    assert fd.direction is None
    assert "insufficient" in fd.reason


def test_macd_must_agree_with_supertrend():
    # Strong uptrend → SuperTrend CALL, MACD bullish → agreement holds.
    prices = list(np.linspace(90, 110, 120))
    fd = evaluate_flip(_df(prices), _PERMISSIVE)
    assert fd.direction == "CALL"
    # If we force the strong-trend gates on a *weak* late move, no continuation.
    prices2 = list(np.linspace(95, 105, 60)) + [105.0] * 60  # rally then flat
    fd2 = evaluate_flip(_df(prices2), FlipParams(adx_trend_min=30, require_adx_rising=True))
    assert fd2.direction is None
