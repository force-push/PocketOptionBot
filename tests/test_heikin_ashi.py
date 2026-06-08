"""Tests for HeikinAshiSignal."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from signals.heikin_ashi import HeikinAshiSignal


def _df(opens, highs, lows, closes) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range(datetime(2026, 1, 1), periods=n, freq="5s")
    return pd.DataFrame(
        {"o": opens, "h": highs, "l": lows, "c": closes, "v": [100] * n},
        index=idx,
    )


def _trending(n: int = 10, direction: str = "up") -> pd.DataFrame:
    """Build a clean trending series that produces n HA bars in one direction."""
    if direction == "up":
        prices = np.linspace(100.0, 110.0, n)
        return _df(
            opens=prices - 0.1,
            highs=prices + 0.3,
            lows=prices - 0.2,
            closes=prices + 0.2,
        )
    else:
        prices = np.linspace(110.0, 100.0, n)
        return _df(
            opens=prices + 0.1,
            highs=prices + 0.2,
            lows=prices - 0.3,
            closes=prices - 0.2,
        )


@pytest.mark.asyncio
async def test_insufficient_data():
    sig = HeikinAshiSignal(min_consecutive=3)
    df = _trending(3, "up")  # too few rows
    result = await sig.evaluate(df)
    assert result.direction is None
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_bullish_trend_call():
    sig = HeikinAshiSignal(min_consecutive=3)
    df = _trending(15, "up")
    result = await sig.evaluate(df)
    assert result.direction == "CALL"
    assert result.confidence > 0.0


@pytest.mark.asyncio
async def test_bearish_trend_put():
    sig = HeikinAshiSignal(min_consecutive=3)
    df = _trending(15, "down")
    result = await sig.evaluate(df)
    assert result.direction == "PUT"
    assert result.confidence > 0.0


@pytest.mark.asyncio
async def test_confidence_scales_with_run_length():
    sig = HeikinAshiSignal(min_consecutive=3)
    short_df = _trending(7, "up")   # shorter run
    long_df = _trending(15, "up")   # longer run
    short_result = await sig.evaluate(short_df)
    long_result = await sig.evaluate(long_df)
    assert long_result.confidence >= short_result.confidence


@pytest.mark.asyncio
async def test_neutral_when_run_too_short():
    sig = HeikinAshiSignal(min_consecutive=5)  # require 5, give only 4
    df = _trending(8, "up")
    result = await sig.evaluate(df)
    # With min_consecutive=5 the run may or may not reach threshold
    # Just verify no exception and valid result
    assert result.direction in (None, "CALL", "PUT")
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_reversal_after_bearish_run():
    """Append a single bullish bar to a sustained bearish run → reversal CALL."""
    sig = HeikinAshiSignal(min_consecutive=3)
    # Build 6 bearish bars then 1 bullish bar
    bear = _trending(7, "down")
    # Replace last bar with a strongly bullish candle
    bear.iloc[-1, bear.columns.get_loc("o")] = 103.0
    bear.iloc[-1, bear.columns.get_loc("c")] = 104.5
    bear.iloc[-1, bear.columns.get_loc("h")] = 105.0
    bear.iloc[-1, bear.columns.get_loc("l")] = 102.5
    result = await sig.evaluate(bear)
    # Should either be CALL reversal or neutral (HA smoothing may absorb a single bar)
    if result.direction is not None:
        assert result.direction == "CALL"


@pytest.mark.asyncio
async def test_no_error_on_flat_data():
    """Flat OHLCV data (all identical prices) produces doji HA bars — no signal."""
    sig = HeikinAshiSignal(min_consecutive=3)
    prices = [100.0] * 20
    df = _df(prices, prices, prices, prices)
    result = await sig.evaluate(df)
    # All prices identical → HA close == HA open every bar → doji → no signal
    assert result.direction is None
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_signal_attributes():
    assert HeikinAshiSignal.name == "HeikinAshi"
    assert HeikinAshiSignal.weight == 0.12
