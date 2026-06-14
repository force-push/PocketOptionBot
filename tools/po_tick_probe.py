"""Tick-feed probe for the flip strategy.

Answers three questions before we build a tick-driven flip detector:
  1. Does subscribe_symbol support MULTIPLE concurrent pairs on one WS session?
  2. What's the real per-pair tick rate?
  3. How do tick-built 1s candles compare to the server's history(1) OHLC?

Run with the bot STOPPED (one WS session per SSID).
    .venv/bin/python tools/po_tick_probe.py
"""
from __future__ import annotations

import asyncio
import sys
import time as _time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402
from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync  # noqa: E402

PAIRS = ["EURUSD_otc", "USDJPY_otc", "AUDUSD_otc", "ZARUSD_otc", "DOGE_otc", "TRX-USD_otc"]
SECS = 25


def _price(tick) -> float | None:
    try:
        if isinstance(tick, dict):
            return float(tick.get("close") if tick.get("close") is not None else tick.get("open"))
        return float(tick)
    except Exception:  # noqa: BLE001
        return None


def _ts(tick) -> float | None:
    try:
        return float(tick["timestamp"]) if isinstance(tick, dict) else None
    except Exception:  # noqa: BLE001
        return None


async def consume(api, pair, store, secs):
    try:
        sub = await api.subscribe_symbol(pair)
        t0 = _time.time()
        async for tick in sub:
            store[pair].append((_time.time(), tick))
            if _time.time() - t0 > secs:
                break
        try:
            await api.unsubscribe(pair)
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        store[pair] = [("ERROR", str(e))]


def build_1s(ticks) -> dict:
    """Bucket (recv_ts, tick) pairs into 1s OHLC keyed by int(server ts)."""
    bars = {}
    for _rt, tk in ticks:
        ts, px = _ts(tk), _price(tk)
        if ts is None or px is None:
            continue
        sec = int(ts)
        b = bars.get(sec)
        if b is None:
            bars[sec] = {"o": px, "h": px, "l": px, "c": px, "n": 1}
        else:
            b["h"] = max(b["h"], px); b["l"] = min(b["l"], px); b["c"] = px; b["n"] += 1
    return bars


async def main() -> None:
    api = PocketOptionAsync(settings.po_ssid)
    await api.wait_for_assets(timeout=60.0)
    print("connected; demo =", api.is_demo())

    store: dict = defaultdict(list)
    print(f"\nsubscribing to {len(PAIRS)} pairs CONCURRENTLY for {SECS}s ...")
    await asyncio.gather(*[consume(api, p, store, SECS) for p in PAIRS])

    print(f"\n=== PER-PAIR TICK RATE (concurrent, ~{SECS}s) ===")
    for p in PAIRS:
        ticks = store.get(p, [])
        if ticks and ticks[0][0] == "ERROR":
            print(f"  {p:12s} ERROR: {ticks[0][1][:90]}")
            continue
        n = len(ticks)
        print(f"  {p:12s} n={n:4d}  rate={n / SECS:.2f}/s")

    # Fidelity: tick-built 1s candles vs server history(1) for EURUSD.
    print("\n=== TICK-BUILT 1s CANDLES vs history(1) — EURUSD_otc ===")
    eur = store.get("EURUSD_otc", [])
    if eur and eur[0][0] != "ERROR":
        bars = build_1s(eur)
        ticks_per_bar = [b["n"] for b in bars.values()]
        ranges = [b["h"] - b["l"] for b in bars.values()]
        nonzero = sum(1 for r in ranges if r > 0)
        avg_tpb = sum(ticks_per_bar) / len(ticks_per_bar) if ticks_per_bar else 0
        avg_rng = sum(ranges) / len(ranges) if ranges else 0
        print(f"  tick-built: {len(bars)} bars, avg {avg_tpb:.1f} ticks/bar, "
              f"{nonzero}/{len(bars)} bars have non-zero range, avg range={avg_rng:.6f}")
    try:
        hc = list(await asyncio.wait_for(api.history("EURUSD_otc", 1), timeout=20))
        hr = [float(c["high"]) - float(c["low"]) for c in hc[-60:]]
        nz = sum(1 for r in hr if r > 0)
        print(f"  history(1):  {len(hc)} bars (last 60: {nz} non-zero range), "
              f"avg range(last60)={sum(hr) / len(hr):.6f}")
    except Exception as e:  # noqa: BLE001
        print(f"  history(1) ERROR: {e}")

    try:
        await api.shutdown()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    asyncio.run(main())
