"""Test signal evaluation logic."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from signals.base import BaseSignal, SignalResult
from signals.bollinger import BollingerSignal
from signals.confluence import ConfluenceEngine, ConfluenceResult
from signals.rsi import RSISignal


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


# ── ConfluenceEngine tests ────────────────────────────────────────────────────

def _make_df(n: int = 50) -> pd.DataFrame:
    """Minimal OHLCV DataFrame for confluence tests."""
    prices = np.linspace(100, 80, n)  # downtrend
    idx = pd.date_range(datetime.now(), periods=n, freq="1min")
    return pd.DataFrame(
        {"o": prices, "h": prices + 0.5, "l": prices - 0.5, "c": prices, "v": [100] * n},
        index=idx,
    )


def _stub_signal(name: str, weight: float, direction: str | None, confidence: float = 0.8) -> BaseSignal:
    """Create a mock BaseSignal that always returns the given result."""
    sig = AsyncMock(spec=BaseSignal)
    sig.name = name
    sig.weight = weight
    sig.evaluate = AsyncMock(
        return_value=SignalResult(name=name, direction=direction, confidence=confidence, reason="stub")
    )
    return sig


@pytest.mark.asyncio
async def test_confluence_requires_3_agreeing_on_same_side():
    """
    Regression test for the agreeing_signals bug.

    2 CALL signals + 1 PUT signal = 3 directional signals total.
    The old code counted this as "3 agreeing" and allowed a trade.
    The fix requires ≥3 on the *same* side, so this should return None.
    """
    signals = [
        _stub_signal("A", 0.2, "CALL"),
        _stub_signal("B", 0.2, "CALL"),
        _stub_signal("C", 0.2, "PUT"),
        _stub_signal("D", 0.2, None),
        _stub_signal("E", 0.2, None),
    ]
    engine = ConfluenceEngine(signals)
    result = await engine.score(_make_df())

    assert result.direction is None, (
        "Should not trade when only 2/5 signals agree on CALL (old bug: counted CALL+PUT as agreement)"
    )
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_confluence_fires_with_3_on_same_side():
    """3 out of 5 signals agree on CALL → should produce a CALL result."""
    signals = [
        _stub_signal("A", 0.2, "CALL"),
        _stub_signal("B", 0.2, "CALL"),
        _stub_signal("C", 0.2, "CALL"),
        _stub_signal("D", 0.2, "PUT"),
        _stub_signal("E", 0.2, None),
    ]
    engine = ConfluenceEngine(signals)
    result = await engine.score(_make_df())

    assert result.direction == "CALL"
    assert result.score > 0.0


@pytest.mark.asyncio
async def test_confluence_rejects_tied_scores():
    """Equal weighted CALL/PUT scores → direction None."""
    signals = [
        _stub_signal("A", 0.5, "CALL", confidence=0.9),
        _stub_signal("B", 0.5, "CALL", confidence=0.9),
        _stub_signal("C", 0.5, "CALL", confidence=0.9),
        _stub_signal("D", 0.5, "PUT",  confidence=0.9),
        _stub_signal("E", 0.5, "PUT",  confidence=0.9),
        _stub_signal("F", 0.5, "PUT",  confidence=0.9),
    ]
    engine = ConfluenceEngine(signals)
    result = await engine.score(_make_df())

    assert result.direction is None
    assert "CALL ≈ PUT" in result.reason


@pytest.mark.asyncio
async def test_confluence_empty_df_returns_none():
    """Empty DataFrame → direction None, score 0."""
    engine = ConfluenceEngine([_stub_signal("A", 1.0, "CALL")])
    result = await engine.score(pd.DataFrame())
    assert result.direction is None
    assert result.score == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
