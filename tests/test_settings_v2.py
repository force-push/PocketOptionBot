import os

from config.settings import BotSettings, settings


def test_v2_defaults_exist():
    assert settings.stake_amount == 1.5
    assert settings.default_expiry_seconds == 30
    assert 30 in settings.allowed_expiries
    assert settings.decisions_log_path.endswith("decisions.jsonl")


    """A ~-prefixed session path must be expanded (Telethon won't do it)."""


    """A plain session name (no ~) is left as-is."""
    cfg = BotSettings(TELEGRAM_SESSION="po_session")
