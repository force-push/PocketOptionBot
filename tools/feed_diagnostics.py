"""Statistical profile of the raw candle feed (SHADOW_TRADE_ANALYSIS.md addendum).

Measures the GENERATING PROCESS of each pair's price feed, not indicator
transforms of it. The PO library caps history at ~150 candles per request, so
we profile at multiple timeframes and POOL across pairs for power:

  1. Lag-1..3 return autocorrelation per timeframe (5s / 30s / 60s)
  2. Lo-MacKinlay variance ratio VR(q), q=2,6 (5s candles)
       VR < 1 → mean-reverting · ≈1 → random walk · >1 → trending
  3. Run-length continuation: P(next candle same color | run of N)
       < 50% → fade runs · > 50% → ride runs

Pooled across ~15 pairs the lag-1 autocorrelation SE is ~0.02, enough to
detect any economically meaningful structure.

Usage (stop the bot first — one WS session per SSID):
    python3 tools/feed_diagnostics.py
    python3 tools/feed_diagnostics.py --pairs EURUSD_otc,GBPUSD_otc --json out.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from broker.po_api import PocketOptionAPIClient

PERIODS = (5, 30, 60)          # candle timeframes to profile
MIN_CANDLES = 100


def autocorr(x: np.ndarray, lag: int) -> float:
    if len(x) <= lag + 2:
        return float("nan")
    a, b = x[:-lag], x[lag:]
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0:
        return float("nan")
    return float(((a - a.mean()) * (b - b.mean())).mean() / (sa * sb))


def variance_ratio(r: np.ndarray, q: int) -> float:
    """Lo-MacKinlay VR(q): Var(q-period return) / (q * Var(1-period return))."""
    if len(r) < q * 10:
        return float("nan")
    v1 = r.var(ddof=1)
    if v1 == 0:
        return float("nan")
    rq = np.array([r[i:i + q].sum() for i in range(0, len(r) - q + 1)])
    return float(rq.var(ddof=1) / (q * v1))


def run_continuation(signs: np.ndarray, n: int) -> tuple[float, int]:
    """P(next candle same sign | current run length == n), and sample count."""
    cont = tot = 0
    run = 1
    for i in range(1, len(signs)):
        if signs[i - 1] == 0:
            run = 1
            continue
        if i >= 2 and signs[i - 1] == signs[i - 2]:
            run += 1
        else:
            run = 1
        if run == n and signs[i] != 0:
            tot += 1
            cont += signs[i] == signs[i - 1]
    return (cont / tot if tot else float("nan")), tot


async def fetch_returns(api, pair: str, period: int):
    candles = await api.get_candles(pair, period=period, count=200)
    if not candles or len(candles) < MIN_CANDLES:
        return None, None
    closes = np.array([float(c["close"]) for c in candles])
    opens = np.array([float(c["open"]) for c in candles])
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(closes))
    r = r[np.isfinite(r)]
    if len(r) < MIN_CANDLES - 1 or r.std() == 0:
        return None, None
    signs = np.sign(closes - opens).astype(int)
    return r, signs


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    api = PocketOptionAPIClient(dry_run=True)
    await api.connect()

    if args.pairs:
        pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    else:
        active = await api.get_active_pairs()
        pairs = [p["symbol"] for p in active[: args.top]]
    print(f"profiling {len(pairs)} pairs at periods {PERIODS}\n")

    # pooled[period] -> lists of per-pair stats
    pooled = {p: {"ac1": [], "ac2": [], "ac3": [], "vr2": [], "vr6": [],
                  "cont1": [], "cont3": [], "zero": []} for p in PERIODS}
    results = []

    for pair in pairs:
        row = {"pair": pair}
        ok = False
        for period in PERIODS:
            try:
                r, signs = await asyncio.wait_for(fetch_returns(api, pair, period), timeout=45.0)
            except Exception as exc:  # noqa: BLE001
                print(f"{pair} @{period}s: failed ({exc})")
                r = None
            if r is None:
                continue
            ok = True
            st = {
                "n": len(r),
                "ac": [autocorr(r, k) for k in (1, 2, 3)],
                "vr2": variance_ratio(r, 2),
                "vr6": variance_ratio(r, 6),
                "cont1": run_continuation(signs, 1),
                "cont3": run_continuation(signs, 3),
                "zero": float((r == 0).mean()),
            }
            row[f"p{period}"] = st
            P = pooled[period]
            P["ac1"].append(st["ac"][0]); P["ac2"].append(st["ac"][1]); P["ac3"].append(st["ac"][2])
            P["vr2"].append(st["vr2"]); P["vr6"].append(st["vr6"])
            if st["cont1"][1] >= 15: P["cont1"].append(st["cont1"][0])
            if st["cont3"][1] >= 10: P["cont3"].append(st["cont3"][0])
            P["zero"].append(st["zero"])
        if ok:
            results.append(row)
            s5 = row.get("p5")
            if s5:
                print(f"{pair:<14} 5s: ac1={s5['ac'][0]:+.3f} vr2={s5['vr2']:.2f} vr6={s5['vr6']:.2f} "
                      f"cont1={s5['cont1'][0]*100:.0f}%/{s5['cont1'][1]} zero={s5['zero']*100:.0f}%")

    print("\n" + "=" * 72)
    print(f"POOLED across {len(results)} pairs (mean ± SE):")
    for period in PERIODS:
        P = pooled[period]
        if not P["ac1"]:
            continue
        def ms(v):
            v = [x for x in v if np.isfinite(x)]
            if not v: return "—"
            return f"{np.mean(v):+.3f}±{np.std(v)/max(len(v),1)**.5:.3f}"
        def msp(v):
            v = [x for x in v if np.isfinite(x)]
            if not v: return "—"
            return f"{np.mean(v)*100:.1f}%±{np.std(v)/max(len(v),1)**.5*100:.1f}"
        print(f"  {period:>3}s candles (n={len(P['ac1'])} pairs): "
              f"ac1={ms(P['ac1'])}  ac2={ms(P['ac2'])}  "
              f"vr2={ms([v-1 for v in P['vr2']])}+1  vr6={ms([v-1 for v in P['vr6']])}+1")
        print(f"        run-continuation: P(cont|run=1)={msp(P['cont1'])}  "
              f"P(cont|run=3)={msp(P['cont3'])}  zero-returns={msp(P['zero'])}")

    ac1_5 = [x for x in pooled[5]["ac1"] if np.isfinite(x)]
    if ac1_5:
        m = float(np.mean(ac1_5)); se = float(np.std(ac1_5) / len(ac1_5) ** 0.5)
        verdict = ("MEAN-REVERTING — fade-style entries structurally correct"
                   if m < -2 * se and m < -0.02 else
                   "TRENDING — momentum structurally correct"
                   if m > 2 * se and m > 0.02 else
                   "RANDOM WALK at 5s — no exploitable linear structure")
        print(f"\nVERDICT (5s lag-1 pooled): {m:+.3f} ± {se:.3f} → {verdict}")

    if args.json and results:
        Path(args.json).write_text(json.dumps(results, default=float, indent=1))
        print(f"raw → {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
