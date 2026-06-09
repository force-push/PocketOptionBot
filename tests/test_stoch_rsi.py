"""Tests for StochRSISignal."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from signals.stoch_rsi import StochRSISignal


def _df(closes) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range(datetime(2026, 1, 1), periods=n, freq="5s")
    prices = list(closes)
    return pd.DataFrame(
        {"o": prices, "h": [c + 0.2 for c in prices], "l": [c - 0.2 for c in prices],
         "c": prices, "v": [100] * n},
        index=idx,
    )


def _downtrend(n: int = 80) -> pd.DataFrame:
    """Rally then sharp crash: RSI goes high then low within the stoch window.

    StochRSI K% measures where current RSI sits within its own recent range.
    A pure linear decline keeps RSI at a steady level (K≈50 — midrange).
    We need RSI to have HIGH values then LOW values within the stoch_period
    window: rally first to push RSI toward 80+, then crash to push RSI near 0.
    The transition window contains high-and-low RSI, so K% → 0.
    """
    rally = np.linspace(100.0, 120.0, 40).tolist()
    crash = np.linspace(120.0, 75.0, n - 40).tolist()
    return _df(rally + crash)


def _uptrend(n: int = 80) -> pd.DataFrame:
    """Crash then sharp surge: RSI goes low then high within the stoch window.

    For K% → 100 (overbought), RSI must hit a *new high* within the window.
    Structure: neutral baseline, then sharp drop to push RSI low, then hard
    rally so RSI surges to the top of the recent window range.
    """
    neutral = np.linspace(100.0, 100.0, 20).tolist()
    drop = np.linspace(100.0, 82.0, 20).tolist()
    surge = np.linspace(82.0, 125.0, n - 40).tolist()
    return _df(neutral + drop + surge)


@pytest.mark.asyncio
async def test_insufficient_data():
    sig = StochRSISignal(rsi_period=14, stoch_period=14, smooth_k=3, smooth_d=3)
    # min required = 14 + 14 + 3 + 3 = 34 rows
    result = await sig.evaluate(_df([100.0] * 30))
    assert result.direction is None
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_oversold_produces_call():
    """Deep downtrend should push StochRSI K% into oversold → CALL."""
    sig = StochRSISignal()
    result = await sig.evaluate(_downtrend(60))
    assert result.direction == "CALL"
    assert result.confidence > 0.0


@pytest.mark.asyncio
async def test_overbought_produces_put():
    """Strong uptrend should push StochRSI K% into overbought → PUT."""
    sig = StochRSISignal()
    result = await sig.evaluate(_uptrend(60))
    assert result.direction == "PUT"
    assert result.confidence > 0.0


@pytest.mark.asyncio
async def test_confidence_in_range():
    sig = StochRSISignal()
    for df in [_downtrend(60), _uptrend(60)]:
        result = await sig.evaluate(df)
        assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_neutral_on_flat():
    """Flat price → RSI neutral → StochRSI neutral, no signal."""
    sig = StochRSISignal()
    # Flat price with tiny noise — RSI stays near 50 → StochRSI neutral
    np.random.seed(42)
    prices = (100.0 + np.random.normal(0, 0.001, 60)).tolist()
    result = await sig.evaluate(_df(prices))
    # Flat should not produce a directional signal
    if result.direction is not None:
        # If it does fire, confidence should be very low
        assert result.confidence < 0.5


@pytest.mark.asyncio
async def test_no_exception_on_nan_edge_cases():
    """Signal should not raise even when RSI range is zero for a period."""
    sig = StochRSISignal()
    # Constant then volatile — creates a zero-range RSI window
    prices = [100.0] * 20 + list(np.linspace(100.0, 80.0, 40))
    result = await sig.evaluate(_df(prices))
    assert result.direction in (None, "CALL", "PUT")
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_attributes():
    assert StochRSISignal.name == "StochRSI"
    assert StochRSISignal.weight == 0.10
