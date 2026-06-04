from config.settings import settings

def test_v2_defaults_exist():
    assert settings.stake_amount == 1.5
    assert settings.default_expiry_seconds == 30
    assert 30 in settings.allowed_expiries
    assert hasattr(settings, "pair_select_min_win_rate")
    assert settings.click_trade_anyway is True
    assert settings.decisions_log_path.endswith("decisions.jsonl")
