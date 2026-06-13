"""Offline tests for the SQLite decision store."""
from __future__ import annotations

import json

import pytest

from data import decisions_store as store


def _row(**over):
    base = {
        "cycle_id": "C1", "pair_raw": "EURUSD_otc", "pair_api": "EURUSD_otc",
        "bot_win_rate": 0.5, "bot_is_top_pick": False, "bot_direction": "CALL",
        "bot_setup": "signals", "bot_indicators_raw": "",
        "our_direction": "CALL", "our_confluence_score": 0.42,
        "our_signal_breakdown": {"RSI": ["CALL", 0.6, "oversold"]},
        "agreement": True, "combined_probability": 0.55, "expiry_seconds": 30,
        "decision": "TRADE", "skip_reason": None, "stake": 1.0,
        "shadow": False, "shadow_kind": None, "trade_id": "T1",
        "status": "PENDING", "outcome": None, "pnl": None,
        "ts": "2026-06-13T10:00:00+00:00",
    }
    base.update(over)
    return base


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "decisions.db"
    store.init_db(p)
    store.reset_cache(p)
    yield p
    store.reset_cache(p)


def test_insert_and_full_row_roundtrip(db):
    store.insert_decision(db, _row(), clock=1.0)
    recs = store.all_records(db)
    assert len(recs) == 1
    assert recs[0]["pair_api"] == "EURUSD_otc"
    # full row preserved verbatim, incl nested breakdown
    assert recs[0]["our_signal_breakdown"]["RSI"][0] == "CALL"


def test_update_outcome_no_rewrite_semantics(db):
    store.insert_decision(db, _row(trade_id="T1", outcome=None, pnl=None), clock=1.0)
    found = store.update_outcome(db, "T1", "win", 0.92, balance_before=100.0,
                                 balance_after=100.92, pnl_currency="USD", clock=2.0)
    assert found is True
    rec = store.find_by_trade_id(db, "T1")
    assert rec["outcome"] == "win"
    assert rec["pnl"] == 0.92
    assert rec["status"] == "WIN"
    assert rec["balance_after"] == 100.92


def test_update_outcome_missing_trade_returns_false(db):
    assert store.update_outcome(db, "nope", "win", 1.0) is False


def test_recent_decisions_newest_first_and_limit(db):
    for i in range(5):
        store.insert_decision(db, _row(trade_id=f"T{i}", ts=f"2026-06-13T10:0{i}:00+00:00"), clock=float(i))
    rows = store.recent_decisions(db, limit=3)
    assert [r["ts"] for r in rows] == [
        "2026-06-13T10:04:00+00:00",
        "2026-06-13T10:03:00+00:00",
        "2026-06-13T10:02:00+00:00",
    ]


def test_recent_decisions_before_cursor(db):
    for i in range(5):
        store.insert_decision(db, _row(trade_id=f"T{i}", ts=f"2026-06-13T10:0{i}:00+00:00"), clock=float(i))
    rows = store.recent_decisions(db, limit=10, before="2026-06-13T10:02:00+00:00")
    assert all(r["ts"] < "2026-06-13T10:02:00+00:00" for r in rows)
    assert len(rows) == 2


def test_records_since(db):
    store.insert_decision(db, _row(trade_id="old", ts="2026-06-13T08:00:00+00:00"), clock=1.0)
    store.insert_decision(db, _row(trade_id="new", ts="2026-06-13T12:00:00+00:00"), clock=2.0)
    recs = store.records_since(db, "2026-06-13T10:00:00+00:00")
    assert [r["trade_id"] for r in recs] == ["new"]


def test_incremental_cache_picks_up_inserts(db):
    store.insert_decision(db, _row(trade_id="T0"), clock=1.0)
    assert len(store.all_records(db, clock=2.0)) == 1
    store.insert_decision(db, _row(trade_id="T1"), clock=3.0)
    # second call must reflect the new row (incremental top-up via rowid)
    recs = store.all_records(db, clock=4.0)
    assert {r["trade_id"] for r in recs} == {"T0", "T1"}


def test_incremental_cache_picks_up_outcome_update(db):
    store.insert_decision(db, _row(trade_id="T0", outcome=None), clock=1.0)
    assert store.all_records(db, clock=2.0)[0]["outcome"] is None
    store.update_outcome(db, "T0", "loss", -1.0, clock=3.0)
    # the in-place update must be reflected by the cache via the updated_at delta
    recs = store.all_records(db, clock=4.0)
    assert recs[0]["outcome"] == "loss"
    assert recs[0]["pnl"] == -1.0


def test_find_by_cycle_id(db):
    store.insert_decision(db, _row(cycle_id="CYC", trade_id=None, decision="SKIP"), clock=1.0)
    rec = store.find_by_cycle_id(db, "CYC")
    assert rec is not None and rec["decision"] == "SKIP"


def test_migrate_jsonl(tmp_path):
    jsonl = tmp_path / "decisions.jsonl"
    db = tmp_path / "decisions.db"
    rows = [_row(trade_id="A"), _row(trade_id="B", decision="SKIP", skip_reason="no_direction")]
    jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    n = store.migrate_jsonl(jsonl, db)
    assert n == 2
    store.reset_cache(db)
    recs = store.all_records(db)
    assert {r["trade_id"] for r in recs} == {"A", "B"}


def test_missing_db_reads_empty(tmp_path):
    missing = tmp_path / "nope.db"
    assert store.all_records(missing) == []
    assert store.recent_decisions(missing) == []
    assert store.find_by_trade_id(missing, "x") is None
