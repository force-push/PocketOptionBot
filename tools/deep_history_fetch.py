"""Deep-history candle fetcher using get_candles_advanced paging.

Pulls thousands of candles per pair (vs the ~100-candle live window) by walking
the server's candle history backwards in pages of 150 candles.  Runs the same
feed-stats diagnostics as feed_diagnostics.py but with real statistical power —
enough data to distinguish per-pair autocorrelation from sampling noise.

Results:
  data/deep_history/<pair>_<period>s.jsonl  — raw candles (one per line)
  data/deep_history_stats.jsonl             — per-pair diagnostics (append)

Usage (stop the bot first — one WS session per SSID):
    .venv/bin/python tools/deep_history_fetch.py
    .venv/bin/python tools/deep_history_fetch.py --pairs EURUSD_otc,BTCUSD_otc
    .venv/bin/python tools/deep_history_fetch.py --top 20 --candles 5000 --period 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time as _time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from broker.po_api import PocketOptionAPIClient
from config.settings import settings

PAGE_SIZE_SECONDS = 750   # 150 candles at 5s per page
MIN_CANDLES = 200         # skip pair if we can't get at least this many


def _autocorr(r: np.ndarray, lag: int) -> float:
    if len(r) <= lag + 2:
        return float("nan")
    a, b = r[:-lag], r[lag:]
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0:
        return float("nan")
    return float(((a - a.mean()) * (b - b.mean())).mean() / (sa * sb))


def _variance_ratio(r: np.ndarray, q: int) -> float:
    if len(r) < q * 10:
        return float("nan")
    v1 = r.var(ddof=1)
    if v1 == 0:
        return float("nan")
    rq = np.array([r[i:i + q].sum() for i in range(0, len(r) - q + 1)])
    return float(rq.var(ddof=1) / (q * v1))


def _run_stats(candles: list[dict]) -> dict:
    closes = np.array([float(c.get("close", c.get("c", 0))) for c in candles])
    opens = np.array([float(c.get("open", c.get("o", 0))) for c in candles])
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(closes))
    r = r[np.isfinite(r)]
    if len(r) < 50 or r.std() == 0:
        return {}
    signs = np.sign(closes - opens).astype(int)
    highs = np.array([float(c.get("high", c.get("h", 0))) for c in candles])
    lows = np.array([float(c.get("low", c.get("l", 0))) for c in candles])
    flat_pct = float(np.mean(highs == lows))  # fraction of candles with h==l (degenerate)
    return {
        "n": int(len(r)),
        "n_candles": len(candles),
        "flat_ohlc_pct": flat_pct,
        "ac1": _autocorr(r, 1),
        "ac2": _autocorr(r, 2),
        "ac3": _autocorr(r, 3),
        "vr2": _variance_ratio(r, 2),
        "vr6": _variance_ratio(r, 6),
        "zero_pct": float((r == 0).mean()),
        "mean_return": float(r.mean()),
        "std_return": float(r.std()),
        "bullish_pct": float((signs > 0).mean()),
    }


async def fetch_deep(api_client: PocketOptionAPIClient, pair: str, period: int,
                     target_candles: int) -> list[dict]:
    """Page backwards through history until we have target_candles or run out."""
    client = api_client._client
    if client is None:
        return []

    try:
        server_ts = await client.get_server_time()
        if server_ts < 1_000_000_000:
            server_ts = int(_time.time())
    except Exception:
        server_ts = int(_time.time())

    all_candles: list[dict] = []
    t = server_ts
    pages = 0

    while len(all_candles) < target_candles:
        try:
            page = await asyncio.wait_for(
                client.get_candles_advanced(pair, period, PAGE_SIZE_SECONDS, t),
                timeout=30.0,
            )
        except Exception as exc:
            print(f"  {pair} page {pages}: error ({exc})")
            break

        if not page:
            break

        all_candles = list(page) + all_candles
        pages += 1
        t = int(page[0].get("timestamp", page[0].get("time", page[0].get("t", t)))) - period

        if pages % 10 == 0:
            print(f"  {pair}: {len(all_candles)} candles so far ({pages} pages)…")

    # Deduplicate by timestamp (paging can produce overlapping edges)
    seen: set = set()
    deduped: list[dict] = []
    for c in all_candles:
        ts_key = c.get("timestamp", c.get("time", c.get("t")))
        if ts_key not in seen:
            seen.add(ts_key)
            deduped.append(c)
    deduped.sort(key=lambda c: c.get("timestamp", c.get("time", c.get("t", 0))))

    print(f"  {pair}: fetched {len(deduped)} candles in {pages} pages")
    return deduped


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="", help="comma-separated pair list; defaults to top-N by payout")
    ap.add_argument("--top", type=int, default=15, help="number of top pairs to profile")
    ap.add_argument("--candles", type=int, default=3000, help="target candles per pair")
    ap.add_argument("--period", type=int, default=5, help="candle period in seconds")
    ap.add_argument("--save-raw", action="store_true", help="write raw candle JSONL files")
    args = ap.parse_args()

    out_dir = Path("data/deep_history")
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_path = Path("data/deep_history_stats.jsonl")

    api = PocketOptionAPIClient(dry_run=True)
    await api.connect()

    if args.pairs:
        pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    else:
        active = await api.get_active_pairs()
        pairs = [p["symbol"] for p in active[: args.top]]

    print(f"Deep-history fetch: {len(pairs)} pairs, target {args.candles} candles @ {args.period}s each\n")

    all_stats: list[dict] = []

    for pair in pairs:
        print(f"{pair}:")
        candles = await fetch_deep(api, pair, args.period, args.candles)

        if len(candles) < MIN_CANDLES:
            print(f"  {pair}: insufficient data ({len(candles)} candles) — skipping\n")
            continue

        if args.save_raw:
            raw_path = out_dir / f"{pair}_{args.period}s.jsonl"
            with raw_path.open("w", encoding="utf-8") as fh:
                for c in candles:
                    fh.write(json.dumps(c, default=str) + "\n")

        stats = _run_stats(candles)
        if not stats:
            print(f"  {pair}: stats computation failed\n")
            continue

        row = {"ts": _time.time(), "pair": pair, "period": args.period, **stats}
        with stats_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=float) + "\n")
        all_stats.append(row)

        flat_warn = f"  ⚠ {stats['flat_ohlc_pct']*100:.0f}% flat candles (h==l)" if stats["flat_ohlc_pct"] > 0.5 else ""
        print(
            f"  n={stats['n_candles']}  ac1={stats['ac1']:+.4f}  ac2={stats['ac2']:+.4f}  "
            f"vr2={stats['vr2']:.3f}  zero={stats['zero_pct']*100:.1f}%  "
            f"flat={stats['flat_ohlc_pct']*100:.0f}%{flat_warn}"
        )
        print()

    if all_stats:
        ac1_vals = [s["ac1"] for s in all_stats if np.isfinite(s["ac1"])]
        vr2_vals = [s["vr2"] for s in all_stats if np.isfinite(s["vr2"])]
        zero_vals = [s["zero_pct"] for s in all_stats]
        flat_vals = [s["flat_ohlc_pct"] for s in all_stats]
        n_vals = [s["n_candles"] for s in all_stats]

        print("=" * 70)
        print(f"POOLED SUMMARY ({len(all_stats)} pairs, period={args.period}s)")
        print(f"  median candles/pair: {sorted(n_vals)[len(n_vals)//2]}")
        if ac1_vals:
            m = float(np.mean(ac1_vals))
            se = float(np.std(ac1_vals) / len(ac1_vals) ** 0.5)
            print(f"  ac1 (lag-1 autocorr):  {m:+.4f} ± {se:.4f} (n={len(ac1_vals)})")
            verdict = (
                "MEAN-REVERTING" if m < -2 * se and m < -0.02 else
                "TRENDING" if m > 2 * se and m > 0.02 else
                "RANDOM WALK"
            )
            print(f"  VERDICT: {verdict}")
        if vr2_vals:
            print(f"  VR(2): {np.mean(vr2_vals):.4f} ± {np.std(vr2_vals)/len(vr2_vals)**0.5:.4f}")
        print(f"  zero-return %: {np.mean(zero_vals)*100:.1f}%")
        print(f"  flat OHLC %: {np.mean(flat_vals)*100:.1f}%  "
              f"({'real OHLC confirmed' if np.mean(flat_vals) < 0.05 else 'WARNING: still flat — history() may not be used'})")
        print(f"\nStats appended → {stats_path}")
    else:
        print("No pairs successfully profiled.")

    try:
        await api._client.shutdown()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
