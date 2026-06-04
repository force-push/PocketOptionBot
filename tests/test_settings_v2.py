import os

from config.settings import BotSettings, settings


def test_v2_defaults_exist():
    assert settings.stake_amount == 1.5
    assert settings.default_expiry_seconds == 30
    assert 30 in settings.allowed_expiries
    assert hasattr(settings, "pair_select_min_win_rate")
    assert settings.click_trade_anyway is True
    assert settings.decisions_log_path.endswith("decisions.jsonl")


def test_telegram_session_tilde_is_expanded():
    """A ~-prefixed session path must be expanded (Telethon won't do it)."""
    cfg = BotSettings(TELEGRAM_SESSION="~/.telebot/telegram.session")
    assert not cfg.telegram_session.startswith("~")
    assert cfg.telegram_session == os.path.expanduser("~/.telebot/telegram.session")


def test_telegram_session_plain_name_unchanged():
    """A plain session name (no ~) is left as-is."""
    cfg = BotSettings(TELEGRAM_SESSION="po_session")
    assert cfg.telegram_session == "po_session"
