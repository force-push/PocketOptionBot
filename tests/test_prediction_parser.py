# tests/test_prediction_parser.py
from telegram_feed.prediction_parser import parse_prediction, PredictionScreen, PairPrediction

PRED = ("📊 Bot Prediction: \n\nHighest chance to win right now:\n\n"
        "**🏆 AUD/USD OTC: Win rate ≈78%**\n"
        "✅CHF/JPY OTC: Win rate ≈70%\n"
        "✅USD/EGP OTC: Win rate ≈77%\n"
        "✅IRR/USD OTC: Win rate ≈59%\n\n🚀 Make your choice below")

def test_parses_all_pairs():
    scr = parse_prediction(PRED)
    assert isinstance(scr, PredictionScreen)
    assert [p.pair_raw for p in scr.pairs] == [
        "AUD/USD OTC", "CHF/JPY OTC", "USD/EGP OTC", "IRR/USD OTC"]
    assert scr.pairs[0].win_rate == 0.78
    assert scr.pairs[0].is_top is True
    assert scr.pairs[1].is_top is False

def test_top_pick_helper():
    scr = parse_prediction(PRED)
    assert scr.top_pick().pair_raw == "AUD/USD OTC"

def test_non_prediction_returns_none():
    assert parse_prediction("🟢 Strong Bullish Setup Detected") is None
    assert parse_prediction("") is None
