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
