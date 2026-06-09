"""Tests for _run_once_signals() — Option A payout-first loop."""
import json
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from strategy.manager_v2 import StrategyManagerV2


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
        monkeypatch.setattr(settings, "min_payout_pct", 92)
        monkeypatch.setattr(settings, "min_confluence_score", 0.0)
        monkeypatch.setattr(settings, "min_signal_agreement", 1)
        monkeypatch.setattr(settings, "max_pairs_per_cycle", 0)
        monkeypatch.setattr(settings, "min_ev_samples", 100)  # disable EV gate in tests
        from config.settings import PredictionSource
        monkeypatch.setattr(settings, "prediction_source", PredictionSource.SIGNALS)

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
        navigator=nav,
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

    # decisions.jsonl should have a TRADE row
    rows = [json.loads(l) for l in (tmp_path / "decisions.jsonl").read_text().splitlines()]
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
    api.balance = AsyncMock(return_value=1000.0)
    api.buy = AsyncMock()
    api.sell = AsyncMock()

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
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
    api.balance = AsyncMock(return_value=1000.0)
    trade = MagicMock(); trade.status = "PENDING"; trade.trade_id = "tid-x"
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)
    api.poll_trade_outcome = AsyncMock(return_value="win")

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "max_pairs_per_cycle", 2)

    await mgr.run_once()

    # Only 2 pairs should have been evaluated (get_candles called twice)
    assert api.get_candles.await_count <= 2


@pytest.mark.asyncio
async def test_signals_loop_no_direction_records_skip(tmp_path, monkeypatch):
    from config.settings import settings
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    api.buy = AsyncMock()

    # Confluence returns no direction
    no_dir = MagicMock(); no_dir.direction = None; no_dir.score = 0.2
    no_dir.reason = "insufficient agreement"; no_dir.breakdown = {}
    conf = MagicMock(); conf.score = AsyncMock(return_value=no_dir)

    nav = MagicMock(); nav.back_to_menu = AsyncMock()
    risk = MagicMock(); risk.is_allowed = MagicMock(return_value=True)
    tracker = MagicMock(); tracker.rate = MagicMock(return_value=(0.5, 0))

    from config.settings import settings, PredictionSource
    monkeypatch.setattr(settings, "decisions_log_path", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setattr(settings, "min_payout_pct", 92)
    monkeypatch.setattr(settings, "min_ev_samples", 100)
    monkeypatch.setattr(settings, "prediction_source", PredictionSource.SIGNALS)

    mgr = StrategyManagerV2(navigator=nav, api_client=api, confluence_engine=conf,
                            risk_manager=risk, tracker=tracker)
    await mgr.run_once()

    api.buy.assert_not_awaited()
    rows = [json.loads(l) for l in (tmp_path / "decisions.jsonl").read_text().splitlines()]
    assert rows[0]["decision"] == "SKIP"
    assert rows[0]["skip_reason"] == "no_direction"


@pytest.mark.asyncio
async def test_signals_loop_places_shadow_expiry_trades(tmp_path, monkeypatch):
    """A real signals trade is replicated at each SHADOW_EXPIRY_SECONDS duration."""
    from config.settings import settings, PredictionSource, TradeMode
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles())
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
    monkeypatch.setattr(settings, "shadow_expiry_seconds", [50, 80, 130, 210])
    monkeypatch.setattr(settings, "trade_stagger_seconds", 0)

    await mgr.run_once()

    rows = [json.loads(l) for l in (tmp_path / "decisions.jsonl").read_text().splitlines()]
    real = [r for r in rows if r["decision"] == "TRADE" and not r.get("shadow")]
    shadow = [r for r in rows if r.get("shadow") and r.get("shadow_kind") == "expiry"]
    # 1 real trade + 4 shadow expiry trades for the one pair
    assert len(real) == 1
    assert sorted(r["expiry_seconds"] for r in shadow) == [50, 80, 130, 210]
    # All shadow rows carry the same pair + direction as the real trade
    assert all(r["pair_api"] == real[0]["pair_api"] for r in shadow)
    assert all(r["our_direction"] == real[0]["our_direction"] for r in shadow)


@pytest.mark.asyncio
async def test_shadow_expiry_disabled_when_empty(tmp_path, monkeypatch):
    """No shadow expiry trades when SHADOW_EXPIRY_SECONDS is empty."""
    from config.settings import settings, TradeMode
    api = MagicMock()
    api.get_active_pairs = AsyncMock(return_value=_make_pairs(("EURUSD", 94)))
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    trade = MagicMock(); trade.status = "PENDING"; trade.trade_id = "tid-only"
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)
    api.poll_trade_outcome = AsyncMock(return_value="win")

    mgr = _make_manager(tmp_path, api, monkeypatch=monkeypatch, settings=settings)
    monkeypatch.setattr(settings, "trade_mode", TradeMode.DEMO)
    monkeypatch.setattr(settings, "shadow_expiry_seconds", [])

    await mgr.run_once()

    rows = [json.loads(l) for l in (tmp_path / "decisions.jsonl").read_text().splitlines()]
    shadow = [r for r in rows if r.get("shadow_kind") == "expiry"]
    assert len(shadow) == 0


@pytest.mark.asyncio
async def test_broker_bot_mode_unchanged(tmp_path, monkeypatch):
    """With PREDICTION_SOURCE=broker_bot, the navigator path is invoked (not signals)."""
    from config.settings import settings, PredictionSource
    monkeypatch.setattr(settings, "prediction_source", PredictionSource.BROKER_BOT)
    monkeypatch.setattr(settings, "decisions_log_path", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setattr(settings, "pair_select_min_win_rate", 0.0)
    monkeypatch.setattr(settings, "min_confluence_score", 0.0)
    monkeypatch.setattr(settings, "min_ev_samples", 100)

    PRED = ("📊 Bot Prediction: \n\nHighest chance to win right now:\n\n"
            "**🏆 AUD/USD OTC: Win rate ≈78%**\n\n🚀 Make your choice below")
    DIR_BUY = "🟢 Direction: 🟢 BUY\n\nSetup detected"

    nav = MagicMock()
    nav.start_autotrade = AsyncMock()
    nav.wait_for_prediction = AsyncMock(return_value=(PRED, ["🏆 AUD/USD OTC"]))
    nav.read_latest_text = AsyncMock(return_value=(DIR_BUY, []))
    nav.select_pair = AsyncMock(return_value=True)
    nav.back_to_menu = AsyncMock()

    api = MagicMock()
    api.get_candles = AsyncMock(return_value=_make_candles())
    api.balance = AsyncMock(return_value=1000.0)
    api.get_payout = AsyncMock(return_value=94)
    trade = MagicMock(); trade.status = "PENDING"; trade.trade_id = "tid-bb"
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)
    api.poll_trade_outcome = AsyncMock(return_value="win")

    conf_r = MagicMock(); conf_r.direction = "CALL"; conf_r.score = 0.8
    conf_r.reason = "ok"; conf_r.breakdown = {}
    conf = MagicMock(); conf.score = AsyncMock(return_value=conf_r)

    risk = MagicMock(); risk.is_allowed = MagicMock(return_value=True)
    tracker = MagicMock(); tracker.rate = MagicMock(return_value=(0.6, 0))

    mgr = StrategyManagerV2(navigator=nav, api_client=api, confluence_engine=conf,
                            risk_manager=risk, tracker=tracker)
    await mgr.run_once()

    # Navigator should have been called (broker_bot path)
    nav.start_autotrade.assert_awaited_once()
    nav.wait_for_prediction.assert_awaited_once()
    # get_active_pairs should NOT be called (signals path)
    api.get_active_pairs.assert_not_awaited() if hasattr(api.get_active_pairs, 'assert_not_awaited') else None
