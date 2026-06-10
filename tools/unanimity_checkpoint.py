"""Follow-unanimity tracker (SHADOW_TRADE_ANALYSIS.md Addendum 3 follow-up).

The candidate strategy: when >=7 signals agree on a direction, FOLLOW it.
Measured two ways from data we already collect:
  - directly: real + time_of_day trades whose traded direction had >=7 agreeing
    signals (gate-passing pairs)
  - by complement: fade shadows (placed opposite the >=7-agree bloc) — a fade
    LOSS is a follow WIN on the same setup (all evaluated pairs)

PROMOTION GATE (set 2026-06-11): follow-unanimity on gate-passing pairs must
show >= 55% over >= 400 resolved, spanning >= 3 distinct UTC days with EVERY
day individually >= 52%. The unanimity edge already flipped sign once between
06-09/10 and 06-10/11 — day-level stability is the test that matters.

Usage: python3 tools/unanimity_checkpoint.py
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GATE_WR, GATE_N, GATE_DAYS, GATE_DAY_WR = 0.55, 400, 3, 0.52
CUT = "2026-06-10T14:54"  # fade implementation; before this >=7-agree fired differently


def wilson(w: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p, z = w / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def main() -> None:
    recs = [json.loads(l) for l in Path("data/decisions.jsonl").read_text().splitlines() if l.strip()]

    direct = []   # (day, agree_count, win) — real/time_of_day trades, >=7 agree, gate-passing pairs
    mirror = []   # (day, agree_count, follow_win) — fade shadows inverted, all pairs
    for r in recs:
        if r.get("ts", "") < CUT or r.get("outcome") not in ("win", "loss"):
            continue
        day = r["ts"][:10]
        kind = r.get("shadow_kind") if r.get("shadow") else "REAL"
        if kind in ("REAL", "time_of_day"):
            d = r.get("our_direction")
            bd = r.get("our_signal_breakdown") or {}
            if not d:
                continue
            k = sum(1 for v in bd.values() if (list(v) + [None])[0] == d)
            if k >= 7:
                direct.append((day, k, r["outcome"] == "win"))
        elif kind == "fade":
            wsr = r.get("would_skip_reason") or ""
            k = int(wsr.split("_")[1]) if wsr.startswith("fade_") and wsr.split("_")[1].isdigit() else 7
            mirror.append((day, k, r["outcome"] == "loss"))  # fade loss = follow win

    def report(name: str, rows: list) -> tuple[int, int, dict]:
        w = sum(1 for _, _, x in rows if x)
        n = len(rows)
        lo, hi = wilson(w, n)
        print(f"\n── {name}: {w}/{n} = {w/n*100 if n else 0:.1f}%  (95% CI {lo*100:.1f}–{hi*100:.1f}%)")
        by_day: dict = defaultdict(lambda: [0, 0])
        for day, _, x in rows:
            by_day[day][0] += x
            by_day[day][1] += 1
        for day in sorted(by_day):
            dw, dn = by_day[day]
            flag = "✓" if dn >= 30 and dw / dn >= GATE_DAY_WR else ("✗" if dn >= 30 else "·")
            print(f"     {day}: {dw}/{dn} = {dw/dn*100:.1f}%  {flag}")
        for kmin, label in ((7, "exactly 7"), (8, "8+")):
            sub = [x for _, k, x in rows if (k == 7 if kmin == 7 else k >= 8)]
            if sub:
                sw = sum(sub)
                print(f"     {label}: {sw}/{len(sub)} = {sw/len(sub)*100:.1f}%")
        return w, n, by_day

    print(f"FOLLOW-UNANIMITY CHECKPOINT  (gate: ≥{GATE_WR*100:.0f}% @ n≥{GATE_N}, "
          f"≥{GATE_DAYS} days each ≥{GATE_DAY_WR*100:.0f}%)")
    w, n, by_day = report("DIRECT (gate-passing pairs — the promotable population)", direct)
    report("MIRROR (fade complement, all evaluated pairs)", mirror)

    qual_days = [d for d, (dw, dn) in by_day.items() if dn >= 30 and dw / dn >= GATE_DAY_WR]
    lo, _ = wilson(w, n)
    print(f"\nGATE STATUS: n={n}/{GATE_N}  WR={w/n*100 if n else 0:.1f}% (need ≥{GATE_WR*100:.0f}%)  "
          f"qualifying days={len(qual_days)}/{GATE_DAYS}")
    if n >= GATE_N and w / n >= GATE_WR and len(qual_days) >= GATE_DAYS:
        print("→ GATE CLEARED — eligible for promotion discussion (check CI lower bound too: "
              f"{lo*100:.1f}%, want >52.1% break-even)")
    else:
        print("→ gate not yet met — keep collecting")


if __name__ == "__main__":
    main()
