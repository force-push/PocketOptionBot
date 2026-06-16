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
        f"json_extract(data,'$.flip_metrics.st_dir') dir, "
        f"COALESCE(json_extract(data,'$.shadow'),0) shadow "
        f"FROM decisions WHERE {where} ORDER BY pair_api, ts"
    ).fetchall()
    # Real trades only (shadow=0) for all analysis — shadow trades don't trigger
    # cooldown and their autocorrelation stats contaminate the post-loss window.
    real_rows = [r for r in rows if not r["shadow"]]

    scope = "ALL history" if args.all else f"last {args.hours:g}h"
    print(f"\n=== Flip failure analysis — {scope} — break-even {BREAKEVEN}% ===\n")
    if not real_rows:
        print("No resolved real trades in window.")
        return

    # 1. Headline (real trades only — shadows are research-only)
    wr, n, pnl = _wr([r["outcome"] for r in real_rows])
    print(f"OVERALL: {n} trades  WR {wr:.1f}%  P&L ${pnl:+.2f}   {_verdict(wr, n)}")
    for kind in ("flip", "trend"):
        krows = [r["outcome"] for r in real_rows if r["kind"] == kind]
        if krows:
            w, k, p = _wr(krows)
            print(f"  {kind:5}: {k:4} trades  WR {w:.1f}%  P&L ${p:+.2f}   {_verdict(w, k)}")

    # 2. Post-loss autocorrelation (real trades only — shadow losses don't trigger
    # cooldown; including them inflates the <30s bucket with shadow→shadow pairs)
    print("\n--- Post-loss window (real trades; WR by seconds since last loss on same pair) ---")
    buckets = {"<30s": [], "30-60s": [], "60-120s": [], "2-5m": [], "5m+": []}
    prev = {}  # pair -> (epoch, outcome)
    for r in real_rows:
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

    # 3. Pair leaderboard (real trades only)
    print("\n--- Pair leaderboard (by P&L) ---")
    by_pair = {}
    for r in real_rows:
        by_pair.setdefault(r["pair_api"], []).append(r["outcome"])
    ranked = sorted(((p, *_wr(o)) for p, o in by_pair.items()), key=lambda x: x[3])
    for p, w, k, pnl_ in ranked[:5]:
        print(f"  WORST {p:14} {k:4}t  WR {w:.1f}%  ${pnl_:+.2f}")
    for p, w, k, pnl_ in ranked[-5:][::-1]:
        print(f"  BEST  {p:14} {k:4}t  WR {w:.1f}%  ${pnl_:+.2f}")

    # 4. Dimension scan (real trades only)
    print("\n--- Dimension scan (bands below break-even = tune candidates) ---")
    _scan(real_rows, "bb_width", "bbw", [(0, 4, "<4 chop"), (4, 8, "4-8"),
          (8, 14, "8-14 ✦"), (14, 25, "14-25"), (25, 1e9, "25+")])
    _scan(real_rows, "ADX", "adx", [(0, 25, "<25"), (25, 30, "25-30 dead"),
          (30, 40, "30-40"), (40, 1e9, "40+")])
    _scan(real_rows, "dist_atr", "dist", [(0, 2, "<2"), (2, 3, "2-3"), (3, 1e9, "3+")])
    # MACD-width consistency (continuation hypothesis): low gap-std = steadier
    # width. Restrict to continuations where the edge is claimed.
    cont = [r for r in real_rows if r["kind"] == "trend"]
    if cont:
        print("  MACD gap-std (continuations only; low = consistent width):")
        _scan(cont, "  cont gapstd", "gapstd",
              [(0, 0.05, "<0.05 steady"), (0.05, 0.15, "0.05-0.15"),
               (0.15, 0.3, "0.15-0.3"), (0.3, 1e9, "0.3+ erratic")])
    print("  direction:")
    for d in ("CALL", "PUT"):
        w, k, p = _wr([r["outcome"] for r in real_rows if r["dir"] == d])
        if k:
            print(f"    {d:5}: {k:4}t  WR {w:.1f}%  ${p:+.2f}   {_verdict(w, k)}")

    # 5. Per-config segmentation, 6. WR trend, 7. optimizer recommendations
    _by_config(con)
    _wr_trend(con)
    _recommend(real_rows)
    print()


# ── Per-config segmentation: clean analysis under "tweaks on the way" ──────────

# The lever subset that defines a "config epoch". Two trades with the same values
# here ran under the same strategy → their outcomes are comparable. Changing any
# of these starts a new epoch, so we never blend regimes into one meaningless WR.
_CONFIG_KEYS = (
    "bb_width_min", "bb_width_max", "flip_confirm_bars", "adx_flip_min",
    "adx_trend_min", "flip_adx_dead_lo", "flip_adx_dead_hi",
    "atr_distance_min", "atr_distance_max", "cont_rsi_min", "cont_macd_gap_min",
)
_MATURE_N = 100   # trades before a config's WR is statistically worth acting on


def _by_config(con) -> None:
    print("\n--- Per-config WR (24h; same lever-set = comparable) ---")
    sel = ", ".join(
        f"json_extract(data,'$.flip_levers.{k}')" for k in _CONFIG_KEYS
    )
    rows = con.execute(
        f"SELECT {sel}, outcome FROM decisions WHERE outcome IN ('win','loss') "
        f"AND replace(substr(ts,1,19),'T',' ') > datetime('now','-24 hours')"
    ).fetchall()
    groups: dict[tuple, list] = {}
    for r in rows:
        sig = tuple(r[i] for i in range(len(_CONFIG_KEYS)))
        groups.setdefault(sig, []).append(r["outcome"])
    cur = _active_levers()
    cur_sig = tuple(cur.get(k) for k in _CONFIG_KEYS)
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for sig, outs in ranked[:6]:
        w, n, p = _wr(outs)
        is_cur = " ←CURRENT" if _sig_match(sig, cur_sig) else ""
        mature = "" if n >= _MATURE_N else f" (immature: {n}/{_MATURE_N})"
        label = f"bb{sig[0]}-{sig[1]} cfm{sig[2]} dead{sig[5]}-{sig[6]}"
        print(f"  {label:30} n={n:4} WR {w:.1f}% ${p:+.0f}{is_cur}{mature}")
    # Maturity verdict for the current config — drives whether tuning is even valid.
    cur_outs = groups.get(next((s for s in groups if _sig_match(s, cur_sig)), None), [])
    cw, cn, _ = _wr(cur_outs)
    if cn >= _MATURE_N:
        print(f"  → current config MATURE (n={cn}, WR {cw:.1f}%) — analysis is viable.")
    else:
        print(f"  → current config IMMATURE (n={cn}/{_MATURE_N}) — HOLD levers to let "
              f"the sample build; tuning now would just chase noise.")


def _sig_match(a, b) -> bool:
    # JSON numbers vs python: compare as floats where possible, else equal.
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        try:
            if float(x) != float(y):
                return False
        except (TypeError, ValueError):
            if x != y:
                return False
    return True


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
