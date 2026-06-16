#!/usr/bin/env python3
"""Failure analysis + tuning advisor for the flip strategy.

Reads data/decisions.db and reports, for a recent window:
  1. Headline WR / P&L (overall + by entry kind), vs the break-even at 92% payout.
  2. Post-loss autocorrelation — WR by seconds since the last loss on the same
     pair. Tells you whether the per-pair post-loss cooldown is set right (the
     <cooldown window should be near-empty if it's enforced; if trades still land
     there at low WR, raise POST_LOSS_PAIR_COOLDOWN_SECONDS).
  3. Pair leaderboard (best/worst by P&L) — candidates for the regex/blocklist.
  4. Dimension scan (bb_width, ADX, dist, direction) — flags any band below
     break-even with a meaningful sample, i.e. a lever worth tuning.
  5. WR trend (30m/2h/6h/24h) — regression radar; catches WR sliding before it
     shows up in a single window.
  6. OPTIMIZER recommendations — reads the live gate thresholds (flip_levers.json)
     and finds BOTH leak types: bands we TRADE that lose (→ tighten) and bands we
     EXCLUDE that win (→ loosen, the opportunity-cost leak). Guardrailed against
     noise: only fires when a band has ≥ MIN_ACT_N trades and is ≥ MARGIN points
     clear of break-even — so it optimises WR on signal, not small-sample swings.

Pure stdlib, read-only. Run with the bot up or down:
    python3 tools/analyze_failures.py            # last 6h
    python3 tools/analyze_failures.py --hours 24
    python3 tools/analyze_failures.py --all       # whole history
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "decisions.db"
LEVERS = Path(__file__).resolve().parent.parent / "data" / "flip_levers.json"
BREAKEVEN = 52.08  # 1/(1+0.92) at 92% payout
PAYOUT_FACTOR = 1.38   # $1.50 stake * 0.92
LOSS = -1.50

# Optimizer guardrails — act on signal, not noise (per the data-driven rule):
#   only recommend a lever change when a band has >= MIN_ACT_N resolved trades AND
#   its WR is clear of break-even by >= MARGIN points.
MIN_ACT_N = 30
MARGIN = 2.0


def _wr(rows):
    n = len(rows)
    if not n:
        return 0.0, 0, 0.0
    wins = sum(1 for o in rows if o == "win")
    pnl = wins * PAYOUT_FACTOR + (n - wins) * LOSS
    return wins * 100.0 / n, n, pnl


def _verdict(wr, n, floor=BREAKEVEN, min_n=20):
    if n < min_n:
        return "·  (thin sample)"
    return "✅ +EV" if wr >= floor else "⚠️  below B/E"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    where = "outcome IN ('win','loss')"
    if not args.all:
        where += (f" AND replace(substr(ts,1,19),'T',' ') > "
                  f"datetime('now','-{args.hours} hours')")
    rows = con.execute(
        f"SELECT ts, pair_api, outcome, "
        f"json_extract(data,'$.flip_metrics.entry_kind') kind, "
        f"json_extract(data,'$.flip_metrics.adx') adx, "
        f"json_extract(data,'$.flip_metrics.dist_atr') dist, "
        f"json_extract(data,'$.flip_metrics.bb_width_bps') bbw, "
        f"json_extract(data,'$.flip_metrics.macd_gap_std') gapstd, "
        f"json_extract(data,'$.flip_metrics.st_dir') dir "
        f"FROM decisions WHERE {where} ORDER BY pair_api, ts"
    ).fetchall()

    scope = "ALL history" if args.all else f"last {args.hours:g}h"
    print(f"\n=== Flip failure analysis — {scope} — break-even {BREAKEVEN}% ===\n")
    if not rows:
        print("No resolved trades in window.")
        return

    # 1. Headline
    wr, n, pnl = _wr([r["outcome"] for r in rows])
    print(f"OVERALL: {n} trades  WR {wr:.1f}%  P&L ${pnl:+.2f}   {_verdict(wr, n)}")
    for kind in ("flip", "trend"):
        krows = [r["outcome"] for r in rows if r["kind"] == kind]
        if krows:
            w, k, p = _wr(krows)
            print(f"  {kind:5}: {k:4} trades  WR {w:.1f}%  P&L ${p:+.2f}   {_verdict(w, k)}")

    # 2. Post-loss autocorrelation (per-pair, time since last loss)
    print("\n--- Post-loss window (WR by seconds since last loss on same pair) ---")
    buckets = {"<30s": [], "30-60s": [], "60-120s": [], "2-5m": [], "5m+": []}
    prev = {}  # pair -> (epoch, outcome)
    for r in rows:
        sec = _epoch(r["ts"])
        p = prev.get(r["pair_api"])
        if p and p[1] == "loss" and sec is not None and p[0] is not None:
            gap = sec - p[0]
            b = ("<30s" if gap < 30 else "30-60s" if gap < 60 else
                 "60-120s" if gap < 120 else "2-5m" if gap < 300 else "5m+")
            buckets[b].append(r["outcome"])
        prev[r["pair_api"]] = (sec, r["outcome"])
    for b, orows in buckets.items():
        w, k, _ = _wr(orows)
        print(f"  {b:8}: {k:4} trades  WR {w:.1f}%   {_verdict(w, k, min_n=15)}")
    early = buckets["<30s"] + buckets["30-60s"]
    if len(early) >= 15:
        ew, ek, ep = _wr(early)
        if ew < BREAKEVEN:
            print(f"  → TUNE: {ek} trades still land <60s after a loss at {ew:.1f}% WR "
                  f"(${ep:+.2f}). Raise POST_LOSS_PAIR_COOLDOWN_SECONDS (or it isn't enforced).")
        else:
            print("  → post-loss window looks clean (cooldown effective or recovered).")

    # 3. Pair leaderboard
    print("\n--- Pair leaderboard (by P&L) ---")
    by_pair = {}
    for r in rows:
        by_pair.setdefault(r["pair_api"], []).append(r["outcome"])
    ranked = sorted(((p, *_wr(o)) for p, o in by_pair.items()), key=lambda x: x[3])
    for p, w, k, pnl_ in ranked[:5]:
        print(f"  WORST {p:14} {k:4}t  WR {w:.1f}%  ${pnl_:+.2f}")
    for p, w, k, pnl_ in ranked[-5:][::-1]:
        print(f"  BEST  {p:14} {k:4}t  WR {w:.1f}%  ${pnl_:+.2f}")

    # 4. Dimension scan
    print("\n--- Dimension scan (bands below break-even = tune candidates) ---")
    _scan(rows, "bb_width", "bbw", [(0, 4, "<4 chop"), (4, 8, "4-8"),
          (8, 14, "8-14 ✦"), (14, 25, "14-25"), (25, 1e9, "25+")])
    _scan(rows, "ADX", "adx", [(0, 25, "<25"), (25, 30, "25-30 dead"),
          (30, 40, "30-40"), (40, 1e9, "40+")])
    _scan(rows, "dist_atr", "dist", [(0, 2, "<2"), (2, 3, "2-3"), (3, 1e9, "3+")])
    # MACD-width consistency (continuation hypothesis): low gap-std = steadier
    # width. Restrict to continuations where the edge is claimed.
    cont = [r for r in rows if r["kind"] == "trend"]
    if cont:
        print("  MACD gap-std (continuations only; low = consistent width):")
        _scan(cont, "  cont gapstd", "gapstd",
              [(0, 0.05, "<0.05 steady"), (0.05, 0.15, "0.05-0.15"),
               (0.15, 0.3, "0.15-0.3"), (0.3, 1e9, "0.3+ erratic")])
    print("  direction:")
    for d in ("CALL", "PUT"):
        w, k, p = _wr([r["outcome"] for r in rows if r["dir"] == d])
        if k:
            print(f"    {d:5}: {k:4}t  WR {w:.1f}%  ${p:+.2f}   {_verdict(w, k)}")

    # 5. WR trend (regression radar) + 6. optimizer recommendations
    _wr_trend(con)
    _recommend(rows)
    print()


# ── WR trend: catch regression early ─────────────────────────────────────────

def _wr_trend(con) -> None:
    print("\n--- WR trend (regression radar) ---")
    spans = [("30m", 0.5), ("2h", 2), ("6h", 6), ("24h", 24)]
    prev = None
    for label, hrs in spans:
        r = con.execute(
            "SELECT outcome FROM decisions WHERE outcome IN ('win','loss') "
            "AND replace(substr(ts,1,19),'T',' ') > datetime('now', ?)",
            (f"-{hrs} hours",),
        ).fetchall()
        w, n, _ = _wr([x["outcome"] for x in r])
        arrow = ""
        if prev is not None and n >= MIN_ACT_N:
            arrow = " ↑" if w > prev + 1 else " ↓" if w < prev - 1 else " ="
        print(f"  {label:4}: {n:4}t  WR {w:.1f}%{arrow}   {_verdict(w, n)}")
        prev = w


# ── Optimizer: find BOTH leak types (tighten losers, loosen excluded winners) ──

def _active_levers() -> dict:
    try:
        return json.loads(LEVERS.read_text())
    except Exception:
        return {}


def _band_stats(rows, col, lo, hi):
    return _wr([r["outcome"] for r in rows
                if r[col] is not None and lo <= float(r[col]) < hi])


def _recommend(rows) -> None:
    print("\n--- OPTIMIZER recommendations (n≥{} & ≥{:.0f}pts off B/E) ---".format(MIN_ACT_N, MARGIN))
    lv = _active_levers()
    actions: list[str] = []

    # bb_width: global gate [min,max]. Find excluded-but-profitable (loosen) and
    # included-but-losing (tighten) fine bands.
    bmin = float(lv.get("bb_width_min", 0) or 0)
    bmax = float(lv.get("bb_width_max", 0) or 0)
    fine = [(0, 3), (3, 4), (4, 6), (6, 8), (8, 14), (14, 18), (18, 25), (25, 1e9)]
    for lo, hi in fine:
        w, n, _ = _band_stats(rows, "bbw", lo, hi)
        if n < MIN_ACT_N:
            continue
        included = (bmin == 0 or lo >= bmin) and (bmax == 0 or hi <= bmax)
        if included and w <= BREAKEVEN - MARGIN:
            actions.append(f"bb_width {lo}-{hi}: TRADED at {w:.1f}% (n={n}) — TIGHTEN to exclude")
        elif not included and w >= BREAKEVEN + MARGIN:
            actions.append(f"bb_width {lo}-{hi}: EXCLUDED but {w:.1f}% (n={n}) — LOOSEN to capture")

    # direction skew → consider a direction-aware filter only on a big, clear sample.
    for d in ("CALL", "PUT"):
        w, n, _ = _wr([r["outcome"] for r in rows if r["dir"] == d])
        if n >= MIN_ACT_N * 2 and w <= BREAKEVEN - MARGIN:
            actions.append(f"direction {d}: {w:.1f}% (n={n}) — consider de-weighting/blocking {d}")

    # bad pairs (big sample, clearly losing) → blocklist candidates.
    by_pair: dict[str, list] = {}
    for r in rows:
        by_pair.setdefault(r["pair_api"], []).append(r["outcome"])
    for pair, o in by_pair.items():
        w, n, pnl = _wr(o)
        if n >= MIN_ACT_N and w <= BREAKEVEN - MARGIN:
            actions.append(f"pair {pair}: {w:.1f}% (n={n}, ${pnl:+.0f}) — blocklist candidate")

    if actions:
        for a in actions:
            print(f"  → {a}")
    else:
        print("  → no high-confidence lever change (samples thin or bands near B/E) — hold")


def _scan(rows, label, col, bands):
    print(f"  {label}:")
    for lo, hi, name in bands:
        orows = [r["outcome"] for r in rows
                 if r[col] is not None and lo <= float(r[col]) < hi]
        w, k, p = _wr(orows)
        if k:
            print(f"    {name:10}: {k:4}t  WR {w:.1f}%  ${p:+.2f}   {_verdict(w, k)}")


def _epoch(ts):
    # ts is ISO-8601 'YYYY-MM-DDTHH:MM:SS...'; convert to epoch seconds.
    try:
        from datetime import datetime, timezone
        s = ts[:19].replace("T", " ")
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


if __name__ == "__main__":
    main()
