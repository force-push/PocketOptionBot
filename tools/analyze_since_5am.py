"""One-off deep analysis of trades since 5am ACST 2026-06-13 vs all history.

Cutoff: 5am ACST = 2026-06-12T19:30:00+00:00 UTC.
Looks at: real vs shadow, per-signal correlation, expiry, pair, sentiment,
shadow_kind. Read-only — does not mutate decisions.jsonl.
"""
import json
from collections import defaultdict
from datetime import datetime, timezone

PATH = "data/decisions.jsonl"
CUTOFF = datetime(2026, 6, 12, 19, 30, 0, tzinfo=timezone.utc)  # 5am ACST
BREAKEVEN = 0.5217  # 92% payout EV=0


def load():
    rows = []
    with open(PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def ts(r):
    try:
        return datetime.fromisoformat(r["ts"])
    except Exception:
        return None


def is_resolved(r):
    return (r.get("outcome") or "").lower() in ("win", "loss")


def won(r):
    return (r.get("outcome") or "").lower() == "win"


def wr(rows):
    res = [r for r in rows if is_resolved(r)]
    if not res:
        return (0.0, 0, 0.0)
    w = sum(1 for r in res if won(r))
    pnl = sum((r.get("pnl") or 0.0) for r in res)
    return (w / len(res), len(res), pnl)


def fmt(label, rows):
    rate, n, pnl = wr(rows)
    flag = "" if n == 0 else ("  ✓EDGE" if rate > BREAKEVEN else "  ✗below-BE")
    return f"  {label:34s} n={n:4d}  WR={rate*100:5.1f}%  P&L={pnl:+8.2f}{flag}"


def section(title):
    print(f"\n{'='*70}\n{title}\n{'='*70}")


def main():
    rows = load()
    recent = [r for r in rows if (t := ts(r)) and t >= CUTOFF]
    older = [r for r in rows if (t := ts(r)) and t < CUTOFF]

    # split real (shadow=False) vs shadow
    def real(rs):
        return [r for r in rs if not r.get("shadow")]

    def shadow(rs):
        return [r for r in rs if r.get("shadow")]

    section("HEADLINE — REAL trades (shadow=False)")
    print(fmt("ALL history (real)", real(rows)))
    print(fmt("BEFORE 5am (real)", real(older)))
    print(fmt("SINCE 5am (real)", real(recent)))

    section("HEADLINE — SHADOW trades (data-collection)")
    print(fmt("ALL history (shadow)", shadow(rows)))
    print(fmt("SINCE 5am (shadow)", shadow(recent)))

    # ---- everything below is SINCE 5am only ----
    R = real(recent)
    S = shadow(recent)
    ALLrec = recent

    section("SINCE 5am — REAL by shadow_kind / source")
    by_kind = defaultdict(list)
    for r in ALLrec:
        k = r.get("shadow_kind") or ("main" if not r.get("shadow") else "shadow_other")
        by_kind[k].append(r)
    for k in sorted(by_kind, key=lambda k: -wr(by_kind[k])[1]):
        print(fmt(k, by_kind[k]))

    section("SINCE 5am — REAL by EXPIRY (seconds)")
    by_exp = defaultdict(list)
    for r in R:
        by_exp[r.get("expiry_seconds")].append(r)
    for e in sorted(by_exp):
        print(fmt(f"{e}s", by_exp[e]))

    section("SINCE 5am — SHADOW expiry experiment (shadow_kind=expiry)")
    by_exp_s = defaultdict(list)
    for r in S:
        if r.get("shadow_kind") == "expiry":
            by_exp_s[r.get("expiry_seconds")].append(r)
    for e in sorted(by_exp_s):
        print(fmt(f"{e}s", by_exp_s[e]))

    section("SINCE 5am — REAL by DIRECTION")
    by_dir = defaultdict(list)
    for r in R:
        by_dir[r.get("our_direction")].append(r)
    for d in sorted(by_dir, key=lambda x: str(x)):
        print(fmt(str(d), by_dir[d]))

    section("SINCE 5am — REAL by PAIR (resolved n>=5, sorted by WR)")
    by_pair = defaultdict(list)
    for r in R:
        by_pair[r.get("pair_api")].append(r)
    pair_stats = []
    for p, rs in by_pair.items():
        rate, n, pnl = wr(rs)
        if n >= 5:
            pair_stats.append((p, rate, n, pnl))
    for p, rate, n, pnl in sorted(pair_stats, key=lambda x: -x[1]):
        flag = "✓" if rate > BREAKEVEN else "✗"
        print(f"  {p:18s} n={n:3d}  WR={rate*100:5.1f}%  P&L={pnl:+7.2f}  {flag}")

    section("SINCE 5am — SENTIMENT coverage & correlation (ALL trades w/ outcome)")
    res = [r for r in ALLrec if is_resolved(r)]
    have_sent = [r for r in res if r.get("sentiment") is not None]
    print(f"  resolved trades: {len(res)}   with sentiment: {len(have_sent)} ({100*len(have_sent)/max(1,len(res)):.1f}%)")
    if have_sent:
        # bucket sentiment 0-100 crowd buy%
        buckets = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
        for lo, hi in buckets:
            b = [r for r in have_sent if lo <= r["sentiment"] < hi]
            if b:
                print(fmt(f"sentiment {lo}-{hi}", b))
        # sentiment-aligned vs contrarian: did we trade WITH the crowd?
        aligned, contra = [], []
        for r in have_sent:
            d = r.get("our_direction")
            s = r["sentiment"]
            if d == "CALL":
                (aligned if s >= 50 else contra).append(r)
            elif d == "PUT":
                (aligned if s < 50 else contra).append(r)
        print(fmt("traded WITH crowd (aligned)", aligned))
        print(fmt("traded AGAINST crowd (contra)", contra))

    section("SINCE 5am — per-SIGNAL correlation with WIN (real+shadow resolved)")
    # our_signal_breakdown: {signal_name: [direction, confidence, reason]}
    sig_agree = defaultdict(lambda: [0, 0])  # signal voted SAME dir as trade -> [wins, total]
    for r in res:
        bd = r.get("our_signal_breakdown") or {}
        td = r.get("our_direction")
        w = won(r)
        for name, v in bd.items():
            if not isinstance(v, (list, tuple)) or not v:
                continue
            sd = v[0]
            if sd == td and td is not None:  # this signal agreed with the taken direction
                sig_agree[name][1] += 1
                if w:
                    sig_agree[name][0] += 1
    print("  (when signal agreed with taken direction, how often did the trade win?)")
    stats = []
    for name, (w, n) in sig_agree.items():
        if n >= 10:
            stats.append((name, w / n, n))
    for name, rate, n in sorted(stats, key=lambda x: -x[1]):
        flag = "✓" if rate > BREAKEVEN else "✗"
        print(f"  {name:18s} agreed-n={n:4d}  win-when-agree={rate*100:5.1f}%  {flag}")

    section("SINCE 5am — agreement COUNT vs WR (real)")
    by_agree = defaultdict(list)
    for r in R:
        bd = r.get("our_signal_breakdown") or {}
        td = r.get("our_direction")
        cnt = sum(1 for v in bd.values() if isinstance(v, (list, tuple)) and v and v[0] == td)
        by_agree[cnt].append(r)
    for c in sorted(by_agree):
        print(fmt(f"{c} signals agreed", by_agree[c]))


if __name__ == "__main__":
    main()
