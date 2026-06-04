from telegram_feed.direction_parser import parse_direction_screen, DirectionScreen

BUY = ("🟢 **Strong Bullish Setup Detected**\n\n"
       "**MACD** confirms upward momentum, with **RSI** clear of overbought levels. \n\n"
       "**Direction:** 🟢 BUY\n\nSelect trade amount")
SELL = ("🔴 Strong Bearish Setup Detected\n\n"
        "MACD signals downward momentum, with RSI showing no oversold conditions.\n\n"
        "Direction: 🔴 SELL")

def test_buy_maps_to_call():
    d = parse_direction_screen(BUY)
    assert isinstance(d, DirectionScreen)
    assert d.direction == "CALL"
    assert d.setup == "bullish"
    assert "MACD" in d.indicators_raw and "RSI" in d.indicators_raw

def test_sell_maps_to_put():
    d = parse_direction_screen(SELL)
    assert d.direction == "PUT"
    assert d.setup == "bearish"

def test_non_direction_returns_none():
    assert parse_direction_screen("📊 Bot Prediction: …") is None
    assert parse_direction_screen("") is None
