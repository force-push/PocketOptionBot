# tests/test_navigator.py
from telegram_feed.navigator import find_pair_button_text, is_nag_screen, is_direction_screen

def test_find_pair_button_among_menu_buttons():
    btns = ["⬅️ Main Menu", "🏆 AUD/USD OTC ≈78%", "CHF/JPY OTC ≈70%"]
    assert find_pair_button_text(btns, "AUDUSD_otc") == "🏆 AUD/USD OTC ≈78%"

def test_is_nag_screen():
    assert is_nag_screen("⚡ Tokens running low - you can trade anyway", ["🚀 Trade Anyway"]) is True
    assert is_nag_screen("📊 Bot Prediction", []) is False

def test_is_direction_screen():
    assert is_direction_screen("Direction: 🟢 BUY  Select trade amount") is True
    assert is_direction_screen("📊 Bot Prediction") is False
