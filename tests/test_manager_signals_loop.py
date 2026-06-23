"""Tests for _run_once_signals() — Option A payout-first loop."""
import json
import pytest
import asyncio
import pandas as pd
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


def _strength_mgr(pair_wr, pair_n):
    tracker = MagicMock()
    tracker.pair_rate = MagicMock(return_value=(pair_wr, pair_n))
    mgr = object.__new__(StrategyManagerV2)
    mgr._tracker = tracker
    return mgr


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
        monkeypatch.setattr(settings, "variable_stake_enabled", False)
        monkeypatch.setattr(settings, "streaming_enabled", False)
        monkeypatch.setattr(settings, "focus_session_enabled", False)

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
    tracker.pair_rate = MagicMock(return_value=(0.55, 0))

    mgr = StrategyManagerV2(
        api_client=api,
        confluence_engine=conf,
        risk_manager=risk,
        tracker=tracker,
    )
    return mgr


def test_trade_strength_blocks_marginal_overbought_reversal(monkeypatch):
    """USDEGP-style case: marginal pair, CALL into RSI extreme, reversal, level-2 stake."""
    monkeypatch.setattr(settings, "stake_amount", 1.5)
    monkeypatch.setattr(settings, "min_expected_value", 0.0)
    mgr = _strength_mgr(pair_wr=0.51, pair_n=100)
    df = pd.DataFrame([
        {"o": 1.00, "c": 1.02},
        {"o": 1.02, "c": 1.01},
    ])

    strength, penalties, skip = mgr._trade_strength_adjustment(
        pair="USDEGP_otc",
        direction="CALL",
        expiry=5,
        payout_pct=92,
        tracked_rate=0.564,
        n_tracked=39,
        flip_metrics={"rsi": 89.7},
        df=df,
        prospective_stake=7.26,
    )

    assert skip is True
    assert strength < 1 / 1.92
    assert "marginal_pair_wr=51.0%/n=100" in penalties
    # 2026-06-23: soft_direction_wr threshold changed (only fires at wr<=0.50
    # with n>=25). 56.4%/n=39 is now treated as a tradeable direction. The
    # other penalties still combine to skip — proving the safety stack doesn't
    # depend on the directional WR gate alone.
    assert "rsi_extreme_against_entry=89.7" in penalties
    assert "last_candle_reversed" in penalties


def test_trade_strength_keeps_clean_strong_entry(monkeypatch):
    monkeypatch.setattr(settings, "stake_amount", 1.5)
    monkeypatch.setattr(settings, "min_expected_value", 0.0)
    mgr = _strength_mgr(pair_wr=0.62, pair_n=100)
    df = pd.DataFrame([
        {"o": 1.00, "c": 1.01},
        {"o": 1.01, "c": 1.03},
    ])

    strength, penalties, skip = mgr._trade_strength_adjustment(
        pair="AUDUSD_otc",
        direction="CALL",
        expiry=5,
        payout_pct=92,
        tracked_rate=0.64,
        n_tracked=40,
        flip_metrics={"rsi": 63.0},
        df=df,
        prospective_stake=1.5,
    )

    assert skip is False
    assert strength == pytest.approx(0.68)
    assert penalties == []


def test_signal_assessment_records_entry_context(monkeypatch):
    monkeypatch.setattr(settings, "stake_amount", 1.5)
    monkeypatch.setattr(settings, "min_expected_value", 0.0)
    mgr = _strength_mgr(pair_wr=0.51, pair_n=100)
    df = pd.DataFrame([
        {"o": 1.00, "c": 1.02},
        {"o": 1.02, "c": 1.01},
    ])

    assessment = mgr._assess_trade_signal(
        pair="USDEGP_otc",
        direction="CALL",
        expiry=5,
        payout_pct=92,
        tracked_rate=0.564,
        n_tracked=39,
        flip_metrics={"rsi": 89.7},
        df=df,
        prospective_stake=7.26,
        our_confluence=1.0,
        agreeing_signals=3,
        bot_is_top_pick=False,
    )

    assert assessment["skip"] is True
    assert assessment["entry_probability"] < assessment["break_even_probability"]
    assert assessment["pair_recent_wr"] == pytest.approx(0.51)
    assert assessment["direction_wr"] == pytest.approx(0.564)
    assert assessment["rsi_extreme"] is True
    assert assessment["reversal_against_entry"] is True
    assert assessment["martingale_escalated"] is True
    assert "marginal_pair_wr=51.0%/n=100" in assessment["penalties"]
    assert "rsi_extreme_against_entry=89.7" in assessment["summary"]


def test_variable_stake_scales_only_proven_positive_ev(monkeypatch):
    monkeypatch.setattr(settings, "stake_amount", 2.0)
    monkeypatch.setattr(settings, "min_balance_multiplier", 5.0)
    monkeypatch.setattr(settings, "variable_stake_enabled", True)
    monkeypatch.setattr(settings, "variable_stake_min_samples", 25)
    monkeypatch.setattr(settings, "variable_stake_min_multiplier", 0.5)
    monkeypatch.setattr(settings, "variable_stake_min_edge", 0.03)
    monkeypatch.setattr(settings, "variable_stake_full_edge", 0.10)
    monkeypatch.setattr(settings, "variable_stake_max_multiplier", 2.0)
    mgr = _strength_mgr(pair_wr=0.60, pair_n=100)

    cold = mgr._variable_stake_info(
        pair="AUDUSD_otc", direction="CALL", expiry=5, payout_pct=92,
        tracked_rate=0.70, n_tracked=24, balance=1000,
    )
    weak = mgr._variable_stake_info(
        pair="AUDUSD_otc", direction="CALL", expiry=5, payout_pct=92,
        tracked_rate=0.54, n_tracked=100, balance=1000,
    )
    strong = mgr._variable_stake_info(
        pair="AUDUSD_otc", direction="CALL", expiry=5, payout_pct=92,
        tracked_rate=0.70, n_tracked=100, balance=1000,
    )

    assert cold.stake == pytest.approx(2.0)
    assert cold.enabled is False
    assert weak.stake == pytest.approx(1.0)
    assert weak.enabled is True
    assert strong.stake == pytest.approx(4.0)
    assert strong.enabled is True
    assert strong.multiplier == pytest.approx(2.0)


def test_variable_stake_live_style_one_point_five_upside(monkeypatch):
    """Current live policy: marginal WR cuts stake, proven upside caps at 1.5x."""
    monkeypatch.setattr(settings, "stake_amount", 1.5)
    monkeypatch.setattr(settings, "min_balance_multiplier", 5.0)
    monkeypatch.setattr(settings, "variable_stake_enabled", True)
    monkeypatch.setattr(settings, "variable_stake_min_samples", 25)
    monkeypatch.setattr(settings, "variable_stake_min_multiplier", 0.5)
    monkeypatch.setattr(settings, "variable_stake_min_edge", 0.05)
    monkeypatch.setattr(settings, "variable_stake_full_edge", 0.12)
    monkeypatch.setattr(settings, "variable_stake_max_multiplier", 1.5)
    mgr = _strength_mgr(pair_wr=0.60, pair_n=100)

    marginal = mgr._variable_stake_info(
        pair="AUDUSD_otc", direction="CALL", expiry=5, payout_pct=92,
        tracked_rate=0.55, n_tracked=100, balance=1000,
    )
    break_even_92 = 1 / 1.92
    base = mgr._variable_stake_info(
        pair="AUDUSD_otc", direction="CALL", expiry=5, payout_pct=92,
        tracked_rate=break_even_92 + 0.05, n_tracked=100, balance=1000,
    )
    proven = mgr._variable_stake_info(
        pair="AUDUSD_otc", direction="CALL", expiry=5, payout_pct=92,
        tracked_rate=0.65, n_tracked=100, balance=1000,
    )

    assert marginal.stake == pytest.approx(0.75)
    assert marginal.multiplier == pytest.approx(0.5)
    assert base.stake == pytest.approx(1.5)
    assert base.multiplier == pytest.approx(1.0)
    assert proven.stake == pytest.approx(2.25)
    assert proven.multiplier == pytest.approx(1.5)


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
async def test_signals_loop_uses_armed_pair_martingale_stake(tmp_path, monkeypatch):
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.get_real_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    trade = MagicMock(); trade.status = "DRY_RUN"; trade.trade_id = None
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "stake_amount", 1.5)
    monkeypatch.setattr(settings, "martingale_enabled", True)
    monkeypatch.setattr(settings, "martingale_scope", "pair")
    monkeypatch.setattr(settings, "martingale_multiplier", 2.2)
    monkeypatch.setattr(settings, "martingale_max_level", 2)
    monkeypatch.setattr(settings, "martingale_min_pair_wr", 0.0)
    monkeypatch.setattr(settings, "martingale_min_wr_samples", 1)
    monkeypatch.setattr(settings, "martingale_min_session_trades", 1)
    monkeypatch.setattr(settings, "martingale_fast_wr_window_hours", 0.0)
    monkeypatch.setattr(settings, "martingale_slow_wr_window_hours", 0.0)
    monkeypatch.setattr(settings, "trade_stagger_seconds", 0)
    mgr._tracker.pair_rate.return_value = (0.60, 10)
    mgr._martingale.record_outcome("EURUSD", False, max_level=2, multiplier=2.2)

    await mgr.run_once()

    api.buy.assert_awaited()
    assert api.buy.await_args.args[1] == pytest.approx(3.3)
    rows = _read_decisions(tmp_path)
    trade_rows = [r for r in rows if r["decision"] == "TRADE"]
    assert trade_rows[0]["stake"] == pytest.approx(3.3)
    assert trade_rows[0]["martingale_enabled"] is True
    assert trade_rows[0]["martingale_scope"] == "pair"
    assert trade_rows[0]["martingale_key"] == "EURUSD"
    assert trade_rows[0]["martingale_level"] == 1
    assert trade_rows[0]["martingale_escalated"] is True


@pytest.mark.asyncio
async def test_signals_loop_stacks_variable_stake_before_martingale(tmp_path, monkeypatch):
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("AUDUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.get_real_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    trade = MagicMock(); trade.status = "DRY_RUN"; trade.trade_id = None
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "stake_amount", 2.0)
    monkeypatch.setattr(settings, "variable_stake_enabled", True)
    monkeypatch.setattr(settings, "variable_stake_min_samples", 25)
    monkeypatch.setattr(settings, "variable_stake_min_multiplier", 0.5)
    monkeypatch.setattr(settings, "variable_stake_min_edge", 0.03)
    monkeypatch.setattr(settings, "variable_stake_full_edge", 0.10)
    monkeypatch.setattr(settings, "variable_stake_max_multiplier", 2.0)
    monkeypatch.setattr(settings, "martingale_enabled", True)
    monkeypatch.setattr(settings, "martingale_scope", "pair")
    monkeypatch.setattr(settings, "martingale_multiplier", 2.2)
    monkeypatch.setattr(settings, "martingale_max_level", 1)
    monkeypatch.setattr(settings, "martingale_min_pair_wr", 0.0)
    monkeypatch.setattr(settings, "martingale_min_wr_samples", 1)
    monkeypatch.setattr(settings, "martingale_min_session_trades", 1)
    monkeypatch.setattr(settings, "martingale_fast_wr_window_hours", 0.0)
    monkeypatch.setattr(settings, "martingale_slow_wr_window_hours", 0.0)
    monkeypatch.setattr(settings, "trade_stagger_seconds", 0)
    mgr._tracker.rate.return_value = (0.70, 100)
    mgr._tracker.pair_rate.return_value = (0.60, 10)
    mgr._martingale.record_outcome("AUDUSD", False, max_level=1, multiplier=2.2)

    await mgr.run_once()

    api.buy.assert_awaited()
    assert api.buy.await_args.args[1] == pytest.approx(8.8)
    rows = _read_decisions(tmp_path)
    trade_rows = [r for r in rows if r["decision"] == "TRADE"]
    assert trade_rows[0]["stake"] == pytest.approx(8.8)
    assert trade_rows[0]["martingale_level"] == 1
    assert trade_rows[0]["signal_assessment"]["variable_stake"]["enabled"] is True
    assert trade_rows[0]["signal_assessment"]["variable_stake"]["stake"] == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_stream_flip_respects_pair_hour_blocklist(tmp_path, monkeypatch):
    api = MagicMock()
    api.balance = AsyncMock(return_value=1000.0)
    api.buy = AsyncMock()
    api.sell = AsyncMock()

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "strategy_mode", "flip")
    monkeypatch.setattr(settings, "default_expiry_seconds", 5)
    monkeypatch.setattr(settings, "pair_hour_blocklist_enabled", True)
    monkeypatch.setattr(settings, "min_payout_pct", 92)

    from strategy.market_filters import PairHourBlocklist
    monkeypatch.setattr(
        PairHourBlocklist,
        "skip_reason",
        classmethod(lambda cls, pair, hour: f"pair_hour_block: {pair} @ {hour:02d}:00 UTC"),
    )

    placed = await mgr._place_flip_trade(
        "USDARS_otc", "CALL",
        conf_score=1.0,
        flip_metrics={"rsi": 55.0},
        flip_levers={},
        payout_pct=92,
    )

    assert placed is False
    api.buy.assert_not_awaited()
    api.sell.assert_not_awaited()
    rows = _read_decisions(tmp_path)
    assert len(rows) == 1
    assert rows[0]["decision"] == "SKIP"
    assert rows[0]["skip_reason"].startswith("pair_hour_block: USDARS_otc")
    assert rows[0]["bot_setup"] == "flip_stream"


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
    monkeypatch.setattr(settings, "shadow_tf5s_enabled", False)  # isolate: testing pair cap only

    await mgr.run_once()

    # Only 2 pairs should have been evaluated (get_real_candles called once per pair for 1s)
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
    monkeypatch.setattr(settings, "shadows_enabled", True)  # master switch must be on
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
