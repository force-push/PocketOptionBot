# tests/test_manager_v2.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from strategy.manager_v2 import StrategyManagerV2

PRED = ("📊 Bot Prediction: \n\nHighest chance to win right now:\n\n"
        "**🏆 AUD/USD OTC: Win rate ≈78%**\n✅CHF/JPY OTC: Win rate ≈70%\n\n🚀 Make your choice below")
DIR_BUY = ("🟢 Strong Bullish Setup Detected\n\nMACD up, RSI fine.\n\nDirection: 🟢 BUY\n\nSelect trade amount")


@pytest.mark.asyncio
async def test_one_cycle_trades_and_logs(tmp_path, monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "pair_select_min_win_rate", 0.0)
    monkeypatch.setattr(settings, "min_confluence_score", 0.0)
    monkeypatch.setattr(settings, "decisions_log_path", str(tmp_path / "decisions.jsonl"))

    nav = MagicMock()
    nav.start_autotrade = AsyncMock()
    # Prediction is now obtained via wait_for_prediction (polls past the AI-analysis
    # status); the direction screen is still read via read_latest_text.
    nav.wait_for_prediction = AsyncMock(return_value=(PRED, ["🏆 AUD/USD OTC", "CHF/JPY OTC"]))
    nav.read_latest_text = AsyncMock(return_value=(DIR_BUY, []))
    nav.select_pair = AsyncMock(return_value=True)
    nav.back_to_menu = AsyncMock()

    api = MagicMock()
    api.get_candles = AsyncMock(return_value=[{"time": i, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for i in range(60)])
    api.balance = AsyncMock(return_value=48592.71)
    trade = MagicMock(); trade.status = "PENDING"; trade.trade_id = "tid42"; trade.id = "trade_1"
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)
    api.check_win = AsyncMock(return_value="win")

    conf = MagicMock()
    conf_result = MagicMock(); conf_result.direction = "CALL"; conf_result.score = 0.81
    conf_result.breakdown = {"RSI": ("CALL", 0.7, "RSI oversold: 28.4")}
    conf.score = AsyncMock(return_value=conf_result)

    risk = MagicMock(); risk.is_allowed = MagicMock(return_value=True); risk.record_trade = MagicMock()
    tracker = MagicMock(); tracker.record = MagicMock()

    mgr = StrategyManagerV2(navigator=nav, api_client=api, confluence_engine=conf,
                            risk_manager=risk, tracker=tracker)
    await mgr.run_once()

    api.buy.assert_awaited_once()
    rows = [json.loads(l) for l in (tmp_path / "decisions.jsonl").read_text().splitlines()]
    assert rows[-1]["decision"] == "TRADE"
    assert rows[-1]["outcome"] == "win"
    assert rows[-1]["our_direction"] == "CALL"
