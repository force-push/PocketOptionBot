"""FastAPI TestClient tests for the dashboard API.

Skipped cleanly where fastapi isn't installed (this sandbox). Run after
``pip install fastapi uvicorn[standard] watchfiles``.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from config.settings import settings  # noqa: E402


SSID_DEMO = '42["auth",{"session":"abc","isDemo":1,"uid":42,"platform":1}]'
SSID_LIVE = '42["auth",{"session":"abc","isDemo":0,"uid":42,"platform":1}]'


def _seed(tmp_path):
    """Point settings at a temp data dir and seed decisions + live_state."""
    decisions = tmp_path / "decisions.jsonl"
    state = tmp_path / "live_state.json"
    from tools.dashboard_demo import generate
    rows, live = generate(40, seed=7)
    with decisions.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    state.write_text(json.dumps(live), encoding="utf-8")
    return decisions, state


@pytest.fixture()
def client(tmp_path, monkeypatch):
    decisions, state = _seed(tmp_path)
    monkeypatch.setattr(settings, "decisions_log_path", str(decisions), raising=False)
    monkeypatch.setattr(settings, "live_state_path", str(state), raising=False)
    monkeypatch.setattr(settings, "events_log_path", str(tmp_path / "events.jsonl"), raising=False)
    monkeypatch.setattr(settings, "dashboard_token", None, raising=False)
    # import after monkeypatching so build picks up paths at request time
    from dashboard.server import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_get_state(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert "kpis" in body and "active" in body
    assert body["mode"] in ("DEMO", "LIVE")


def test_get_history(client):
    r = client.get("/api/history?limit=10")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) <= 10
    # newest first
    ts = [row["ts"] for row in rows if row["ts"]]
    assert ts == sorted(ts, reverse=True)


def test_get_performance(client):
    r = client.get("/api/performance?range=ALL")
    assert r.status_code == 200
    body = r.json()
    assert body["range"] == "ALL"
    assert "equity" in body and "winloss" in body


def test_get_settings_masks_secrets(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    blob = json.dumps(body)
    assert "isDemo" not in blob  # SSID not leaked


def test_post_settings_ok(client):
    r = client.post("/api/settings", json={"fields": {"STAKE_AMOUNT": 2.0}})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_post_settings_live_guard_rejects(client):
    r = client.post("/api/settings", json={"fields": {"TRADE_MODE": "LIVE"}})
    assert r.status_code == 400
    assert "TRADE_MODE" in r.json()["errors"]


def test_post_settings_token_required(tmp_path, monkeypatch):
    decisions, state = _seed(tmp_path)
    monkeypatch.setattr(settings, "decisions_log_path", str(decisions), raising=False)
    monkeypatch.setattr(settings, "live_state_path", str(state), raising=False)
    monkeypatch.setattr(settings, "events_log_path", str(tmp_path / "events.jsonl"), raising=False)
    monkeypatch.setattr(settings, "dashboard_token", "s3cret", raising=False)
    from dashboard.server import create_app
    app = create_app()
    with TestClient(app) as c:
        # missing token → 401
        r = c.post("/api/settings", json={"fields": {"STAKE_AMOUNT": 2.0}})
        assert r.status_code == 401
        # correct token → ok
        r2 = c.post("/api/settings", json={"fields": {"STAKE_AMOUNT": 2.0}},
                    headers={"X-Dashboard-Token": "s3cret"})
        assert r2.status_code == 200


def test_ws_hello_and_state(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        state = ws.receive_json()
        assert state["type"] == "state"
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong["type"] == "pong"
