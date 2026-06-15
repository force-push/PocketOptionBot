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

Pure stdlib, read-only. Run with the bot up or down:
    python3 tools/analyze_failures.py            # last 6h
    python3 tools/analyze_failures.py --hours 24
    python3 tools/analyze_failures.py --all       # whole history
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "decisions.db"
BREAKEVEN = 52.08  # 1/(1+0.92) at 92% payout
PAYOUT_FACTOR = 1.38   # $1.50 stake * 0.92
LOSS = -1.50


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
    print()


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
