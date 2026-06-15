"""Offline tests for broker.tick_stream.TickAccumulator and RawTickStream."""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock

from broker.tick_stream import TickAccumulator, RawTickStream, _EPOCH_OFFSET

PAIR = "EURUSD_otc"
BASE_TS = 1_700_000_000  # arbitrary UTC epoch


def _tick(pair: str, ts_utc: float, price: float) -> list:
    """Build a tick frame as the raw handler delivers it (Python list, server epoch)."""
    return [[pair, ts_utc + _EPOCH_OFFSET, price]]


def _history_str(pair: str, ticks: list[tuple[float, float]]) -> str:
    """Build the history-seed JSON string sent right after changeSymbol."""
    import json
    items = [[ts + _EPOCH_OFFSET, px] for ts, px in ticks]
    return json.dumps({"asset": pair, "period": 1, "history": items})


# ── basic tick accumulation ───────────────────────────────────────────────────

def test_no_bar_on_first_tick():
    acc = TickAccumulator(PAIR)
    result = acc.process(_tick(PAIR, BASE_TS + 0.1, 1.1000))
    assert result is None


def test_no_bar_mid_second():
    acc = TickAccumulator(PAIR)
    acc.process(_tick(PAIR, BASE_TS + 0.0, 1.1000))
    acc.process(_tick(PAIR, BASE_TS + 0.3, 1.1001))
    result = acc.process(_tick(PAIR, BASE_TS + 0.7, 1.1002))
    assert result is None  # still same second


def test_bar_emitted_on_second_roll():
    acc = TickAccumulator(PAIR)
    # fill first second
    acc.process(_tick(PAIR, BASE_TS + 0.0, 1.1000))
    acc.process(_tick(PAIR, BASE_TS + 0.5, 1.1010))
    # tick in the next second rolls the first bar into completed
    df = acc.process(_tick(PAIR, BASE_TS + 1.0, 1.1005))
    # 1 completed bar + 1 open bar → to_df returns 1-row DataFrame
    assert df is not None and len(df) == 1

    # another roll gives 2 completed bars
    df = acc.process(_tick(PAIR, BASE_TS + 2.0, 1.1020))
    assert df is not None
    assert len(df) == 2


def test_bar_ohlc_correct():
    acc = TickAccumulator(PAIR)
    acc.process(_tick(PAIR, BASE_TS + 0.0, 1.1000))
    acc.process(_tick(PAIR, BASE_TS + 0.2, 1.1020))  # high
    acc.process(_tick(PAIR, BASE_TS + 0.5, 1.0990))  # low
    acc.process(_tick(PAIR, BASE_TS + 0.8, 1.1010))  # close
    # roll to next second — get this bar as completed
    acc.process(_tick(PAIR, BASE_TS + 1.0, 1.1005))
    df = acc.process(_tick(PAIR, BASE_TS + 2.0, 1.1005))
    assert df is not None
    bar = df.iloc[-1]  # the completed first bar is the second-to-last
    bar0 = df.iloc[0]
    assert bar0["o"] == pytest.approx(1.1000)
    assert bar0["h"] == pytest.approx(1.1020)
    assert bar0["l"] == pytest.approx(1.0990)
    assert bar0["c"] == pytest.approx(1.1010)
    assert bar0["v"] == pytest.approx(4.0)  # 4 ticks


def test_wrong_pair_ignored():
    acc = TickAccumulator(PAIR)
    acc.process(_tick(PAIR, BASE_TS + 0.0, 1.1000))
    # tick for a different pair
    result = acc.process(_tick("AUDUSD_otc", BASE_TS + 1.0, 0.65))
    assert result is None


def test_non_tick_frame_ignored():
    acc = TickAccumulator(PAIR)
    # deal update string — should be silently ignored
    result = acc.process('451-["updateHistoryNewFast",{"_placeholder":true}]')
    assert result is None
    result = acc.process({"not": "a tick"})
    assert result is None


# ── history-seed frame ────────────────────────────────────────────────────────

def test_history_seed_populates_bars():
    acc = TickAccumulator(PAIR)
    hist = [(BASE_TS - 3, 1.1000), (BASE_TS - 2, 1.1010), (BASE_TS - 1, 1.1005)]
    acc.process(_history_str(PAIR, hist))
    # no bar emitted by history frames
    df = acc.to_df()
    # to_df excludes the last bar (treated as open), so at least 2 returned
    assert df is not None and len(df) >= 2


def test_history_seed_wrong_pair_ignored():
    acc = TickAccumulator(PAIR)
    acc.process(_history_str("AUDUSD_otc", [(BASE_TS, 0.65)]))
    assert acc.to_df() is None


def test_history_then_live_tick():
    """Seed from history then add a live tick in the next second."""
    acc = TickAccumulator(PAIR)
    hist = [(BASE_TS - 2, 1.1000), (BASE_TS - 1, 1.1010)]
    acc.process(_history_str(PAIR, hist))
    # live tick one second after last seeded bar
    df = acc.process(_tick(PAIR, float(BASE_TS), 1.1015))
    # new tick is in same second as BASE_TS — not yet a roll
    assert df is None
    # roll to next second
    df = acc.process(_tick(PAIR, float(BASE_TS + 1), 1.1020))
    assert df is not None
    assert len(df) >= 2  # seed bars + new bar


# ── seed_df ───────────────────────────────────────────────────────────────────

def test_seed_df_populates_from_dataframe():
    acc = TickAccumulator(PAIR)
    idx = pd.date_range("2024-01-01 00:00:00", periods=5, freq="s", tz="UTC")
    df_seed = pd.DataFrame({
        "o": [1.1, 1.2, 1.3, 1.4, 1.5],
        "h": [1.15, 1.25, 1.35, 1.45, 1.55],
        "l": [1.05, 1.15, 1.25, 1.35, 1.45],
        "c": [1.12, 1.22, 1.32, 1.42, 1.52],
        "v": [10.0, 10.0, 10.0, 10.0, 10.0],
    }, index=idx)
    acc.seed_df(df_seed)
    df = acc.to_df()
    assert df is not None
    assert len(df) == 4  # 5 seeded bars, last excluded (treated as open)
    assert df.iloc[0]["o"] == pytest.approx(1.1)
    assert df.iloc[0]["h"] == pytest.approx(1.15)


# ── rolling window / pruning ──────────────────────────────────────────────────

def test_rolling_window_prunes_old_bars():
    acc = TickAccumulator(PAIR, history_bars=5)
    for i in range(10):
        acc.process(_tick(PAIR, float(BASE_TS + i), 1.1 + i * 0.001))
        # force roll
        acc.process(_tick(PAIR, float(BASE_TS + i + 0.5), 1.1 + i * 0.001))
    df = acc.to_df()
    # should never exceed history_bars
    assert df is None or len(df) <= 5


# ── DataFrame shape ───────────────────────────────────────────────────────────

def test_to_df_returns_correct_columns():
    acc = TickAccumulator(PAIR)
    hist = [(BASE_TS - 3, 1.1000), (BASE_TS - 2, 1.1010), (BASE_TS - 1, 1.1005)]
    acc.process(_history_str(PAIR, hist))
    df = acc.to_df()
    assert df is not None
    assert list(df.columns) == ["o", "h", "l", "c", "v"]
    assert isinstance(df.index, pd.DatetimeIndex)


def test_to_df_sorted_ascending():
    acc = TickAccumulator(PAIR)
    hist = [(BASE_TS - 3, 1.10), (BASE_TS - 2, 1.11), (BASE_TS - 1, 1.12)]
    acc.process(_history_str(PAIR, hist))
    df = acc.to_df()
    assert df is not None
    assert list(df.index) == sorted(df.index)


# ── RawTickStream (async) ─────────────────────────────────────────────────────


def _make_handler(frames: list) -> MagicMock:
    """Mock raw WS handler whose wait_next() returns frames then hangs."""
    handler = MagicMock()
    frame_iter = iter(frames)

    async def _wait_next():
        try:
            return next(frame_iter)
        except StopIteration:
            # Block indefinitely (simulates a quiet stream); cancelled by stop()
            await asyncio.sleep(3600)

    handler.wait_next = _wait_next
    return handler


def _make_api(frames: list, pair: str = PAIR) -> MagicMock:
    """Mock API client with raw handler + send_raw_message."""
    api = MagicMock()
    api.create_raw_handler = AsyncMock(return_value=_make_handler(frames))
    api.send_raw_message = AsyncMock()
    return api


@pytest.mark.asyncio
async def test_raw_tick_stream_sends_change_symbol():
    api = _make_api([])
    stream = RawTickStream(api, PAIR)
    await stream.start()
    await stream.stop()
    api.send_raw_message.assert_awaited_once()
    msg = api.send_raw_message.await_args[0][0]
    assert f'"asset":"{PAIR}"' in msg
    assert "changeSymbol" in msg


@pytest.mark.asyncio
async def test_raw_tick_stream_yields_bar_on_second_roll():
    frames = [
        _tick(PAIR, BASE_TS + 0.1, 1.1000),
        _tick(PAIR, BASE_TS + 0.5, 1.1010),
        _tick(PAIR, BASE_TS + 1.0, 1.1005),   # rolls first bar
    ]
    api = _make_api(frames)
    stream = RawTickStream(api, PAIR)
    await stream.start()

    df = await asyncio.wait_for(stream.__anext__(), timeout=2.0)
    assert df is not None
    assert len(df) == 1
    assert df.iloc[0]["o"] == pytest.approx(1.1000)
    assert df.iloc[0]["h"] == pytest.approx(1.1010)
    await stream.stop()


@pytest.mark.asyncio
async def test_raw_tick_stream_stop_unblocks_anext():
    api = _make_api([])   # no frames — pump will sit waiting
    stream = RawTickStream(api, PAIR)
    await stream.start()

    async def _stop_soon():
        await asyncio.sleep(0.05)
        await stream.stop()

    task = asyncio.create_task(_stop_soon())
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), timeout=2.0)
    await task


@pytest.mark.asyncio
async def test_raw_tick_stream_seed_included_in_df():
    idx = pd.date_range(
        pd.Timestamp(BASE_TS - 5, unit="s", tz="UTC"),
        periods=5, freq="s",
    )
    seed_df = pd.DataFrame({
        "o": [1.1] * 5, "h": [1.15] * 5, "l": [1.05] * 5,
        "c": [1.12] * 5, "v": [10.0] * 5,
    }, index=idx)

    frames = [
        _tick(PAIR, BASE_TS + 0.1, 1.1020),
        _tick(PAIR, BASE_TS + 1.0, 1.1030),   # rolls bar
    ]
    api = _make_api(frames)
    stream = RawTickStream(api, PAIR)
    stream.seed(seed_df)
    await stream.start()

    df = await asyncio.wait_for(stream.__anext__(), timeout=2.0)
    await stream.stop()
    # seed bars + live bar means df has > 1 row
    assert df is not None and len(df) > 1


@pytest.mark.asyncio
async def test_raw_tick_stream_non_tick_frames_ignored():
    """Non-tick frames (strings, deal updates) don't emit a bar."""
    frames = [
        '451-["updateHistoryNewFast",{"_placeholder":true}]',
        {"not": "a tick"},
        _tick(PAIR, BASE_TS + 0.1, 1.1000),   # real tick — no roll yet
    ]
    api = _make_api(frames)
    stream = RawTickStream(api, PAIR)
    await stream.start()

    # Queue should stay empty — no roll happened
    await asyncio.sleep(0.1)
    assert stream._queue.empty()
    await stream.stop()


@pytest.mark.asyncio
async def test_raw_tick_stream_wrong_pair_frames_ignored():
    frames = [
        _tick("AUDUSD_otc", BASE_TS + 0.1, 0.65),
        _tick("AUDUSD_otc", BASE_TS + 1.0, 0.66),   # would roll if pair matched
    ]
    api = _make_api(frames)
    stream = RawTickStream(api, PAIR)
    await stream.start()

    await asyncio.sleep(0.1)
    assert stream._queue.empty()
    await stream.stop()


@pytest.mark.asyncio
async def test_raw_tick_stream_multiple_bars_queued():
    frames = [
        _tick(PAIR, BASE_TS + 0.1, 1.1000),
        _tick(PAIR, BASE_TS + 1.0, 1.1010),   # bar 1 rolls
        _tick(PAIR, BASE_TS + 2.0, 1.1020),   # bar 2 rolls
        _tick(PAIR, BASE_TS + 3.0, 1.1030),   # bar 3 rolls
    ]
    api = _make_api(frames)
    stream = RawTickStream(api, PAIR)
    await stream.start()

    # Collect three bar emissions
    bars = []
    for _ in range(3):
        df = await asyncio.wait_for(stream.__anext__(), timeout=2.0)
        bars.append(df)
    await stream.stop()

    # Each emission accumulates: 1-bar, 2-bar, 3-bar DataFrames
    assert len(bars[0]) == 1
    assert len(bars[1]) == 2
    assert len(bars[2]) == 3


@pytest.mark.asyncio
async def test_raw_tick_stream_handler_error_is_fail_soft():
    """A transient handler exception doesn't crash the stream or the test."""
    error_count = [0]
    handler = MagicMock()

    async def _wait_next():
        await asyncio.sleep(0)  # yield so the event loop can process cancel signals
        error_count[0] += 1
        if error_count[0] <= 2:
            raise RuntimeError("transient WS error")
        # After failures, deliver a tick pair that rolls a bar
        if error_count[0] == 3:
            return _tick(PAIR, BASE_TS + 0.1, 1.1000)
        return _tick(PAIR, BASE_TS + 1.0, 1.1010)   # rolls

    handler.wait_next = _wait_next
    api = MagicMock()
    api.create_raw_handler = AsyncMock(return_value=handler)
    api.send_raw_message = AsyncMock()

    stream = RawTickStream(api, PAIR)
    await stream.start()

    df = await asyncio.wait_for(stream.__anext__(), timeout=5.0)
    await stream.stop()
    assert df is not None
    assert error_count[0] >= 3   # errors occurred but didn't kill the pump
