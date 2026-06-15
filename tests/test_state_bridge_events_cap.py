"""Tier 4: events.jsonl size cap in StateBridge."""
from __future__ import annotations

import json

from dashboard import state_bridge as sb
from dashboard.state_bridge import StateBridge


def _count_lines(p):
    return sum(1 for _ in p.open())


def test_events_file_capped_when_over_limit(tmp_path, monkeypatch):
    # Tiny caps so the test is fast/deterministic.
    monkeypatch.setattr(sb, "_EVENTS_MAX_BYTES", 1000)
    monkeypatch.setattr(sb, "_EVENTS_KEEP_LINES", 20)
    monkeypatch.setattr(sb, "_EVENTS_CHECK_EVERY", 10)

    ev = tmp_path / "events.jsonl"
    bridge = StateBridge(state_path=tmp_path / "live.json", events_path=ev, enabled=True)

    for i in range(500):
        bridge.on_decision({"i": i, "pad": "x" * 50})

    assert ev.exists()
    # Truncation kicked in: file is bounded near KEEP_LINES, not 500 lines.
    assert _count_lines(ev) <= 20
    # Remaining lines are valid JSON and are the MOST RECENT ones.
    last = json.loads(ev.read_text().splitlines()[-1])
    assert last["data"]["i"] == 499


def test_events_not_capped_below_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "_EVENTS_MAX_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(sb, "_EVENTS_CHECK_EVERY", 1)
    ev = tmp_path / "events.jsonl"
    bridge = StateBridge(state_path=tmp_path / "live.json", events_path=ev, enabled=True)
    for i in range(30):
        bridge.trade_opened({"i": i})
    assert _count_lines(ev) == 30   # nothing dropped under the cap


def test_disabled_bridge_writes_nothing(tmp_path):
    ev = tmp_path / "events.jsonl"
    bridge = StateBridge(state_path=tmp_path / "live.json", events_path=ev, enabled=False)
    bridge.on_decision({"i": 1})
    assert not ev.exists()
