"""Test signal evaluation logic."""

import asyncio
from datetime import datetime

import pandas as pd
import pytest

from signals.rsi import RSISignal
from signals.bollinger import BollingerSignal


@pytest.mark.asyncio
async def test_rsi_oversold():
    """RSI < 30 should trigger CALL signal."""
    signal = RSISignal(period=14)

    # Create fake data with strong downtrend (RSI should be low)
    prices = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88, 87, 86]
    df = pd.DataFrame({
        "o": prices,
        "h": prices,
        "l": prices,
        "c": prices,
        "v": [1] * len(prices),
    })
    df.index = pd.date_range(datetime.now(), periods=len(prices), freq="1min")

    result = await signal.evaluate(df)
    assert result.direction == "CALL"
    assert result.confidence > 0


@pytest.mark.asyncio
async def test_rsi_insufficient_data():
    """RSI with insufficient data should return None."""
    signal = RSISignal(period=14)

    df = pd.DataFrame({
        "o": [100, 99],
        "h": [100, 99],
        "l": [100, 99],
        "c": [100, 99],
        "v": [1, 1],
    })
    df.index = pd.date_range(datetime.now(), periods=2, freq="1min")

    result = await signal.evaluate(df)
    assert result.direction is None
    assert result.confidence == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
