"""Tests for RoCSignal (Rate of Change)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from signals.roc import RoCSignal


def _df(closes) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range(datetime(2026, 1, 1), periods=n, freq="5s")
    return pd.DataFrame(
        {"o": closes, "h": [c + 0.1 for c in closes], "l": [c - 0.1 for c in closes],
         "c": closes, "v": [100] * n},
        index=idx,
    )


@pytest.mark.asyncio
async def test_insufficient_data():
    sig = RoCSignal(period=5)
    result = await sig.evaluate(_df([100.0] * 5))  # need period + 1 = 6
    assert result.direction is None
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_rising_momentum_call():
    sig = RoCSignal(period=5, threshold=0.05)
    # Strong upward move: current close well above 5 bars ago
    prices = [100.0, 100.1, 100.2, 100.3, 100.4, 101.0]  # 6 bars
    result = await sig.evaluate(_df(prices))
    assert result.direction == "CALL"
    assert result.confidence > 0.0


@pytest.mark.asyncio
async def test_falling_momentum_put():
    sig = RoCSignal(period=5, threshold=0.05)
    prices = [101.0, 100.9, 100.8, 100.7, 100.6, 100.0]  # strong drop
    result = await sig.evaluate(_df(prices))
    assert result.direction == "PUT"
    assert result.confidence > 0.0


@pytest.mark.asyncio
async def test_flat_no_signal():
    sig = RoCSignal(period=5, threshold=0.05)
    prices = [100.0] * 6  # no movement
    result = await sig.evaluate(_df(prices))
    assert result.direction is None


@pytest.mark.asyncio
async def test_below_threshold_no_signal():
    sig = RoCSignal(period=5, threshold=1.0)  # high threshold
    # Small movement that won't meet threshold
    prices = [100.0, 100.01, 100.02, 100.03, 100.04, 100.05]  # 0.05% change
    result = await sig.evaluate(_df(prices))
    assert result.direction is None


@pytest.mark.asyncio
async def test_confidence_caps_at_1():
    sig = RoCSignal(period=5, threshold=0.05, confidence_cap_pct=0.30)
    # Huge move — well beyond 0.3% cap
    prices = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]  # 10% move
    result = await sig.evaluate(_df(prices))
    assert result.direction == "CALL"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_confidence_scales():
    sig = RoCSignal(period=5, threshold=0.05, confidence_cap_pct=0.30)
    small = _df([100.0, 100.0, 100.0, 100.0, 100.0, 100.10])  # 0.10% → conf ~0.33
    large = _df([100.0, 100.0, 100.0, 100.0, 100.0, 100.25])  # 0.25% → conf ~0.83
    r_small = await sig.evaluate(small)
    r_large = await sig.evaluate(large)
    assert r_small.direction == r_large.direction == "CALL"
    assert r_large.confidence > r_small.confidence


@pytest.mark.asyncio
async def test_attributes():
    assert RoCSignal.name == "RoC"
    assert RoCSignal.weight == 0.08
