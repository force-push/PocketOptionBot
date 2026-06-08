#!/usr/bin/env python3
"""Signal-attribution analysis over recorded trade decisions.

Reads data/decisions.jsonl and reports, for the *resolved* trades (those with a
win/loss outcome), how each individual TA signal relates to the outcome — plus
confluence-score and agreement-count breakdowns, per-pair win rates, and a
summary of how much data the gates are censoring.

This is a read-only diagnostic. Run it whenever the dataset grows:

    python scripts/analyze_signals.py
    python scripts/analyze_signals.py --data data/decisions.jsonl --min-n 20

The headline question it answers: does a signal agreeing with the traded
direction actually predict a win? A useful confirmer should show a higher win
rate when it agrees than when it is neutral or opposes.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATA = _PROJECT_ROOT / "data" / "decisions.jsonl"

WIN, LOSS, DRAW = "win", "loss", "draw"


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"no data file at {path}")
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out


def win_rate(rows: list[dict]) -> tuple[float | None, int]:
    """Win rate over win/loss rows (draws excluded from numerator and denom)."""
    wl = [r for r in rows if r.get("outcome") in (WIN, LOSS)]
    if not wl:
        return None, 0
    return sum(1 for r in wl if r.get("outcome") == WIN) / len(wl), len(wl)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion (small-sample safe)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def fmt_pct(x: float | None) -> str:
    return f"{x*100:4.1f}%" if isinstance(x, (int, float)) else "  -  "


def breakeven_for_payout(payout_pct: float) -> float:
    """Win rate needed to break even at a given payout %: 1 / (1 + payout)."""
    return 1.0 / (1.0 + payout_pct / 100.0)


def report(rows: list[dict], min_n: int) -> None:
    traded = [r for r in rows if r.get("decision") == "TRADE"]
    resolved = [r for r in traded if r.get("outcome") in (WIN, LOSS, DRAW)]
    wl = [r for r in resolved if r.get("outcome") in (WIN, LOSS)]
    base, n_base = win_rate(wl)

    print("=" * 68)
    print("SIGNAL ATTRIBUTION REPORT")
    print("=" * 68)
    print(f"decisions total      : {len(rows)}")
    print(f"  traded             : {len(traded)}")
    print(f"  resolved (W/L/D)   : {len(resolved)}  "
          f"(draws: {sum(1 for r in resolved if r.get('outcome') == DRAW)})")
    print(f"  win/loss (scored)  : {n_base}")
    if base is not None:
        lo, hi = wilson_ci(sum(1 for r in wl if r['outcome'] == WIN), n_base)
        print(f"base win rate        : {fmt_pct(base)}  (95% CI {fmt_pct(lo)}–{fmt_pct(hi)})")

    # Break-even context from observed payouts.
    payouts = [r.get("payout_pct") for r in wl if r.get("payout_pct")]
    if payouts:
        med = sorted(payouts)[len(payouts) // 2]
        be = breakeven_for_payout(med)
        edge = (base - be) if base is not None else None
        print(f"median payout        : {med}%  -> break-even WR {fmt_pct(be)}  "
              f"-> edge {('%+.1f pts' % (edge*100)) if edge is not None else '-'}")

    # ── Per-signal attribution ───────────────────────────────────────────────
    print("\n" + "-" * 68)
    print("PER-SIGNAL: win rate when the signal AGREES with the traded direction")
    print("-" * 68)
    print(f"{'signal':<15}{'agree n':>8}{'WR':>7}{'  ':>2}"
          f"{'neut n':>7}{'WR':>7}{'  ':>2}{'opp n':>6}{'WR':>7}{'   lift(agree-neut)':>20}")
    sig_names = sorted({k for r in resolved for k in (r.get("our_signal_breakdown") or {})})
    for s in sig_names:
        agree, neutral, oppose = [], [], []
        for r in resolved:
            td = r.get("our_direction")
            bd = (r.get("our_signal_breakdown") or {}).get(s)
            if not bd:
                continue
            d = bd[0]
            (neutral if d is None else agree if d == td else oppose).append(r)
        aw, an = win_rate(agree)
        nw, nn = win_rate(neutral)
        ow, on = win_rate(oppose)
        lift = (aw - nw) if (aw is not None and nw is not None) else None
        flag = ""
        if an >= min_n and aw is not None and base is not None:
            if aw < base - 0.03:
                flag = "  ⚠ agreeing HURTS"
            elif aw > base + 0.03:
                flag = "  ✓ agreeing helps"
        if on >= min_n and ow is not None and base is not None and ow > base + 0.03:
            flag += "  ⚠ opposing > base (inverted?)"
        if an == 0 and nn > 0 and on == 0:
            flag = "  ✗ never fires a direction (dead)"
        lift_s = ("%+.1f pts" % (lift * 100)) if lift is not None else "   -   "
        print(f"{s:<15}{an:>8}{fmt_pct(aw):>7}{'  ':>2}"
              f"{nn:>7}{fmt_pct(nw):>7}{'  ':>2}{on:>6}{fmt_pct(ow):>7}{lift_s:>14}{flag}")

    # ── Confluence score buckets ─────────────────────────────────────────────
    print("\n" + "-" * 68)
    print("CONFLUENCE SCORE vs win rate")
    print("-" * 68)
    edges = [0.0, 0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.01]
    for lo, hi in zip(edges, edges[1:]):
        b = [r for r in resolved if lo <= (r.get("our_confluence_score") or 0) < hi]
        w, n = win_rate(b)
        if n:
            print(f"  [{lo:.1f}, {hi:.1f}) : n={n:>4}  WR={fmt_pct(w)}")

    # ── Agreement-count buckets ──────────────────────────────────────────────
    print("\n" + "-" * 68)
    print("# SIGNALS AGREEING with traded direction vs win rate")
    print("-" * 68)
    by_k: dict[int, list[dict]] = defaultdict(list)
    for r in resolved:
        td = r.get("our_direction")
        bd = r.get("our_signal_breakdown") or {}
        k = sum(1 for v in bd.values() if v and v[0] == td)
        by_k[k].append(r)
    for k in sorted(by_k):
        w, n = win_rate(by_k[k])
        print(f"  {k} agree : n={n:>4}  WR={fmt_pct(w)}")

    # ── Per-pair win rate (min sample) ───────────────────────────────────────
    print("\n" + "-" * 68)
    print(f"PER-PAIR win rate (n >= {min_n})")
    print("-" * 68)
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for r in resolved:
        by_pair[r.get("pair_api", "?")].append(r)
    pair_stats = []
    for p, rs in by_pair.items():
        w, n = win_rate(rs)
        if w is not None and n >= min_n:
            pair_stats.append((w, n, p))
    for w, n, p in sorted(pair_stats, reverse=True):
        print(f"  {p:<16} n={n:>4}  WR={fmt_pct(w)}")

    # ── Censoring summary ────────────────────────────────────────────────────
    print("\n" + "-" * 68)
    print("CENSORING: decisions we never got an outcome for (gate filtered)")
    print("-" * 68)
    skips = Counter(r.get("skip_reason") for r in rows if r.get("decision") == "SKIP")
    for reason, c in skips.most_common():
        print(f"  {str(reason):<16} {c}")
    print("\nThese skips have NO outcome — the dataset is censored on disagreement.")
    print("Growing coverage requires recording outcomes for would-be-skipped")
    print("trades (demo shadow mode), not back-filling history.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=_DEFAULT_DATA)
    ap.add_argument("--min-n", type=int, default=20,
                    help="minimum sample size before flagging/printing a slice")
    args = ap.parse_args(argv)
    report(load_rows(args.data), args.min_n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
