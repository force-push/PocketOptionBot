"""Offline tests for FocusSessionManager (raw-tick stream edition)."""
from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from strategy import focus_session as fs_module
from strategy.focus_session import (
    FocusSessionManager, _ILLIQUID_COOLDOWN, _disconnect_backoff,
    _BACKOFF_MAX, _BACKOFF_BASE,
)


# ── disconnect backoff (Tier 2 memory/hot-loop fix) ───────────────────────────

def test_disconnect_backoff_exponential_and_capped():
    assert _disconnect_backoff(0) == 0.0
    assert _disconnect_backoff(1) == _BACKOFF_BASE
    assert _disconnect_backoff(2) == _BACKOFF_BASE * 2
    assert _disconnect_backoff(3) == _BACKOFF_BASE * 4
    # grows but never exceeds the cap
    assert _disconnect_backoff(50) == _BACKOFF_MAX
    assert all(_disconnect_backoff(n) <= _BACKOFF_MAX for n in range(0, 100))


@pytest.mark.asyncio
async def test_run_backs_off_on_fast_fail(monkeypatch):
    """A pair session that returns instantly with 0 trades triggers a backoff
    sleep instead of hot-looping."""
    _clear_pair_filters(monkeypatch)
    api = _make_api()
    mgr = _make_mgr()
    fsm = FocusSessionManager(api, mgr)
    fsm._running = True

    # _pick_pair always returns a pair; _run_pair_session returns immediately
    # (simulating a disconnect/stream-setup failure with no trades).
    async def _instant_session(pair):
        return
    monkeypatch.setattr(fsm, "_pick_pair", AsyncMock(return_value="EURUSD_otc"))
    monkeypatch.setattr(fsm, "_run_pair_session", _instant_session)

    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def _spy_sleep(secs):
        sleeps.append(secs)
        if len(sleeps) >= 3:        # let a few iterations run, then stop the loop
            fsm._running = False
        await real_sleep(0)         # yield without real delay
    monkeypatch.setattr(fs_module.asyncio, "sleep", _spy_sleep)

    await fsm._run()

    # backoffs recorded and they escalate (2, 4, ...) — i.e. not a hot-loop
    assert len(sleeps) >= 2
    assert sleeps[0] == _BACKOFF_BASE
    assert sleeps[1] == _BACKOFF_BASE * 2


# ── helpers ───────────────────────────────────────────────────────────────────

PAIR = "EURUSD_otc"

_PERMISSIVE_LEVERS = {
    "st_period": 10, "st_multiplier": 3.0, "flip_window_bars": 5,
    "adx_flip_min": 0, "adx_trend_min": 999, "adx_max": 999,
    "require_adx_rising": False, "atr_distance_min": 0.0,
    "atr_distance_max": 999.0, "cont_macd_gap_min": 0.0, "cont_rsi_min": 0.0,
}


def _make_df(closes, t0: int = 0) -> pd.DataFrame:
    idx = pd.date_range(
        pd.Timestamp(t0, unit="s", tz="UTC"), periods=len(closes), freq="s"
    )
    closes = np.array(closes, dtype=float)
    return pd.DataFrame(
        {"o": closes, "h": closes + 0.01, "l": closes - 0.01,
         "c": closes, "v": np.ones(len(closes))},
        index=idx,
    )


class _FakeStream:
    """Mock RawTickStream: yields DataFrames then raises StopAsyncIteration."""

    def __init__(self, dfs, *, start_event=None, bar_delay=0.0):
        self._dfs = list(dfs)
        self._start_event = start_event
        self._bar_delay = bar_delay
        self.stop_called = False
        self.seed_df = None

    async def start(self):
        if self._start_event:
            self._start_event.set()

    async def stop(self):
        self.stop_called = True

    def seed(self, df):
        self.seed_df = df

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(self._bar_delay)
        if self._dfs:
            return self._dfs.pop(0)
        raise StopAsyncIteration


def _make_api(pair=PAIR, payout=92, active_pairs=None):
    api = MagicMock()
    api.get_real_candles = AsyncMock(return_value=[])
    api.get_payout = AsyncMock(return_value=payout)
    if active_pairs is None:
        active_pairs = [{"symbol": pair, "payout": payout, "is_active": True}]
    api.get_active_pairs = AsyncMock(return_value=active_pairs)
    api.unsubscribe = AsyncMock()
    return api


def _make_mgr(place_return=True):
    mgr = MagicMock()
    mgr._place_flip_trade = AsyncMock(return_value=place_return)
    # Default: no perf tracker and no post-loss cooldown (MagicMock would auto-create
    # truthy attrs that break ranking / exclude every pair). Tests set them explicitly.
    mgr.tracker = None
    mgr._pair_cooldown = None
    return mgr


# ── _run_pair_session ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_places_trade_on_flip(monkeypatch):
    """A valid flip signal causes _place_flip_trade to be called."""
    monkeypatch.setattr(fs_module, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))

    down = list(np.linspace(110, 95, 150))
    up = list(np.linspace(95, 120, 40))
    all_closes = down + up
    dfs = [_make_df(all_closes[: 150 + i + 1]) for i in range(40)]

    fake_stream = _FakeStream(dfs)
    api = _make_api()
    mgr = _make_mgr()

    fsm = FocusSessionManager(api, mgr)
    fsm._running = True
    with patch.object(fs_module, "RawTickStream", return_value=fake_stream):
        await fsm._run_pair_session(PAIR)

    assert mgr._place_flip_trade.await_count >= 1
    args = mgr._place_flip_trade.await_args.args
    assert args[1] == "CALL"


@pytest.mark.asyncio
async def test_session_rotates_after_quota(monkeypatch):
    """Session exits once focus_session_trades trades are placed."""
    monkeypatch.setattr(fs_module, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))
    # Disable inter-trade delay so bars are processed immediately in the test.
    monkeypatch.setattr(fs_module.settings, "default_expiry_seconds", 0)

    down = list(np.linspace(110, 95, 150))
    up = list(np.linspace(95, 120, 40))
    all_closes = down + up
    # Enough DataFrames for many trades
    dfs = [_make_df(all_closes[: 150 + i + 1]) for i in range(40)] * 5

    fake_stream = _FakeStream(dfs)
    api = _make_api()
    mgr = _make_mgr(place_return=True)

    fsm = FocusSessionManager(api, mgr)
    fsm._running = True
    target = fs_module.settings.focus_session_trades

    with patch.object(fs_module, "RawTickStream", return_value=fake_stream):
        await fsm._run_pair_session(PAIR)

    assert fsm.session_trades == target


@pytest.mark.asyncio
async def test_session_seeds_from_history(monkeypatch):
    """get_real_candles result is passed to stream.seed()."""
    monkeypatch.setattr(fs_module, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))

    seed_candles = [
        {"time": 1700000000 + i, "open": 1.1, "high": 1.15, "low": 1.05,
         "close": 1.1, "volume": 1}
        for i in range(60)
    ]
    fake_stream = _FakeStream([])
    api = _make_api()
    api.get_real_candles = AsyncMock(return_value=seed_candles)
    mgr = _make_mgr()

    fsm = FocusSessionManager(api, mgr)
    with patch.object(fs_module, "RawTickStream", return_value=fake_stream):
        await fsm._run_pair_session(PAIR)

    assert fake_stream.seed_df is not None
    assert not fake_stream.seed_df.empty


@pytest.mark.asyncio
async def test_session_stops_stream_on_exit(monkeypatch):
    """stream.stop() is always called when _run_pair_session returns."""
    monkeypatch.setattr(fs_module, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))

    fake_stream = _FakeStream([])   # immediately StopAsyncIteration
    api = _make_api()
    mgr = _make_mgr()

    fsm = FocusSessionManager(api, mgr)
    with patch.object(fs_module, "RawTickStream", return_value=fake_stream):
        await fsm._run_pair_session(PAIR)

    assert fake_stream.stop_called


@pytest.mark.asyncio
async def test_session_rotates_on_payout_drop(monkeypatch):
    """Session exits early if payout falls below floor mid-session."""
    monkeypatch.setattr(fs_module, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))

    # Provide enough bars to trigger a payout check (_PAYOUT_CHECK_BARS = 30)
    dfs = [_make_df([1.1] * 50)] * 35

    fake_stream = _FakeStream(dfs)
    api = _make_api(payout=80)   # below the 92% floor
    mgr = _make_mgr(place_return=False)

    fsm = FocusSessionManager(api, mgr)
    fsm._running = True
    with patch.object(fs_module, "RawTickStream", return_value=fake_stream):
        await fsm._run_pair_session(PAIR)

    # Should have exited without placing trades (no flip signal + payout drop exit)
    assert fake_stream.stop_called


@pytest.mark.asyncio
async def test_session_marks_illiquid_on_no_bars(monkeypatch):
    """Pair is added to illiquid cooldown when too few bars arrive in time limit."""
    monkeypatch.setattr(fs_module, "load_levers", lambda: dict(_PERMISSIVE_LEVERS))
    # Patch the bar timeout and elapsed threshold to millisecond scale so this
    # test completes in <1s without real wall-clock waiting.
    monkeypatch.setattr(fs_module, "_BAR_TIMEOUT", 0.05)   # 50ms bar timeout
    monkeypatch.setattr(fs_module, "_ILLIQUID_ELAPSED", 0)  # any elapsed triggers it

    class _HangStream(_FakeStream):
        """Stream that never emits a bar (simulates illiquid pair)."""
        async def __anext__(self):
            await asyncio.sleep(3600)   # blocked; cancelled by _BAR_TIMEOUT

    fake_stream = _HangStream([])
    api = _make_api()
    mgr = _make_mgr()
    fsm = FocusSessionManager(api, mgr)
    fsm._running = True

    with patch.object(fs_module, "RawTickStream", return_value=fake_stream):
        await asyncio.wait_for(fsm._run_pair_session(PAIR), timeout=2.0)

    assert PAIR in fsm._illiquid


# ── _pick_pair ────────────────────────────────────────────────────────────────

def _clear_pair_filters(monkeypatch):
    """Neutralise the .env pair-filter config so a test controls it explicitly."""
    monkeypatch.setattr(fs_module.settings, "allowed_pair_regex", "")
    monkeypatch.setattr(fs_module.settings, "allowed_pairs", [])
    monkeypatch.setattr(fs_module.settings, "blocked_pairs", [])
    monkeypatch.setattr(fs_module.settings, "focus_payout_floor", 90)
    monkeypatch.setattr(fs_module.settings, "streaming_enabled", False)


@pytest.mark.asyncio
async def test_pick_pair_returns_highest_payout(monkeypatch):
    _clear_pair_filters(monkeypatch)
    active = [
        {"symbol": "EURUSD_otc", "payout": 94, "is_active": True},
        {"symbol": "AUDUSD_otc", "payout": 92, "is_active": True},
        {"symbol": "GBPUSD_otc", "payout": 89, "is_active": True},
    ]
    api = _make_api(active_pairs=active)
    api.get_active_pairs = AsyncMock(return_value=active)
    mgr = _make_mgr()
    fsm = FocusSessionManager(api, mgr)

    result = await fsm._pick_pair()
    assert result == "EURUSD_otc"


@pytest.mark.asyncio
async def test_pick_pair_skips_below_floor(monkeypatch):
    _clear_pair_filters(monkeypatch)
    active = [
        {"symbol": "EURUSD_otc", "payout": 85, "is_active": True},
    ]
    api = _make_api(active_pairs=active)
    api.get_active_pairs = AsyncMock(return_value=active)
    mgr = _make_mgr()
    fsm = FocusSessionManager(api, mgr)

    result = await fsm._pick_pair()
    assert result is None


@pytest.mark.asyncio
async def test_pick_pair_honors_allowlist(monkeypatch):
    """When ALLOWED_PAIRS is set it is authoritative — only those symbols picked."""
    _clear_pair_filters(monkeypatch)
    active = [
        {"symbol": "EURUSD_otc", "payout": 96, "is_active": True},   # highest, not allowed
        {"symbol": "AUDUSD_otc", "payout": 92, "is_active": True},   # allowed
        {"symbol": "GBPUSD_otc", "payout": 95, "is_active": True},   # not allowed
    ]
    api = _make_api(active_pairs=active)
    api.get_active_pairs = AsyncMock(return_value=active)
    mgr = _make_mgr()
    fsm = FocusSessionManager(api, mgr)

    monkeypatch.setattr(fs_module.settings, "allowed_pairs", ["AUDUSD_otc"])
    result = await fsm._pick_pair()
    assert result == "AUDUSD_otc"   # not EURUSD/GBPUSD despite higher payout


@pytest.mark.asyncio
async def test_pick_pair_honors_regex(monkeypatch):
    """ALLOWED_PAIR_REGEX is authoritative and excludes GBP via lookahead."""
    _clear_pair_filters(monkeypatch)
    monkeypatch.setattr(fs_module.settings, "allowed_pair_regex",
                        "^(?!.*GBP).*(USD|CNY|CNH|EUR)")
    active = [
        {"symbol": "GBPUSD_otc", "payout": 97, "is_active": True},   # highest but GBP → excluded
        {"symbol": "CADCHF_otc", "payout": 96, "is_active": True},   # no USD/CNY/EUR → excluded
        {"symbol": "EURUSD_otc", "payout": 93, "is_active": True},   # matches
    ]
    api = _make_api(active_pairs=active)
    api.get_active_pairs = AsyncMock(return_value=active)
    mgr = _make_mgr()
    fsm = FocusSessionManager(api, mgr)

    result = await fsm._pick_pair()
    assert result == "EURUSD_otc"


@pytest.mark.asyncio
async def test_pick_pair_bumps_high_performers(monkeypatch, tmp_path):
    """A proven high-WR pair outranks a higher-payout unproven pair."""
    _clear_pair_filters(monkeypatch)
    active = [
        {"symbol": "EURUSD_otc", "payout": 96, "is_active": True},   # higher payout, no history
        {"symbol": "AUDUSD_otc", "payout": 92, "is_active": True},   # lower payout, proven winner
    ]
    api = _make_api(active_pairs=active)
    api.get_active_pairs = AsyncMock(return_value=active)

    from strategy.win_rate import WinRateTracker
    tr = WinRateTracker(json_path=tmp_path / "wr.json")
    for _ in range(9):
        tr.record("AUDUSD_otc", "CALL", 5, "win")
    for _ in range(3):
        tr.record("AUDUSD_otc", "CALL", 5, "loss")   # 9/12 = 75%, n=12 ≥ _RANK_MIN_SAMPLES
    mgr = MagicMock()
    mgr._place_flip_trade = AsyncMock(return_value=True)
    mgr.tracker = tr
    mgr._pair_cooldown = None
    fsm = FocusSessionManager(api, mgr)

    result = await fsm._pick_pair()
    assert result == "AUDUSD_otc"   # proven winner bumped above higher-payout unproven


@pytest.mark.asyncio
async def test_pick_pair_skips_post_loss_cooldown(monkeypatch):
    """A pair on per-pair post-loss cooldown is skipped; rotation picks the next."""
    _clear_pair_filters(monkeypatch)
    active = [
        {"symbol": "EURUSD_otc", "payout": 96, "is_active": True},   # higher, but cooling
        {"symbol": "AUDUSD_otc", "payout": 92, "is_active": True},
    ]
    api = _make_api(active_pairs=active)
    api.get_active_pairs = AsyncMock(return_value=active)

    from strategy.pair_cooldown import PairCooldown
    mgr = _make_mgr()
    mgr._pair_cooldown = PairCooldown(seconds=60)
    mgr._pair_cooldown.record_loss("EURUSD_otc")   # just lost → cooling
    fsm = FocusSessionManager(api, mgr)

    result = await fsm._pick_pair()
    assert result == "AUDUSD_otc"   # rotated off the cooling higher-payout pair


@pytest.mark.asyncio
async def test_pick_pair_skips_illiquid(monkeypatch):
    _clear_pair_filters(monkeypatch)
    active = [
        {"symbol": "EURUSD_otc", "payout": 94, "is_active": True},
        {"symbol": "AUDUSD_otc", "payout": 96, "is_active": True},
    ]
    api = _make_api(active_pairs=active)
    api.get_active_pairs = AsyncMock(return_value=active)
    mgr = _make_mgr()
    fsm = FocusSessionManager(api, mgr)

    # Mark AUDUSD (higher payout) as illiquid
    loop = asyncio.get_event_loop()
    fsm._illiquid["AUDUSD_otc"] = loop.time()

    result = await fsm._pick_pair()
    assert result == "EURUSD_otc"
