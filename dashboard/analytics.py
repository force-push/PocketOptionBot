"""Dependency-free analytics over ``decisions.jsonl`` (stdlib only).

These are *pure* functions: they take either a list of decision dicts (the JSON
form of ``strategy.trade_logger.DecisionRow``) or a path to the JSONL file, and
return the history rows, equity curve, win/loss distribution and the KPI
snapshot the dashboard UI expects (docs/dashboard-plan.md §4.2).

No fastapi / pandas / pydantic — importable and testable fully offline.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

# ── outcome normalisation ────────────────────────────────────────────────────
# Records carry both ``outcome`` ("win"/"loss"/"draw") and a legacy ``status``
# ("WIN"/"LOSS"/"DRAW"/"PENDING"). We treat ``outcome`` as authoritative and
# fall back to ``status``.
_WIN = "win"
_LOSS = "loss"
_DRAW = "draw"
_RESULTS = (_WIN, _LOSS, _DRAW)


def _normalize_result(rec: dict) -> Optional[str]:
    """Return 'win'|'loss'|'draw' or None (pending / skip / unknown)."""
    val = rec.get("outcome")
    if val is None:
        status = rec.get("status")
        if isinstance(status, str):
            val = status
    if not isinstance(val, str):
        return None
    v = val.strip().lower()
    return v if v in _RESULTS else None


def _is_trade(rec: dict) -> bool:
    return str(rec.get("decision", "")).strip().upper() == "TRADE"


def _parse_ts(rec: dict) -> Optional[datetime]:
    """Parse the ISO ``ts`` field into an aware UTC datetime (or None)."""
    ts = rec.get("ts")
    if not isinstance(ts, str) or not ts:
        return None
    raw = ts.strip()
    # Accept trailing 'Z' (Zulu) which fromisoformat rejects on older pythons.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _num(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ── loading ──────────────────────────────────────────────────────────────────

def load_records(path: str | Path) -> list[dict]:
    """Read a JSONL file into a list of dicts. Missing file → []. Bad lines skipped."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


# ── history rows (§4.2 GET /api/history) ─────────────────────────────────────

def history_row(rec: dict) -> dict:
    """Project a raw decision record into the UI history-row shape.

    Includes SKIPs (decision == 'SKIP', skip_reason populated, result null).
    """
    pair_raw = rec.get("pair_raw")
    pair_api = rec.get("pair_api") or ""
    otc = bool(isinstance(pair_api, str) and pair_api.lower().endswith("_otc"))
    decision = str(rec.get("decision", "")).strip().upper() or None
    result = _normalize_result(rec) if _is_trade(rec) else None
    return {
        "cycle_id": rec.get("cycle_id"),
        "ts": rec.get("ts"),
        "pair_raw": pair_raw,
        "pair_api": pair_api or None,
        "otc": otc,
        "dir": rec.get("our_direction") or rec.get("bot_direction"),
        "decision": decision,
        "result": result,
        "pnl": _num(rec.get("pnl")) if _is_trade(rec) else None,
        "stake": _num(rec.get("stake")),
        "expiry_seconds": rec.get("expiry_seconds"),
        "our_confluence": _num(rec.get("our_confluence_score")),
        "bot_win_rate": _num(rec.get("bot_win_rate")),
        "entry": rec.get("entry"),
        "skip_reason": rec.get("skip_reason"),
        "trade_id": rec.get("trade_id"),
    }


def full_detail_row(rec: dict) -> dict:
    """Return the complete decision record enriched with derived display fields."""
    base = history_row(rec)
    base.update({
        "bot_direction": rec.get("bot_direction"),
        "bot_setup": rec.get("bot_setup"),
        "bot_indicators_raw": rec.get("bot_indicators_raw"),
        "bot_is_top_pick": rec.get("bot_is_top_pick"),
        "our_direction": rec.get("our_direction"),
        "our_confluence_score": _num(rec.get("our_confluence_score")),
        "our_signal_breakdown": rec.get("our_signal_breakdown") or {},
        "agreement": rec.get("agreement"),
        "combined_probability": _num(rec.get("combined_probability")),
        "calibrated_probability": _num(rec.get("calibrated_probability")),
        "balance_before": _num(rec.get("balance_before")),
        "balance_after": _num(rec.get("balance_after")),
        "pnl_currency": rec.get("pnl_currency") or "USD",
        "status": rec.get("status"),
        "outcome": rec.get("outcome"),
    })
    return base


def find_by_cycle_id(records: Iterable[dict], cycle_id: str) -> Optional[dict]:
    """Return the first record matching cycle_id, or None."""
    for rec in records:
        if rec.get("cycle_id") == cycle_id:
            return rec
    return None


def history(
    records: Iterable[dict],
    *,
    limit: int = 100,
    before: Optional[str] = None,
) -> list[dict]:
    """Newest-first history rows (TRADES + SKIPs), paginated.

    ``before`` is an ISO timestamp; only rows strictly older than it are returned
    (cursor pagination). ``limit`` caps the result count.
    """
    rows = [history_row(r) for r in records]
    # newest first by ts (rows without ts sort last/oldest)
    rows.sort(key=lambda r: r["ts"] or "", reverse=True)
    if before:
        before = before.strip()
        rows = [r for r in rows if (r["ts"] or "") < before]
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows


# ── equity curve (§4.2 GET /api/performance) ─────────────────────────────────

_RANGE_DELTAS = {
    "1H": timedelta(hours=1),
    "1D": timedelta(days=1),
    "1W": timedelta(weeks=1),
}


def _resolved_trades(records: Iterable[dict]) -> list[tuple[datetime | None, dict, str]]:
    """Trades with a win/loss/draw result, oldest-first by ts."""
    out = []
    for r in records:
        if not _is_trade(r):
            continue
        res = _normalize_result(r)
        if res is None:
            continue
        out.append((_parse_ts(r), r, res))
    out.sort(key=lambda t: (t[0] or datetime.min.replace(tzinfo=timezone.utc)))
    return out


def _filter_range(
    trades: list[tuple[datetime | None, dict, str]],
    rng: str,
    now: Optional[datetime] = None,
) -> list[tuple[datetime | None, dict, str]]:
    rng = (rng or "ALL").upper()
    delta = _RANGE_DELTAS.get(rng)
    if delta is None:
        return trades
    now = now or datetime.now(timezone.utc)
    cutoff = now - delta
    return [t for t in trades if t[0] is not None and t[0] >= cutoff]


def equity_curve(records: Iterable[dict], *, rng: str = "ALL",
                 now: Optional[datetime] = None) -> list[dict]:
    """Cumulative-P&L points over resolved trades within ``rng``.

    Returns ``[{"t": iso_ts, "cum_pnl": float}, ...]`` oldest-first.
    """
    trades = _filter_range(_resolved_trades(records), rng, now=now)
    pts: list[dict] = []
    cum = 0.0
    for dt, rec, _res in trades:
        cum += _num(rec.get("pnl")) or 0.0
        pts.append({
            "t": rec.get("ts"),
            "cum_pnl": round(cum, 6),
        })
    return pts


def winloss(records: Iterable[dict], *, rng: str = "ALL",
            now: Optional[datetime] = None) -> dict:
    """Win/loss/draw counts over resolved trades within ``rng``."""
    trades = _filter_range(_resolved_trades(records), rng, now=now)
    wins = sum(1 for _, _, r in trades if r == _WIN)
    losses = sum(1 for _, _, r in trades if r == _LOSS)
    draws = sum(1 for _, _, r in trades if r == _DRAW)
    return {"wins": wins, "losses": losses, "draws": draws}


def by_pair(records: Iterable[dict], *, rng: str = "ALL",
            now: Optional[datetime] = None) -> list[dict]:
    """Per-pair P&L + win/loss, sorted by descending P&L."""
    trades = _filter_range(_resolved_trades(records), rng, now=now)
    agg: dict[str, dict] = {}
    for _dt, rec, res in trades:
        pair = rec.get("pair_api") or rec.get("pair_raw") or "?"
        a = agg.setdefault(pair, {"pair": pair, "pnl": 0.0, "wins": 0, "losses": 0})
        a["pnl"] += _num(rec.get("pnl")) or 0.0
        if res == _WIN:
            a["wins"] += 1
        elif res == _LOSS:
            a["losses"] += 1
    rows = list(agg.values())
    for r in rows:
        r["pnl"] = round(r["pnl"], 6)
    rows.sort(key=lambda r: r["pnl"], reverse=True)
    return rows


def performance(records: Iterable[dict], *, rng: str = "ALL",
                now: Optional[datetime] = None) -> dict:
    """Full performance payload (§4.2 GET /api/performance)."""
    recs = list(records)
    rng = (rng or "ALL").upper()
    return {
        "range": rng,
        "equity": equity_curve(recs, rng=rng, now=now),
        "winloss": winloss(recs, rng=rng, now=now),
        "by_pair": by_pair(recs, rng=rng, now=now),
    }


# ── KPI snapshot (§4.2 GET /api/state.kpis) ──────────────────────────────────

def _same_utc_day(dt: Optional[datetime], ref: datetime) -> bool:
    return dt is not None and dt.date() == ref.date()


def kpis(
    records: Iterable[dict],
    *,
    balance: Optional[float] = None,
    active: Optional[Iterable[dict]] = None,
    now: Optional[datetime] = None,
) -> dict:
    """KPI snapshot for the monitoring strip.

    ``today`` is the current UTC calendar day. ``balance`` and ``active`` come
    from live_state.json; when absent, derived fields degrade gracefully.
    """
    recs = list(records)
    now = now or datetime.now(timezone.utc)
    active_list = list(active or [])

    today_records = [r for r in recs if _same_utc_day(_parse_ts(r), now)]
    today_trades = [r for r in today_records if _is_trade(r)]
    today_skips = [r for r in today_records if not _is_trade(r)]

    wins = losses = draws = 0
    today_pnl = 0.0
    for r in today_trades:
        res = _normalize_result(r)
        if res == _WIN:
            wins += 1
        elif res == _LOSS:
            losses += 1
        elif res == _DRAW:
            draws += 1
        today_pnl += _num(r.get("pnl")) or 0.0

    resolved = wins + losses + draws
    win_rate = (wins / resolved) if resolved else 0.0

    # today P&L % is measured against the day's opening balance, approximated as
    # (current balance − today P&L). Falls back to None when balance unknown.
    today_pnl_pct: Optional[float] = None
    if balance is not None:
        opening = balance - today_pnl
        if opening > 0:
            today_pnl_pct = today_pnl / opening

    # avg confluence over today's *trades* (the entries we actually took).
    confs = [c for c in (_num(r.get("our_confluence_score")) for r in today_trades) if c is not None]
    avg_confluence = (sum(confs) / len(confs)) if confs else 0.0

    at_risk = round(sum(_num(a.get("stake")) or 0.0 for a in active_list), 6)

    # Weekly profit projection: calculate P&L rate per minute from ALL historical trades
    weekly_projection = 0.0
    all_trades = [r for r in recs if _is_trade(r)]
    if all_trades:
        # Sum all resolved trade P&L
        total_pnl = 0.0
        for r in all_trades:
            if _normalize_result(r) is not None:  # only resolved trades
                total_pnl += _num(r.get("pnl")) or 0.0

        # Find earliest and latest trade timestamp across all history
        timestamps = [_parse_ts(r) for r in all_trades]
        timestamps = [t for t in timestamps if t is not None]
        if len(timestamps) >= 2 and total_pnl != 0.0:
            earliest = min(timestamps)
            latest = max(timestamps)
            elapsed_minutes = max((latest - earliest).total_seconds() / 60, 1)  # avoid div by zero
            pnl_per_minute = total_pnl / elapsed_minutes
            minutes_per_week = 7 * 24 * 60
            weekly_projection = pnl_per_minute * minutes_per_week

    return {
        "today_pnl": round(today_pnl, 6),
        "today_pnl_pct": (round(today_pnl_pct, 8) if today_pnl_pct is not None else None),
        "win_rate": round(win_rate, 6),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "active_count": len(active_list),
        "at_risk": at_risk,
        "trades_today": len(today_records),
        "traded": len(today_trades),
        "skipped": len(today_skips),
        "avg_confluence": round(avg_confluence, 6),
        "weekly_projection": round(weekly_projection, 2),
    }


__all__ = [
    "load_records",
    "history_row",
    "full_detail_row",
    "find_by_cycle_id",
    "history",
    "equity_curve",
    "winloss",
    "by_pair",
    "performance",
    "kpis",
]
