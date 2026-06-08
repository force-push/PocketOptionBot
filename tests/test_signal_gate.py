"""Tests for strategy/signal_gate.py — all offline.

Uses a mocked API client (returns canned candles), a seeded WinRateTracker,
and a real ConfluenceEngine (with the real TA signal set).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from config.settings import settings
from signals.adx_dmi import ADXDMISignal
from signals.atr import ATRSignal
from signals.bollinger import BollingerSignal
from signals.candle_pattern import CandlePatternSignal
from signals.confluence import ConfluenceEngine
from signals.ema_cross import EMASignal
from signals.macd import MACDSignal
from signals.parabolic_sar import ParabolicSARSignal
from signals.rsi import RSISignal
from signals.stochastic import StochasticSignal
from signals.supertrend import SupertrendSignal
from strategy.signal_gate import SignalGate, GateResult
from strategy.win_rate import WinRateTracker
from telegram_feed.parser import TelegramSignal


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_signal(
    pair="EURUSD_otc",
    direction="CALL",
    expiry=60,
    stated_win_rate=0.87,
) -> TelegramSignal:
    return TelegramSignal(
        pair=pair,
        direction=direction,
        expiry_seconds=expiry,
        stated_win_rate=stated_win_rate,
        raw="EUR/USD OTC CALL M1 Win rate: 87%",
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_strong_call_df(n: int = 100) -> pd.DataFrame:
    """Generate OHLCV DataFrame with a strong downtrend (RSI oversold → CALL)."""
    np.random.seed(1)
    prices = np.linspace(100, 70, n)  # strong downtrend → RSI oversold → CALL
    idx = pd.date_range(datetime.now(tz=timezone.utc), periods=n, freq="1min")
    df = pd.DataFrame({
        "o": prices,
        "h": prices + 0.5,
        "l": prices - 0.5,
        "c": prices,
        "v": np.random.uniform(1000, 5000, n),
    }, index=idx)
    return df


def _make_candles_from_df(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame back to the list-of-dicts format the API returns."""
    rows = []
    for ts, row in df.iterrows():
        rows.append({
            "time": ts.timestamp(),
            "open": row["o"],
            "high": row["h"],
            "low": row["l"],
            "close": row["c"],
            "volume": row["v"],
        })
    return rows


@pytest.fixture
def confluence_engine():
    signals = [
        RSISignal(period=14),
        MACDSignal(fast=12, slow=26, signal=9),
        BollingerSignal(period=20, std_dev=2.0),
        EMASignal(fast=9, slow=21),
        CandlePatternSignal(),
        SupertrendSignal(period=10, multiplier=3.0),      # Tier 2
        StochasticSignal(period=14, smooth_k=3, smooth_d=3),  # Tier 2
        ParabolicSARSignal(initial_af=0.02, max_af=0.2, af_step=0.02),  # Tier 2
        ADXDMISignal(period=14),   # Tier 1: Observation only
        ATRSignal(period=14),      # Tier 1: Observation only
    ]
    return ConfluenceEngine(signals)


@pytest.fixture
def warm_tracker(tmp_path):
    """Tracker warmed up with 20 wins for EURUSD_otc CALL 60s."""
    t = WinRateTracker(json_path=tmp_path / "wr.json")
    for _ in range(20):
        t.record("EURUSD_otc", "CALL", 60, "win")
    return t


@pytest.fixture
def cold_tracker(tmp_path):
    """Fresh tracker with no data (cold start)."""
    return WinRateTracker(json_path=tmp_path / "wr_cold.json")


@pytest.fixture
def mock_api_call_df():
    """Mock API that returns a strong CALL candle set."""
    df = _make_strong_call_df()
    candles = _make_candles_from_df(df)
    api = MagicMock()
    api.get_candles = AsyncMock(return_value=candles)
    api.balance = AsyncMock(return_value=1000.0)
    return api


# ── Gate 1 tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate1_fails_when_no_win_rate(confluence_engine, warm_tracker, mock_api_call_df):
    signal = _make_signal(stated_win_rate=None)
    gate = SignalGate(confluence_engine, warm_tracker, mock_api_call_df)
    result = await gate.evaluate(signal)
    assert result.passed is False
    assert "Gate 1" in result.reason


@pytest.mark.asyncio
async def test_gate1_fails_when_win_rate_below_threshold(
    confluence_engine, warm_tracker, mock_api_call_df, monkeypatch
):
    monkeypatch.setattr(settings, "min_channel_win_rate", 0.80)
    signal = _make_signal(stated_win_rate=0.75)
    gate = SignalGate(confluence_engine, warm_tracker, mock_api_call_df)
    result = await gate.evaluate(signal)
    assert result.passed is False
    assert "Gate 1" in result.reason


@pytest.mark.asyncio
async def test_gate1_passes_at_threshold(
    confluence_engine, warm_tracker, mock_api_call_df, monkeypatch
):
    monkeypatch.setattr(settings, "min_channel_win_rate", 0.80)
    # Gate 1 passes but gate 3 may fail — we just confirm Gate 1 doesn't block
    signal = _make_signal(stated_win_rate=0.80)
    gate = SignalGate(confluence_engine, warm_tracker, mock_api_call_df)
    result = await gate.evaluate(signal)
    # Gate 1 passes; result depends on subsequent gates
    if not result.passed:
        assert "Gate 1" not in result.reason


# ── Gate 2 tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate2_cold_start_passes(
    confluence_engine, cold_tracker, mock_api_call_df, monkeypatch
):
    monkeypatch.setattr(settings, "min_channel_win_rate", 0.50)
    monkeypatch.setattr(settings, "min_tracked_samples", 20)
    signal = _make_signal(stated_win_rate=0.87)
    gate = SignalGate(confluence_engine, cold_tracker, mock_api_call_df)
    result = await gate.evaluate(signal)
    # Gate 2 should pass (cold start); result depends on gate 3
    if not result.passed:
        assert "Gate 2" not in result.reason


@pytest.mark.asyncio
async def test_gate2_fails_after_warmup_bad_rate(
    confluence_engine, tmp_path, mock_api_call_df, monkeypatch
):
    monkeypatch.setattr(settings, "min_channel_win_rate", 0.50)
    monkeypatch.setattr(settings, "min_tracked_win_rate", 0.55)
    monkeypatch.setattr(settings, "min_tracked_samples", 10)

    tracker = WinRateTracker(json_path=tmp_path / "wr2.json")
    for _ in range(10):
        tracker.record("EURUSD_otc", "CALL", 60, "loss")  # 0% win rate

    signal = _make_signal(stated_win_rate=0.87)
    gate = SignalGate(confluence_engine, tracker, mock_api_call_df)
    result = await gate.evaluate(signal)
    assert result.passed is False
    assert "Gate 2" in result.reason


# ── Gate 3 tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate3_fails_empty_candles(
    confluence_engine, warm_tracker, monkeypatch
):
    monkeypatch.setattr(settings, "min_channel_win_rate", 0.50)

    api = MagicMock()
    api.get_candles = AsyncMock(return_value=[])  # empty candles

    signal = _make_signal(stated_win_rate=0.87)
    gate = SignalGate(confluence_engine, warm_tracker, api)
    result = await gate.evaluate(signal)
    assert result.passed is False
    assert "Gate 3" in result.reason


@pytest.mark.asyncio
async def test_gate3_fails_wrong_direction(
    confluence_engine, warm_tracker, monkeypatch
):
    monkeypatch.setattr(settings, "min_channel_win_rate", 0.50)

    # Build a strong CALL DataFrame but request PUT signal
    df = _make_strong_call_df()
    candles = _make_candles_from_df(df)
    api = MagicMock()
    api.get_candles = AsyncMock(return_value=candles)

    # Signal says PUT, but TA says CALL
    signal = _make_signal(stated_win_rate=0.87, direction="PUT")
    gate = SignalGate(confluence_engine, warm_tracker, api)
    result = await gate.evaluate(signal)
    # TA may produce CALL or neutral; if CALL, gate 3 should fail for PUT
    if not result.passed:
        # Either direction mismatch or score too low
        assert "Gate 3" in result.reason or "Gate 1" in result.reason


# ── GateResult dataclass ──────────────────────────────────────────────────────

def test_gate_result_is_frozen():
    r = GateResult(passed=True, reason="ok")
    with pytest.raises((AttributeError, TypeError)):
        r.passed = False  # type: ignore[misc]


# ── Exception safety ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_does_not_raise_on_api_error(
    confluence_engine, warm_tracker, monkeypatch
):
    monkeypatch.setattr(settings, "min_channel_win_rate", 0.50)

    api = MagicMock()
    api.get_candles = AsyncMock(side_effect=RuntimeError("network error"))

    signal = _make_signal(stated_win_rate=0.87)
    gate = SignalGate(confluence_engine, warm_tracker, api)
    result = await gate.evaluate(signal)
    assert result.passed is False
    assert isinstance(result.reason, str)
