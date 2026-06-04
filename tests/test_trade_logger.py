# tests/test_trade_logger.py
import json
from strategy.trade_logger import DecisionRow, write_decision, backfill_outcome

def test_write_and_read_row(tmp_path):
    path = tmp_path / "decisions.jsonl"
    row = DecisionRow(
        cycle_id="c1", pair_raw="AUD/USD OTC", pair_api="AUDUSD_otc",
        bot_win_rate=0.78, bot_is_top_pick=True, bot_direction="CALL",
        bot_setup="bullish", bot_indicators_raw="MACD/RSI",
        our_direction="CALL", our_confluence_score=0.81,
        our_signal_breakdown={"RSI": ["CALL", 0.7]},
        agreement=True, combined_probability=0.795, expiry_seconds=30,
        decision="TRADE", skip_reason=None, stake=1.5,
    )
    write_decision(path, row)
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["pair_api"] == "AUDUSD_otc"
    assert rec["decision"] == "TRADE"
    assert rec["ts"].endswith("Z") or "T" in rec["ts"]

def test_backfill_outcome(tmp_path):
    path = tmp_path / "decisions.jsonl"
    row = DecisionRow(cycle_id="c2", pair_raw="X", pair_api="X", bot_win_rate=0.8,
                      bot_is_top_pick=True, bot_direction="CALL", bot_setup="bullish",
                      bot_indicators_raw="", our_direction="CALL", our_confluence_score=0.8,
                      our_signal_breakdown={}, agreement=True, combined_probability=0.8,
                      expiry_seconds=30, decision="TRADE", skip_reason=None, stake=1.5,
                      trade_id="tid9")
    write_decision(path, row)
    backfill_outcome(path, trade_id="tid9", outcome="win", pnl=1.38,
                     balance_before=100.0, balance_after=101.38, pnl_currency="USD")
    rec = json.loads(path.read_text().strip().splitlines()[-1])
    assert rec["outcome"] == "win"
    assert rec["pnl"] == 1.38
    assert rec["balance_after"] == 101.38
