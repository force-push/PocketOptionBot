"""Offline tests for the event-driven flip streamer (raw-tick edition)."""
from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from strategy import flip_streamer
from strategy.flip_streamer import FlipStreamer


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_df(closes, t0=0) -> pd.DataFrame:
    """Build an o/h/l/c/v DataFrame that evaluate_flip can consume."""
    idx = pd.date_range(
        pd.Timestamp(t0, unit="s", tz="UTC"), periods=len(closes), freq="s"
    )
    closes = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "o": closes, "h": closes + 0.02,
            "l": closes - 0.02, "c": closes, "v": np.ones(len(closes)),
        },
        index=idx,
    )


class _FakeRawTickStream:
    """Mock RawTickStream that yields pre-built DataFrames then stops."""

    def __init__(self, dfs, *, started=None):
        self._dfs = list(dfs)
        self._started = started   # asyncio.Event set when start() is called

    async def start(self) -> None:
        if self._started is not None:
            self._started.set()

    async def stop(self) -> None:
        pass

    def seed(self, df: pd.DataFrame) -> None:
        pass

    def __aiter__(self):
        return self

    async def __anext__(self) -> pd.DataFrame:
        await asyncio.sleep(0)
        if self._dfs:
            return self._dfs.pop(0)
        raise StopAsyncIteration


_PERMISSIVE_LEVERS = {
    "st_period": 10, "st_multiplier": 3.0, "flip_window_bars": 5,
    "adx_flip_min": 0, "adx_trend_min": 999, "adx_max": 999,
    "require_adx_rising": False, "atr_distance_min": 0.0,
    "atr_distance_max": 999.0, "cont_macd_gap_min": 0.0, "cont_rsi_min": 0.0,
}

# ── tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_streamer_places_on_fresh_flip(monkeypatch):
    monkeypatch.setattr(flip_streamer, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))

    # Downtrend seed then sharp reversal — should trigger a CALL flip
    down = list(np.linspace(110, 95, 150))
    up = list(np.linspace(95, 120, 40))
    all_closes = down + up
    # emit full rolling DataFrames (as RawTickStream does after seeding)
    dfs = [_make_df(all_closes[: 150 + i + 1]) for i in range(40)]

    started = asyncio.Event()
    fake_stream = _FakeRawTickStream(dfs, started=started)

    api = MagicMock()
    api.get_real_candles = AsyncMock(return_value=[])
    api.get_payout = AsyncMock(return_value=92)

    mgr = MagicMock()
    mgr._place_flip_trade = AsyncMock(return_value=True)

    with patch("strategy.flip_streamer.RawTickStream", return_value=fake_stream):
        s = FlipStreamer(api, mgr)
        s._running = True
        task = asyncio.create_task(s._consume("EURUSD_otc"))
        # wait until the stream starts or timeout
        try:
            await asyncio.wait_for(started.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        # let it process frames
        for _ in range(200):
            await asyncio.sleep(0.005)
            if mgr._place_flip_trade.await_count:
                break
        s._running = False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    assert mgr._place_flip_trade.await_count >= 1
    args = mgr._place_flip_trade.await_args.args
    assert args[1] == "CALL"
    assert mgr._place_flip_trade.await_args.kwargs["payout_pct"] == 92


@pytest.mark.asyncio
async def test_streamer_start_caps_at_4(monkeypatch):
    api = MagicMock()
    mgr = MagicMock()
    s = FlipStreamer(api, mgr)
    monkeypatch.setattr(s, "_consume", AsyncMock())
    await s.start(["A", "B", "C", "D", "E", "F"])
    assert len(s.pairs) == 4
    await s.stop()


@pytest.mark.asyncio
async def test_streamer_seeds_from_history(monkeypatch):
    """RawTickStream.seed() is called with the candles_to_df result."""
    monkeypatch.setattr(flip_streamer, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))

    seed_called_with = []

    class _TrackSeedStream(_FakeRawTickStream):
        def seed(self, df: pd.DataFrame) -> None:
            seed_called_with.append(df)

    fake_stream = _TrackSeedStream([])
    seed_candles = [
        {"time": 1700000000 + i, "open": 1.1, "high": 1.15, "low": 1.05,
         "close": 1.1, "volume": 1}
        for i in range(50)
    ]
    api = MagicMock()
    api.get_real_candles = AsyncMock(return_value=seed_candles)
    api.get_payout = AsyncMock(return_value=92)
    mgr = MagicMock()
    mgr._place_flip_trade = AsyncMock(return_value=False)

    with patch("strategy.flip_streamer.RawTickStream", return_value=fake_stream):
        s = FlipStreamer(api, mgr)
        s._running = True
        task = asyncio.create_task(s._consume("EURUSD_otc"))
        await asyncio.sleep(0.05)
        s._running = False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    assert len(seed_called_with) >= 1
    assert not seed_called_with[0].empty


@pytest.mark.asyncio
async def test_streamer_stops_stream_on_error(monkeypatch):
    """stream.stop() is called even when _consume raises."""
    monkeypatch.setattr(flip_streamer, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))

    stop_called = [False]

    class _ErrorStream(_FakeRawTickStream):
        async def __anext__(self):
            raise RuntimeError("deliberate WS error")

        async def stop(self):
            stop_called[0] = True

    fake_stream = _ErrorStream([])
    api = MagicMock()
    api.get_real_candles = AsyncMock(return_value=[])
    api.get_payout = AsyncMock(return_value=92)
    mgr = MagicMock()

    with patch("strategy.flip_streamer.RawTickStream", return_value=fake_stream):
        s = FlipStreamer(api, mgr)
        s._running = True
        task = asyncio.create_task(s._consume("EURUSD_otc"))
        await asyncio.sleep(0.05)
        s._running = False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    assert stop_called[0]
