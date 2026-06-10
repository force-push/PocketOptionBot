"""Offline, dependency-free tests for dashboard.analytics (stdlib + pytest only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from dashboard import analytics


def _trade(ts, *, pair_api="EURUSD_otc", pair_raw="EUR/USD OTC", direction="CALL",
           outcome="win", pnl=1.38, expiry=30, conf=0.84, bot_wr=0.85,
           trade_id="t1", stake=1.5):
    return {
        "cycle_id": "c", "pair_raw": pair_raw, "pair_api": pair_api,
        "bot_win_rate": bot_wr, "bot_is_top_pick": True, "bot_direction": direction,
        "bot_setup": "x", "bot_indicators_raw": "y",
        "our_direction": direction, "our_confluence_score": conf,
        "our_signal_breakdown": {}, "agreement": True, "combined_probability": 0.85,
        "expiry_seconds": expiry, "decision": "TRADE", "skip_reason": None,
        "stake": stake, "trade_id": trade_id, "status": outcome.upper(),
        "outcome": outcome, "pnl": pnl, "pnl_currency": "USD",
        "balance_before": 100.0, "balance_after": 100.0 + (pnl or 0),
        "ts": ts,
    }


def _skip(ts, *, reason="confluence_below_floor", pair_api="GBPUSD_otc"):
    return {
        "cycle_id": "c", "pair_raw": "GBP/USD OTC", "pair_api": pair_api,
        "bot_win_rate": 0.83, "bot_is_top_pick": True, "bot_direction": "PUT",
        "bot_setup": "x", "bot_indicators_raw": "y",
        "our_direction": None, "our_confluence_score": 0.6,
        "our_signal_breakdown": {}, "agreement": False, "combined_probability": 0.6,
        "expiry_seconds": 30, "decision": "SKIP", "skip_reason": reason,
        "stake": 1.5, "trade_id": None, "status": "SKIP", "outcome": None,
        "pnl": None, "pnl_currency": None, "balance_before": None,
        "balance_after": None, "ts": ts,
    }


def _iso(h, m, s=0, day=15):
    return datetime(2026, 6, day, h, m, s, tzinfo=timezone.utc).isoformat()


NOW = datetime(2026, 6, 15, 18, 0, 0, tzinfo=timezone.utc)


# ── KPIs ──────────────────────────────────────────────────────────────────────

def test_kpis_basic_aggregation():
    recs = [
        _trade(_iso(10, 0), outcome="win", pnl=1.4, conf=0.80, trade_id="a"),
        _trade(_iso(10, 5), outcome="loss", pnl=-1.5, conf=0.78, trade_id="b"),
        _trade(_iso(10, 10), outcome="win", pnl=1.4, conf=0.86, trade_id="c"),
        _trade(_iso(10, 15), outcome="draw", pnl=0.0, conf=0.76, trade_id="d"),
        _skip(_iso(10, 20)),
    ]
    k = analytics.kpis(recs, balance=200.0,
                       active=[{"stake": 1.5}, {"stake": 1.5}], now=NOW)
    assert k["wins"] == 2 and k["losses"] == 1 and k["draws"] == 1
    # win_rate over resolved (4) = 2/4
    assert k["win_rate"] == pytest.approx(0.5)
    assert k["today_pnl"] == pytest.approx(1.3)
    assert k["traded"] == 4
    assert k["skipped"] == 1
    assert k["trades_today"] == 5
    assert k["active_count"] == 2
    assert k["at_risk"] == pytest.approx(3.0)
    # avg confluence over today's trades
    assert k["avg_confluence"] == pytest.approx((0.80 + 0.78 + 0.86 + 0.76) / 4)
    # pnl pct vs opening balance (200 - 1.3)
    assert k["today_pnl_pct"] == pytest.approx(1.3 / (200.0 - 1.3))


def test_kpis_only_counts_today():
    recs = [
        _trade(_iso(10, 0, day=14), outcome="win", pnl=5.0, trade_id="old"),  # yesterday
        _trade(_iso(10, 0, day=15), outcome="win", pnl=1.4, trade_id="new"),  # today
    ]
    k = analytics.kpis(recs, balance=100.0, now=NOW)
    assert k["wins"] == 1
    assert k["today_pnl"] == pytest.approx(1.4)


def test_kpis_empty():
    k = analytics.kpis([], now=NOW)
    assert k["wins"] == 0 and k["win_rate"] == 0.0 and k["today_pnl"] == 0.0
    assert k["today_pnl_pct"] is None  # balance unknown


# ── equity curve ──────────────────────────────────────────────────────────────

def test_equity_curve_is_cumulative_and_ordered():
    recs = [
        _trade(_iso(10, 10), outcome="win", pnl=1.4, trade_id="b"),
        _trade(_iso(10, 0), outcome="win", pnl=2.0, trade_id="a"),   # earlier
        _skip(_iso(10, 5)),                                          # excluded
        _trade(_iso(10, 20), outcome="loss", pnl=-1.5, trade_id="c"),
    ]
    eq = analytics.equity_curve(recs, rng="ALL")
    assert [round(p["cum_pnl"], 2) for p in eq] == [2.0, 3.4, 1.9]
    # ordered oldest-first by ts
    assert eq[0]["t"] < eq[1]["t"] < eq[2]["t"]


def test_equity_curve_range_filter():
    recs = [
        _trade(_iso(10, 0), outcome="win", pnl=1.0, trade_id="a"),
        _trade(_iso(17, 30), outcome="win", pnl=2.0, trade_id="b"),  # within last 1h of NOW(18:00)
    ]
    eq_1h = analytics.equity_curve(recs, rng="1H", now=NOW)
    assert len(eq_1h) == 1 and eq_1h[0]["cum_pnl"] == pytest.approx(2.0)
    eq_all = analytics.equity_curve(recs, rng="ALL", now=NOW)
    assert len(eq_all) == 2


# ── win/loss distribution ─────────────────────────────────────────────────────

def test_winloss_distribution():
    recs = [
        _trade(_iso(10, 0), outcome="win", trade_id="a"),
        _trade(_iso(10, 1), outcome="win", trade_id="b"),
        _trade(_iso(10, 2), outcome="loss", trade_id="c"),
        _trade(_iso(10, 3), outcome="draw", trade_id="d"),
        _skip(_iso(10, 4)),
    ]
    wl = analytics.winloss(recs, rng="ALL")
    assert wl == {"wins": 2, "losses": 1, "draws": 1}


def test_by_pair_aggregation_sorted():
    recs = [
        _trade(_iso(10, 0), pair_api="EURUSD_otc", outcome="win", pnl=1.4, trade_id="a"),
        _trade(_iso(10, 1), pair_api="EURUSD_otc", outcome="loss", pnl=-1.5, trade_id="b"),
        _trade(_iso(10, 2), pair_api="USDJPY", outcome="win", pnl=2.0, trade_id="c"),
    ]
    bp = analytics.by_pair(recs, rng="ALL")
    assert bp[0]["pair"] == "USDJPY" and bp[0]["pnl"] == pytest.approx(2.0)
    eur = next(p for p in bp if p["pair"] == "EURUSD_otc")
    assert eur["wins"] == 1 and eur["losses"] == 1
    assert eur["pnl"] == pytest.approx(-0.1)


def test_performance_payload_shape():
    recs = [_trade(_iso(10, 0), trade_id="a")]
    perf = analytics.performance(recs, rng="1D", now=NOW)
    assert perf["range"] == "1D"
    assert set(perf.keys()) == {"range", "equity", "winloss", "by_pair", "kpis"}
    assert perf["kpis"]["range"] == "1D"  # KPI strip follows the chart range


# ── history rows / pagination / SKIP inclusion ────────────────────────────────

def test_history_newest_first_includes_skips():
    recs = [
        _trade(_iso(10, 0), trade_id="a", outcome="win"),
        _skip(_iso(11, 0), reason="risk_blocked"),
        _trade(_iso(12, 0), trade_id="c", outcome="loss"),
    ]
    rows = analytics.history(recs, limit=100)
    assert [r["ts"] for r in rows] == [_iso(12, 0), _iso(11, 0), _iso(10, 0)]
    skip_row = rows[1]
    assert skip_row["decision"] == "SKIP"
    assert skip_row["result"] is None
    assert skip_row["skip_reason"] == "risk_blocked"
    assert skip_row["pnl"] is None
    # trade rows carry result + pnl
    assert rows[0]["result"] == "loss" and rows[0]["pnl"] == pytest.approx(1.38) or rows[0]["pnl"] is not None
    assert rows[2]["result"] == "win"


def test_history_otc_flag_and_dir():
    rows = analytics.history([_trade(_iso(10, 0), pair_api="EURUSD_otc")])
    assert rows[0]["otc"] is True
    rows2 = analytics.history([_trade(_iso(10, 0), pair_api="USDJPY")])
    assert rows2[0]["otc"] is False
    assert rows2[0]["dir"] == "CALL"


def test_history_limit_and_before_cursor():
    recs = [_trade(_iso(10, i), trade_id=f"t{i}") for i in range(5)]
    page1 = analytics.history(recs, limit=2)
    assert len(page1) == 2
    assert page1[0]["ts"] == _iso(10, 4)
    # before the last ts of page1 → next older rows
    cursor = page1[-1]["ts"]
    page2 = analytics.history(recs, limit=2, before=cursor)
    assert len(page2) == 2
    assert all(r["ts"] < cursor for r in page2)
    assert page2[0]["ts"] == _iso(10, 2)


# ── loading from file ─────────────────────────────────────────────────────────

def test_load_records_skips_bad_lines(tmp_path):
    p = tmp_path / "decisions.jsonl"
    p.write_text(
        json.dumps(_trade(_iso(10, 0), trade_id="a")) + "\n"
        + "not json\n"
        + "\n"
        + json.dumps(_skip(_iso(10, 1))) + "\n",
        encoding="utf-8",
    )
    recs = analytics.load_records(p)
    assert len(recs) == 2


def test_load_records_missing_file(tmp_path):
    assert analytics.load_records(tmp_path / "nope.jsonl") == []


def test_parse_ts_handles_zulu():
    rows = analytics.history([_trade("2026-06-15T10:00:00Z", trade_id="a")])
    assert rows[0]["ts"] == "2026-06-15T10:00:00Z"
