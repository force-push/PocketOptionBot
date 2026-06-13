from config.settings import settings


def test_v2_defaults_exist():
    assert settings.stake_amount == 1.0
    # default_expiry varies by strategy/.env (5s scalping vs 30s); assert the
    # stable invariant that it's one of the allowed expiries, not a fixed value.
    assert settings.default_expiry_seconds in settings.allowed_expiries
    assert 30 in settings.allowed_expiries
    assert settings.decisions_db_path.endswith("decisions.db")
