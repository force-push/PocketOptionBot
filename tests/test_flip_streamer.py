"""Offline test for the event-driven flip streamer wiring."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock

from strategy import flip_streamer
from strategy.flip_streamer import FlipStreamer


def _candles(closes, t0=0):
    return [
        {"timestamp": t0 + i, "open": float(c), "high": float(c) + 0.02,
         "low": float(c) - 0.02, "close": float(c), "volume": 1}
        for i, c in enumerate(closes)
    ]


class _AStream:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(0)
        if self._items:
            return self._items.pop(0)
        raise StopAsyncIteration


_PERMISSIVE_LEVERS = {
    "st_period": 10, "st_multiplier": 3.0, "flip_window_bars": 5,
    "adx_flip_min": 0, "adx_trend_min": 999, "adx_max": 999,
    "require_adx_rising": False, "atr_distance_min": 0.0, "cont_macd_gap_min": 0.0,
}


@pytest.mark.asyncio
async def test_streamer_places_on_fresh_flip(monkeypatch):
    monkeypatch.setattr(flip_streamer, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))
    seed = _candles(list(np.linspace(110, 95, 150)))          # downtrend → PUT side
    up = _candles(list(np.linspace(95, 120, 40)), t0=150)     # sharp reversal → flip CALL

    api = MagicMock()
    api.get_real_candles = AsyncMock(return_value=seed)
    api.create_timed_stream = AsyncMock(return_value=_AStream(up))
    api.get_payout = AsyncMock(return_value=92)
    api.unsubscribe = AsyncMock()

    mgr = MagicMock()
    mgr._place_flip_trade = AsyncMock(return_value=True)

    s = FlipStreamer(api, mgr)
    s._running = True
    task = asyncio.create_task(s._consume("EURUSD_otc"))
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
    # entered CALL on the upward flip
    _args, kwargs = mgr._place_flip_trade.await_args
    assert mgr._place_flip_trade.await_args.args[1] == "CALL"
    assert kwargs["payout_pct"] == 92


@pytest.mark.asyncio
async def test_streamer_start_caps_at_4(monkeypatch):
    api = MagicMock()
    mgr = MagicMock()
    s = FlipStreamer(api, mgr)
    # don't actually run consumers
    monkeypatch.setattr(s, "_consume", AsyncMock())
    await s.start(["A", "B", "C", "D", "E", "F"])
    assert len(s.pairs) == 4
    await s.stop()
