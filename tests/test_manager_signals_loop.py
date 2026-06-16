"""Tests for _run_once_signals() — Option A payout-first loop."""
import json
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from strategy.manager_v2 import StrategyManagerV2
from config.settings import settings, TradeMode
from data import decisions_store as store


def _read_decisions(tmp_path):
    """Read decision rows the manager wrote to the temp SQLite store."""
    db = tmp_path / "decisions.db"
    store.reset_cache(db)
    return store.all_records(db)


def _make_candles(n=60):
    return [{"time": i, "open": 1.0, "high": 1.01, "low": 0.99, "close": 1.0, "volume": 1} for i in range(n)]


def _make_pairs(*pairs):
    """Build a list of asset dicts as returned by get_active_pairs()."""
    return [{"symbol": sym, "payout": pct, "is_active": True} for sym, pct in pairs]


def _make_manager(tmp_path, api, conf_result_by_pair=None, risk_allowed=True, monkeypatch=None, settings=None):
    from config.settings import settings as _settings
    if settings is None:
        settings = _settings
    if monkeypatch:
        monkeypatch.setattr(settings, "decisions_log_path", str(tmp_path / "decisions.jsonl"))
        monkeypatch.setattr(settings, "decisions_db_path", str(tmp_path / "decisions.db"))
        # These tests exercise the legacy confluence path with no allowlist.
        monkeypatch.setattr(settings, "strategy_mode", "confluence")
        monkeypatch.setattr(settings, "allowed_pairs", [])
        monkeypatch.setattr(settings, "min_payout_pct", 92)
        monkeypatch.setattr(settings, "min_confluence_score", 0.0)
        monkeypatch.setattr(settings, "min_signal_agreement", 1)
        monkeypatch.setattr(settings, "max_pairs_per_cycle", 0)
        monkeypatch.setattr(settings, "min_ev_samples", 100)  # disable EV gate in tests

    nav = MagicMock()
    nav.start_autotrade = AsyncMock()
    nav.back_to_menu = AsyncMock()

    conf = MagicMock()
    if conf_result_by_pair is None:
        result = MagicMock()
        result.direction = "CALL"
        result.score = 0.75
        result.reason = "MACD+EMA"
        result.breakdown = {"MACD": ("CALL", 0.8, "bullish"), "EMA_Cross": ("CALL", 0.7, "cross")}
        conf.score = AsyncMock(return_value=result)
    else:
        async def _score_side_effect(df):
            # We can't easily map pair here; just return first result
            return list(conf_result_by_pair.values())[0]
        conf.score = AsyncMock(side_effect=_score_side_effect)

    risk = MagicMock()
    risk.is_allowed = MagicMock(return_value=risk_allowed)
    risk.record_trade = MagicMock()

    tracker = MagicMock()
    tracker.record = MagicMock()
    tracker.rate = MagicMock(return_value=(0.55, 0))

    mgr = StrategyManagerV2(
        api_client=api,
        confluence_engine=conf,
        risk_manager=risk,
        tracker=tracker,
    )
    return mgr


@pytest.mark.asyncio
async def test_signals_loop_places_trade(tmp_path, monkeypatch):
    from config.settings import settings
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94), ("GBPUSD", 93)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.get_real_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    api.get_payout = AsyncMock(return_value=94)
    trade = MagicMock(); trade.status = "PENDING"; trade.trade_id = "tid-sig-1"
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)
    api.poll_trade_outcome = AsyncMock(return_value="win")

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    await mgr.run_once()

    # Should have placed at least one buy (CALL direction)
    api.buy.assert_awaited()

    # the store should have a TRADE row
    rows = _read_decisions(tmp_path)
    trade_rows = [r for r in rows if r["decision"] == "TRADE"]
    assert len(trade_rows) >= 1
    assert trade_rows[0]["pair_api"] in ("EURUSD", "GBPUSD")


@pytest.mark.asyncio
async def test_signals_loop_filters_below_payout_floor(tmp_path, monkeypatch):
    from config.settings import settings
    api = MagicMock()
    # All pairs below 92% floor
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 88), ("GBPUSD", 90)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.get_real_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    api.buy = AsyncMock()
    api.sell = AsyncMock()

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    await mgr.run_once()

    # No trades should be placed
    api.buy.assert_not_awaited()
    api.sell.assert_not_awaited()


@pytest.mark.asyncio
async def test_signals_loop_skips_blocked_pairs(tmp_path, monkeypatch):
    from config.settings import settings
    api = MagicMock()
    # Only blocked pairs above floor
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD_otc", 95), ("ETHUSD_otc", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.get_real_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    api.buy = AsyncMock()
    api.sell = AsyncMock()

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    # Explicitly block the two test pairs so the test doesn't rely on .env state
    monkeypatch.setattr(settings, "blocked_pairs", ["EURUSD_otc", "ETHUSD_otc"])
    await mgr.run_once()

    api.buy.assert_not_awaited()
    api.sell.assert_not_awaited()


@pytest.mark.asyncio
async def test_signals_loop_respects_max_pairs_per_cycle(tmp_path, monkeypatch):
    from config.settings import settings
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(
        ("EURUSD", 95), ("GBPUSD", 94), ("AUDUSD", 93), ("USDJPY", 92)
    ))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.get_real_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    trade = MagicMock(); trade.status = "PENDING"; trade.trade_id = "tid-x"
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)
    api.poll_trade_outcome = AsyncMock(return_value="win")

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "max_pairs_per_cycle", 2)

    await mgr.run_once()

    # Only 2 pairs should have been evaluated (get_candles called twice)
    assert api.get_real_candles.await_count <= 2


@pytest.mark.asyncio
async def test_signals_loop_no_direction_records_skip(tmp_path, monkeypatch):
    from config.settings import settings
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.get_real_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    api.buy = AsyncMock()

    # Confluence returns no direction
    no_dir = MagicMock(); no_dir.direction = None; no_dir.score = 0.2
    no_dir.reason = "insufficient agreement"; no_dir.breakdown = {}
    conf = MagicMock(); conf.score = AsyncMock(return_value=no_dir)

    nav = MagicMock(); nav.back_to_menu = AsyncMock()
    risk = MagicMock(); risk.is_allowed = MagicMock(return_value=True)
    tracker = MagicMock(); tracker.rate = MagicMock(return_value=(0.5, 0))

    monkeypatch.setattr(settings, "decisions_log_path", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setattr(settings, "decisions_db_path", str(tmp_path / "decisions.db"))
    monkeypatch.setattr(settings, "strategy_mode", "confluence")
    monkeypatch.setattr(settings, "allowed_pairs", [])
    monkeypatch.setattr(settings, "min_payout_pct", 92)
    monkeypatch.setattr(settings, "min_ev_samples", 100)

    mgr = StrategyManagerV2(api_client=api, confluence_engine=conf,
                            risk_manager=risk, tracker=tracker)
    await mgr.run_once()

    api.buy.assert_not_awaited()
    rows = _read_decisions(tmp_path)
    assert rows[0]["decision"] == "SKIP"
    assert rows[0]["skip_reason"] == "no_direction"


@pytest.mark.asyncio
async def test_signals_loop_places_shadow_expiry_trades(tmp_path, monkeypatch):
    """A real signals trade is replicated at each SHADOW_EXPIRY_SECONDS duration."""
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.get_real_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    api.get_payout = AsyncMock(return_value=94)

    # Distinct trade_id per placement so rows don't collide.
    _ctr = {"n": 0}
    def _new_trade(*a, **k):
        _ctr["n"] += 1
        t = MagicMock(); t.status = "PENDING"; t.trade_id = f"tid-{_ctr['n']}"
        return t
    api.buy = AsyncMock(side_effect=_new_trade)
    api.sell = AsyncMock(side_effect=_new_trade)
    api.poll_trade_outcome = AsyncMock(return_value="win")

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "trade_mode", TradeMode.DEMO)
    monkeypatch.setattr(settings, "shadow_expiry_seconds", [50, 80, 128, 216])
    monkeypatch.setattr(settings, "trade_stagger_seconds", 0)

    await mgr.run_once()
    # Shadow expiry placements run as background tasks — drain the event loop
    # so all create_task() coroutines complete before we read the log file.
    await asyncio.gather(*[t for t in asyncio.all_tasks() if t is not asyncio.current_task()])

    rows = _read_decisions(tmp_path)
    real = [r for r in rows if r["decision"] == "TRADE" and not r.get("shadow")]
    shadow = [r for r in rows if r.get("shadow") and r.get("shadow_kind") == "expiry"]
    # 1 real trade + 4 shadow expiry trades for the one pair
    assert len(real) == 1
    assert sorted(r["expiry_seconds"] for r in shadow) == [50, 80, 128, 216]
    # All shadow rows carry the same pair + direction as the real trade
    assert all(r["pair_api"] == real[0]["pair_api"] for r in shadow)
    assert all(r["our_direction"] == real[0]["our_direction"] for r in shadow)


@pytest.mark.asyncio
async def test_tf5s_shadow_fires_when_enabled(tmp_path, monkeypatch):
    """When SHADOW_TF5S_ENABLED, a 5s flip signal places tf5s shadow rows at each expiry."""
    from strategy.flip_strategy import FlipDecision

    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles(60))
    api.get_real_candles = AsyncMock(return_value=_make_candles(60))
    api.balance = AsyncMock(return_value=1000.0)
    # DRY_RUN-style mock: trade_id=None prevents resolution background tasks
    # (which would sleep for the expiry duration and slow the test to 30+ s).
    def _dry_trade(*a, **k):
        t = MagicMock(); t.status = "DRY_RUN"; t.trade_id = None
        return t
    api.buy = AsyncMock(side_effect=_dry_trade)
    api.sell = AsyncMock(side_effect=_dry_trade)

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "strategy_mode", "flip")
    monkeypatch.setattr(settings, "shadow_tf5s_enabled", True)
    monkeypatch.setattr(settings, "shadow_tf5s_expiry_seconds", [15, 30])
    monkeypatch.setattr(settings, "trade_mode", TradeMode.DEMO)
    monkeypatch.setattr(settings, "allowed_pairs", [])
    monkeypatch.setattr(settings, "allowed_pair_regex", "")
    monkeypatch.setattr(settings, "trade_stagger_seconds", 0)

    fake_fd = FlipDecision(
        direction="CALL", entry_kind="flip", reason="test-flip",
        metrics={"entry_kind": "flip", "adx": 20.0, "bb_width_bps": 12.0},
    )
    monkeypatch.setattr("strategy.manager_v2.evaluate_flip", lambda df, params: fake_fd)

    await mgr.run_once()
    # Yield several times so the shadow placement tasks (2×_place_single_shadow)
    # can complete. Each does ~2 awaits (balance + buy) then write_decision().
    # We avoid asyncio.gather(*all_tasks) because that also catches resolution
    # tasks that sleep for the full expiry duration (30+ s).
    for _ in range(10):
        await asyncio.sleep(0)

    rows = _read_decisions(tmp_path)
    tf5s = [r for r in rows if r.get("shadow_kind") == "tf5s"]
    assert len(tf5s) == 2, f"expected 2 tf5s rows (15s + 30s), got {len(tf5s)}"
    assert sorted(r["expiry_seconds"] for r in tf5s) == [15, 30]
    assert all(r["our_direction"] == "CALL" for r in tf5s)
    assert all(r.get("shadow") for r in tf5s)


@pytest.mark.asyncio
async def test_tf5s_shadow_disabled_by_default(tmp_path, monkeypatch):
    """No tf5s shadow rows when SHADOW_TF5S_ENABLED=false (default)."""
    from strategy.flip_strategy import FlipDecision

    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles(60))
    api.get_real_candles = AsyncMock(return_value=_make_candles(60))
    api.balance = AsyncMock(return_value=1000.0)
    def _dry_trade(*a, **k):
        t = MagicMock(); t.status = "DRY_RUN"; t.trade_id = None
        return t
    api.buy = AsyncMock(side_effect=_dry_trade)
    api.sell = AsyncMock(side_effect=_dry_trade)

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "strategy_mode", "flip")
    monkeypatch.setattr(settings, "shadow_tf5s_enabled", False)
    monkeypatch.setattr(settings, "trade_mode", TradeMode.DEMO)
    monkeypatch.setattr(settings, "allowed_pairs", [])
    monkeypatch.setattr(settings, "allowed_pair_regex", "")

    fake_fd = FlipDecision(
        direction="CALL", entry_kind="flip", reason="test-flip",
        metrics={"entry_kind": "flip", "adx": 20.0, "bb_width_bps": 12.0},
    )
    monkeypatch.setattr("strategy.manager_v2.evaluate_flip", lambda df, params: fake_fd)

    await mgr.run_once()
    for _ in range(5):
        await asyncio.sleep(0)

    rows = _read_decisions(tmp_path)
    tf5s = [r for r in rows if r.get("shadow_kind") == "tf5s"]
    assert len(tf5s) == 0


@pytest.mark.asyncio
async def test_shadow_expiry_disabled_when_empty(tmp_path, monkeypatch):
    """No shadow expiry trades when SHADOW_EXPIRY_SECONDS is empty."""
    from config.settings import settings, TradeMode
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.get_real_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    trade = MagicMock(); trade.status = "PENDING"; trade.trade_id = "tid-only"
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)
    api.poll_trade_outcome = AsyncMock(return_value="win")

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "trade_mode", TradeMode.DEMO)
    monkeypatch.setattr(settings, "shadow_expiry_seconds", [])

    await mgr.run_once()

    rows = _read_decisions(tmp_path)
    shadow = [r for r in rows if r.get("shadow_kind") == "expiry"]
    assert len(shadow) == 0
