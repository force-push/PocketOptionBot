"""Analysis aggregations for the dashboard Analysis tab.

Pure functions over the decision records (same source as analytics.py). Mirrors
tools/analyze_since_5am.py but returns JSON-serialisable dicts for the UI rather
than printing. Breakdowns: headline cohorts, source/expiry/direction/pair,
per-signal win-when-agree, agreement-count, and sentiment coverage/correlation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from dashboard import analytics

# Fixed boundary: 5am ACST 2026-06-13 = when the WS hang fixes landed and the
# bot became stable. Trades before this are from the buggy/hanging era.
CUTOFF_5AM_ISO = "2026-06-12T19:30:00+00:00"
BREAKEVEN = 0.5217  # WR at 92% payout where EV = 0


def _resolved(rec: dict) -> bool:
    return (rec.get("outcome") or "").lower() in ("win", "loss")


def _won(rec: dict) -> bool:
    return (rec.get("outcome") or "").lower() == "win"


def _wr(rows: list[dict]) -> dict:
    res = [r for r in rows if _resolved(r)]
    if not res:
        return {"n": 0, "wr": None, "pnl": 0.0}
    wins = sum(1 for r in res if _won(r))
    pnl = sum((analytics._num(r.get("pnl")) or 0.0) for r in res)
    return {"n": len(res), "wr": round(wins / len(res), 4), "pnl": round(pnl, 2)}


def _row(label: str, rows: list[dict]) -> dict:
    d = _wr(rows)
    d["label"] = label
    d["edge"] = (d["wr"] is not None and d["wr"] > BREAKEVEN)
    return d


def _agree_count(rec: dict) -> int:
    bd = rec.get("our_signal_breakdown") or {}
    td = rec.get("our_direction")
    return sum(
        1 for v in bd.values()
        if isinstance(v, (list, tuple)) and v and v[0] == td and td is not None
    )


def analysis(records: Iterable[dict], *, since_iso: Optional[str] = CUTOFF_5AM_ISO) -> dict:
    """Build the full analysis payload. ``since_iso`` None means whole history."""
    rows = list(records)
    cutoff = datetime.fromisoformat(since_iso) if since_iso else None

    def in_window(r: dict) -> bool:
        if cutoff is None:
            return True
        t = analytics._parse_ts(r)
        return t is not None and t >= cutoff

    recent = [r for r in rows if in_window(r)]
    older = [r for r in rows if not in_window(r)]
    real = lambda rs: [r for r in rs if not r.get("shadow")]
    shadow = lambda rs: [r for r in rs if r.get("shadow")]

    R = real(recent)
    S = shadow(recent)

    # headline cohorts
    headline = [
        _row("All history (real)", real(rows)),
        _row("Before cutoff (real)", real(older)),
        _row("Since cutoff (real)", R),
        _row("Since cutoff (shadow)", S),
    ]

    # by source / shadow_kind
    by_kind: dict[str, list] = defaultdict(list)
    for r in recent:
        k = r.get("shadow_kind") or ("main" if not r.get("shadow") else "shadow_other")
        by_kind[k].append(r)
    by_source = sorted(
        (_row(k, v) for k, v in by_kind.items()),
        key=lambda d: -d["n"],
    )

    # by expiry (real)
    by_exp: dict[Any, list] = defaultdict(list)
    for r in R:
        by_exp[r.get("expiry_seconds")].append(r)
    by_expiry = [_row(f"{e}s", by_exp[e]) for e in sorted(by_exp, key=lambda x: (x is None, x))]

    # shadow expiry experiment
    by_exp_s: dict[Any, list] = defaultdict(list)
    for r in S:
        if r.get("shadow_kind") == "expiry":
            by_exp_s[r.get("expiry_seconds")].append(r)
    shadow_expiry = [_row(f"{e}s", by_exp_s[e]) for e in sorted(by_exp_s, key=lambda x: (x is None, x))]

    # by direction (real)
    by_dir: dict[Any, list] = defaultdict(list)
    for r in R:
        by_dir[r.get("our_direction")].append(r)
    by_direction = [_row(str(d), by_dir[d]) for d in sorted(by_dir, key=lambda x: str(x))]

    # by pair (real, n>=5)
    by_pair_map: dict[Any, list] = defaultdict(list)
    for r in R:
        by_pair_map[r.get("pair_api")].append(r)
    by_pair = sorted(
        (_row(p or "?", v) for p, v in by_pair_map.items() if _wr(v)["n"] >= 5),
        key=lambda d: (-(d["wr"] or 0), -d["n"]),
    )

    # per-signal win-when-agree (real+shadow resolved)
    res_all = [r for r in recent if _resolved(r)]
    sig: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in res_all:
        bd = r.get("our_signal_breakdown") or {}
        td = r.get("our_direction")
        w = _won(r)
        for name, v in bd.items():
            if isinstance(v, (list, tuple)) and v and v[0] == td and td is not None:
                sig[name][1] += 1
                if w:
                    sig[name][0] += 1
    by_signal = sorted(
        (
            {"label": n, "n": tot, "wr": round(wn / tot, 4), "pnl": None,
             "edge": (wn / tot) > BREAKEVEN}
            for n, (wn, tot) in sig.items() if tot >= 10
        ),
        key=lambda d: -(d["wr"] or 0),
    )

    # agreement count vs WR (real)
    by_agree_map: dict[int, list] = defaultdict(list)
    for r in R:
        by_agree_map[_agree_count(r)].append(r)
    by_agreement = [_row(f"{c} agreed", by_agree_map[c]) for c in sorted(by_agree_map)]

    # sentiment coverage + correlation
    have_sent = [r for r in res_all if r.get("sentiment") is not None]
    sent_buckets = []
    aligned: list[dict] = []
    contra: list[dict] = []
    for r in have_sent:
        s = r["sentiment"]
        d = r.get("our_direction")
        if d == "CALL":
            (aligned if s >= 50 else contra).append(r)
        elif d == "PUT":
            (aligned if s < 50 else contra).append(r)
    for lo, hi in [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]:
        b = [r for r in have_sent if lo <= (r.get("sentiment") or -1) < hi]
        if b:
            sent_buckets.append(_row(f"{lo}-{hi}", b))
    sentiment = {
        "resolved": len(res_all),
        "with_sentiment": len(have_sent),
        "coverage_pct": round(100 * len(have_sent) / max(1, len(res_all)), 1),
        "buckets": sent_buckets,
        "aligned": _row("Traded WITH crowd", aligned) if have_sent else None,
        "contra": _row("Traded AGAINST crowd", contra) if have_sent else None,
    }

    return {
        "cutoff_iso": since_iso,
        "breakeven": BREAKEVEN,
        "headline": headline,
        "by_source": by_source,
        "by_expiry": by_expiry,
        "shadow_expiry": shadow_expiry,
        "by_direction": by_direction,
        "by_pair": by_pair,
        "by_signal": by_signal,
        "by_agreement": by_agreement,
        "sentiment": sentiment,
    }
