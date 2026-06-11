"""Offline tests for dashboard.settings_io.

Pure logic only — masking, grouping, SSID demo decode, partial-update validation,
and the LIVE/SSID guard. Field validation is delegated to BotSettings in
production; here we inject a fake ``validator`` so the tests run with stdlib +
pytest only (no pydantic needed in this sandbox).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from dashboard import settings_io as sio

# SSID samples (mirrors the 42["auth",{...}] frame the bot parses).
SSID_DEMO = '42["auth",{"session":"abc","isDemo":1,"uid":42,"platform":1}]'
SSID_LIVE = '42["auth",{"session":"abc","isDemo":0,"uid":42,"platform":1}]'
SSID_NOFLAG = '42["auth",{"session":"abc","uid":42}]'


class _Mode:
    """Stand-in for the TradeMode StrEnum (has a .value)."""
    def __init__(self, v):
        self.value = v


def make_settings(*, mode="DEMO", ssid=SSID_DEMO):
    """A lightweight stand-in for the BotSettings singleton."""
    return SimpleNamespace(
        trade_mode=_Mode(mode),
        dry_run=True,
        stake_amount=1.5,
        default_expiry_seconds=30,
        telegram_api_id=2040123,
        telegram_api_hash="super-secret-hash",
        signal_bot_username="po_broker_bot",
        po_ssid=ssid,
        pair_select_min_win_rate=0.82,
        min_confluence_score=0.75,
        click_trade_anyway=True,
        max_trades_per_hour=10,
        max_daily_loss_usd=25.0,
        cooldown_after_loss_seconds=120,
        min_balance_multiplier=5.0,
    )


# a no-op validator that always accepts (production uses BotSettings)
def _accept(env_overrides):
    return None


def _reject(msg="bad value"):
    def _v(env_overrides):
        raise ValueError(msg)
    return _v


# ── SSID decode ───────────────────────────────────────────────────────────────

def test_ssid_is_demo_decode():
    assert sio.ssid_is_demo(SSID_DEMO) is True
    assert sio.ssid_is_demo(SSID_LIVE) is False
    assert sio.ssid_is_demo(SSID_NOFLAG) is None
    assert sio.ssid_is_demo("") is None
    assert sio.ssid_is_demo("garbage") is None


# ── read_settings: masking + grouping ─────────────────────────────────────────

def _flat_fields(out):
    """Flatten the grouped array into {key: field} (the UI shape)."""
    return {f["key"]: f for grp in out["groups"] for f in grp["fields"]}


def test_read_settings_masks_secrets():
    out = sio.read_settings(make_settings())
    flat = _flat_fields(out)
    # secrets present in groups but masked
    assert flat["PO_SSID"]["value"] == sio.MASK
    assert flat["PO_SSID"]["value"] == sio.MASK
    # real secret value never appears anywhere
    blob = repr(out)
    assert "super-secret-hash" not in blob
    assert "isDemo" not in blob  # the SSID itself is not leaked
    # non-secrets pass through
    assert flat["STAKE_AMOUNT"]["value"] == 1.5
    assert flat["TRADE_MODE"]["value"] == "DEMO"
    # detected ssid mode
    assert out["detected"]["ssid_mode"] == "DEMO"


def test_read_settings_groups_mirror_mockup():
    out = sio.read_settings(make_settings())
    # groups is an ORDERED array of cards with display metadata (UI shape).
    assert isinstance(out["groups"], list)
    ids = [g["id"] for g in out["groups"]]
    assert ids == ["safety", "gate", "ta", "risk", "pocketoption"]
    safety = out["groups"][0]
    assert safety["span2"] is True and safety["title"] == "Safety & Trade Mode"
    assert all("fields" in g and g["fields"] for g in out["groups"])


def test_read_settings_ui_control_types():
    """Lock the control-type contract consumed by components/settings.js."""
    flat = _flat_fields(sio.read_settings(make_settings()))
    assert flat["TRADE_MODE"]["type"] == "mode"
    assert flat["DRY_RUN"]["type"] == "toggle"
    assert flat["PO_SSID"]["type"] == "secret"
    assert flat["STAKE_AMOUNT"]["type"] == "number" and flat["STAKE_AMOUNT"]["step"] == 0.5
    # the read-only "Detected Mode" pill is injected into the PocketOption card
    assert flat["_detected_mode"]["type"] == "pill"
    assert flat["_detected_mode"]["value"].startswith("DEMO")
    # POST body is keyed by env var name — every real field exposes `key`
    assert flat["MAX_DAILY_LOSS_USD"]["label"] == "Daily Loss Limit (USD)"


def test_read_settings_empty_secret_not_masked():
    s = make_settings()
    s.po_ssid = ""
    out = sio.read_settings(s)
    flat = _flat_fields(out)
    assert flat["PO_SSID"]["value"] == ""
    assert out["detected"]["ssid_mode"] == "UNKNOWN"


# ── validate_update: partial validation ───────────────────────────────────────

def test_validate_accepts_known_fields():
    res = sio.validate_update(
        {"STAKE_AMOUNT": 2.0, "DRY_RUN": "false"},
        settings_obj=make_settings(), validator=_accept,
    )
    assert res["ok"] is True
    assert res["applied"]["STAKE_AMOUNT"] == 2.0
    assert res["applied"]["DRY_RUN"] is False
    # env overrides serialised for dotenv
    assert res["_env_overrides"]["DRY_RUN"] == "false"


def test_validate_rejects_unknown_field():
    res = sio.validate_update(
        {"NOT_A_SETTING": 1}, settings_obj=make_settings(), validator=_accept,
    )
    assert res["ok"] is False
    assert "NOT_A_SETTING" in res["errors"]


def test_validate_bad_type_reports_error():
    res = sio.validate_update(
        {"DEFAULT_EXPIRY_SECONDS": "notanint"},
        settings_obj=make_settings(), validator=_accept,
    )
    assert res["ok"] is False
    assert "DEFAULT_EXPIRY_SECONDS" in res["errors"]


def test_validate_secret_mask_is_skipped():
    # supplying the mask means "leave unchanged" — not written.
    res = sio.validate_update(
        {"PO_SSID": sio.MASK}, settings_obj=make_settings(), validator=_accept,
    )
    assert res["ok"] is True
    assert "PO_SSID" not in res["applied"]


def test_validate_secret_real_value_written_masked_in_response():
    res = sio.validate_update(
        {"PO_SSID": SSID_DEMO}, settings_obj=make_settings(), validator=_accept,
    )
    assert res["ok"] is True
    # applied echoes the mask, never the real value
    assert res["applied"]["PO_SSID"] == sio.MASK
    assert SSID_DEMO not in repr(res["applied"])
    # but the env override (for writing) holds the real value
    assert res["_env_overrides"]["PO_SSID"] == SSID_DEMO


def test_validate_propagates_validator_failure():
    res = sio.validate_update(
        {"STAKE_AMOUNT": -1}, settings_obj=make_settings(), validator=_reject("must be > 0"),
    )
    assert res["ok"] is False
    assert "must be > 0" in res["errors"]["_"]


def test_requires_restart_flagged():
    res = sio.validate_update(
        {"PO_SSID": SSID_DEMO, "STAKE_AMOUNT": 2.0},
        settings_obj=make_settings(), validator=_accept,
    )
    assert "PO_SSID" in res["requires_restart"]


# ── LIVE/SSID guard (fail-closed) ─────────────────────────────────────────────

def test_live_flip_requires_confirm():
    res = sio.validate_update(
        {"TRADE_MODE": "LIVE"},
        settings_obj=make_settings(ssid=SSID_LIVE), confirm_live=False, validator=_accept,
    )
    assert res["ok"] is False
    assert "TRADE_MODE" in res["errors"]
    assert "confirm" in res["errors"]["TRADE_MODE"].lower()


def test_live_flip_rejected_when_ssid_is_demo():
    res = sio.validate_update(
        {"TRADE_MODE": "LIVE"},
        settings_obj=make_settings(ssid=SSID_DEMO), confirm_live=True, validator=_accept,
    )
    assert res["ok"] is False
    assert "DEMO" in res["errors"]["TRADE_MODE"]


def test_live_flip_rejected_when_ssid_unknown():
    res = sio.validate_update(
        {"TRADE_MODE": "LIVE"},
        settings_obj=make_settings(ssid=SSID_NOFLAG), confirm_live=True, validator=_accept,
    )
    assert res["ok"] is False
    assert "TRADE_MODE" in res["errors"]


def test_live_flip_allowed_with_confirm_and_live_ssid():
    res = sio.validate_update(
        {"TRADE_MODE": "LIVE"},
        settings_obj=make_settings(ssid=SSID_LIVE), confirm_live=True, validator=_accept,
    )
    assert res["ok"] is True
    assert res["applied"]["TRADE_MODE"] == "LIVE"


def test_live_flip_uses_ssid_supplied_in_same_update():
    # current settings demo, but the update supplies a live SSID + LIVE + confirm.
    res = sio.validate_update(
        {"TRADE_MODE": "LIVE", "PO_SSID": SSID_LIVE},
        settings_obj=make_settings(ssid=SSID_DEMO), confirm_live=True, validator=_accept,
    )
    assert res["ok"] is True


def test_switching_to_demo_never_guarded():
    res = sio.validate_update(
        {"TRADE_MODE": "DEMO"},
        settings_obj=make_settings(ssid=SSID_LIVE), confirm_live=False, validator=_accept,
    )
    assert res["ok"] is True


# ── apply_update: writes .env, preserves keys ─────────────────────────────────

def test_apply_update_writes_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("EXISTING_KEY=keepme\nSTAKE_AMOUNT=1.50\n", encoding="utf-8")

    written = {}

    def fake_set_key(path, key, val, quote_mode="never"):
        # emulate python-dotenv set_key: update/append the key
        written[key] = val
        return True, key, val

    # inject a fake dotenv module so apply_update's lazy import resolves offline
    import sys
    import types
    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.set_key = fake_set_key
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    res = sio.apply_update(
        {"STAKE_AMOUNT": 2.5, "PO_SSID": SSID_DEMO},
        settings_obj=make_settings(), env_path=env, validator=_accept,
    )
    assert res["ok"] is True
    assert written["STAKE_AMOUNT"] == "2.5"
    assert written["PO_SSID"] == SSID_DEMO
    # response never leaks the secret
    assert res["applied"]["PO_SSID"] == sio.MASK
    # private key stripped from the public response
    assert "_env_overrides" not in res


def test_apply_update_does_not_write_on_failure(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("STAKE_AMOUNT=1.50\n", encoding="utf-8")
    import sys, types
    fake_dotenv = types.ModuleType("dotenv")
    called = {"n": 0}
    def fake_set_key(*a, **k):
        called["n"] += 1
    fake_dotenv.set_key = fake_set_key
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    res = sio.apply_update(
        {"TRADE_MODE": "LIVE"},  # rejected: no confirm
        settings_obj=make_settings(ssid=SSID_LIVE), env_path=env, validator=_accept,
    )
    assert res["ok"] is False
    assert called["n"] == 0  # nothing written
