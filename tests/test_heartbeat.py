"""Test the main-loop liveness heartbeat (Tier 3 watchdog support)."""
from __future__ import annotations

import time
from pathlib import Path

import main_v2


def test_touch_heartbeat_writes_recent_timestamp(tmp_path, monkeypatch):
    hb = tmp_path / "sub" / "heartbeat"          # parent dir doesn't exist yet
    monkeypatch.setattr(main_v2, "_HEARTBEAT_PATH", hb)
    before = time.time()
    main_v2._touch_heartbeat()
    assert hb.exists()
    written = float(hb.read_text())
    assert written >= before - 1      # a fresh, plausible epoch timestamp


def test_touch_heartbeat_never_raises(monkeypatch):
    # Point at an unwritable path → must swallow the error, never disrupt trading.
    monkeypatch.setattr(main_v2, "_HEARTBEAT_PATH", Path("/proc/nonexistent/heartbeat"))
    main_v2._touch_heartbeat()   # should not raise


def test_touch_heartbeat_advances(tmp_path, monkeypatch):
    hb = tmp_path / "heartbeat"
    monkeypatch.setattr(main_v2, "_HEARTBEAT_PATH", hb)
    main_v2._touch_heartbeat()
    first = float(hb.read_text())
    time.sleep(0.01)
    main_v2._touch_heartbeat()
    assert float(hb.read_text()) >= first
