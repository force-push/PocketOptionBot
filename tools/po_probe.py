"""PocketOption data-surface discovery probe.

Catalogues everything the WS API exposes beyond what the bot uses today
(snapshot candles, payout, balance). Four phases:

  1. ASSETS    — full schema of active_assets() entries (hunting for sentiment/
                 trend/prediction fields we ignore)
  2. HISTORY   — depth limits: get_candles vs history vs get_candles_advanced
                 paging (can we walk past the 150-candle cap?)
  3. TICKS     — subscribe_symbol raw tick stream: rate, fields, and whether
                 timed subscriptions yield REAL OHLC (the snapshot endpoint
                 returns flat o==h==l==c)
  4. CHANNELS  — catch-all raw WS listener: catalogue every message type the
                 server pushes (hunting for traders'-sentiment / "majority
                 opinion" data = per-pair crowd predictions)

Usage (stop the bot first — one WS session per SSID):
    .venv/bin/python tools/po_probe.py [--asset EURUSD_otc] [--secs 30]
Writes a JSON report to data/po_probe_report.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time as _time
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402

from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync  # noqa: E402
from BinaryOptionsToolsV2.validator import Validator  # noqa: E402

REPORT: dict = {}


def section(title: str) -> None:
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


async def probe_assets(api) -> None:
    section("1. ASSET METADATA (active_assets)")
    assets = await api.active_assets()
    REPORT["asset_count"] = len(assets)
    if not assets:
        print("no assets returned")
        return
    keys = Counter()
    for a in assets:
        keys.update(a.keys())
    print(f"{len(assets)} assets; union of keys across all entries:")
    for k, n in keys.most_common():
        sample = next((a[k] for a in assets if k in a and a[k] is not None), None)
        print(f"  {k:<22} present={n:<4} sample={str(sample)[:60]}")
    REPORT["asset_keys"] = dict(keys)
    REPORT["asset_sample"] = assets[0]
    print("\nfull first entry:")
    print(json.dumps(assets[0], indent=1, default=str)[:1200])


async def probe_history(api, asset: str) -> None:
    section(f"2. HISTORY DEPTH ({asset})")
    out = {}
    for name, coro in (
        ("get_candles(p=5,offset=7500)", api.get_candles(asset, 5, 7500)),
        ("history(p=5)", api.history(asset, 5)),
    ):
        try:
            c = await asyncio.wait_for(coro, timeout=30)
            span = (c[-1]["timestamp"] - c[0]["timestamp"]) if len(c) > 1 else 0
            out[name] = {"n": len(c), "span_s": span,
                         "flat_ohlc": all(x["open"] == x["high"] == x["low"] == x["close"] for x in c[:50])}
            print(f"  {name:<32} n={len(c):<5} span={span}s flat_ohlc={out[name]['flat_ohlc']}")
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": str(e)[:80]}
            print(f"  {name:<32} ERROR {e}")

    # paging: walk get_candles_advanced backwards 3 pages
    try:
        now = await api.get_server_time()
        if now < 1_000_000_000:  # offset, not epoch — fall back to wall clock
            now = int(_time.time())
        total, pages, t = 0, [], now
        for i in range(3):
            c = await asyncio.wait_for(api.get_candles_advanced(asset, 5, 750, t), timeout=30)
            if not c:
                break
            pages.append((len(c), c[0]["timestamp"], c[-1]["timestamp"]))
            total += len(c)
            t = int(c[0]["timestamp"]) - 5
        print(f"  get_candles_advanced paging: {len(pages)} pages, {total} candles total")
        for i, (n, t0, t1) in enumerate(pages):
            print(f"    page {i}: n={n}  {t0} → {t1}")
        out["advanced_paging"] = {"pages": len(pages), "total": total,
                                  "works": len(pages) > 1 and total > 200}
    except Exception as e:  # noqa: BLE001
        out["advanced_paging"] = {"error": str(e)[:80]}
        print(f"  get_candles_advanced paging ERROR: {e}")
    REPORT["history"] = out


async def probe_ticks(api, asset: str, secs: int) -> None:
    section(f"3. RAW TICK STREAM ({asset}, {secs}s)")
    out = {}
    try:
        sub = await api.subscribe_symbol(asset)
        ticks, t0 = [], _time.time()
        async for tick in sub:
            ticks.append(tick)
            if _time.time() - t0 > secs or len(ticks) >= 500:
                break
        try:
            await api.unsubscribe(asset)
        except Exception:  # noqa: BLE001
            pass
        rate = len(ticks) / max(_time.time() - t0, 1)
        print(f"  {len(ticks)} ticks in {_time.time()-t0:.0f}s  ({rate:.1f}/s)")
        if ticks:
            print(f"  tick fields: {list(ticks[0].keys()) if isinstance(ticks[0], dict) else type(ticks[0])}")
            print(f"  first: {str(ticks[0])[:160]}")
            print(f"  last:  {str(ticks[-1])[:160]}")
        out = {"n": len(ticks), "rate_per_s": round(rate, 2),
               "fields": list(ticks[0].keys()) if ticks and isinstance(ticks[0], dict) else None,
               "sample": ticks[0] if ticks else None}
    except Exception as e:  # noqa: BLE001
        out = {"error": str(e)[:120]}
        print(f"  subscribe_symbol ERROR: {e}")
    REPORT["ticks"] = out

    # timed candles: do we get REAL OHLC (non-flat)?
    try:
        sub = await api.subscribe_symbol_timed(asset, timedelta(seconds=5))
        candles, t0 = [], _time.time()
        async for c in sub:
            candles.append(c)
            if len(candles) >= 4 or _time.time() - t0 > 30:
                break
        try:
            await api.unsubscribe(asset)
        except Exception:  # noqa: BLE001
            pass
        flat = all(c.get("open") == c.get("high") == c.get("low") == c.get("close") for c in candles) if candles else None
        print(f"  timed 5s candles: n={len(candles)}  flat_ohlc={flat}")
        if candles:
            print(f"  sample: {str(candles[0])[:200]}")
        REPORT["timed_candles"] = {"n": len(candles), "flat_ohlc": flat,
                                   "sample": candles[0] if candles else None}
    except Exception as e:  # noqa: BLE001
        REPORT["timed_candles"] = {"error": str(e)[:120]}
        print(f"  subscribe_symbol_timed ERROR: {e}")


async def probe_channels(api, asset: str, secs: int) -> None:
    section(f"4. RAW WS CHANNEL CATALOGUE ({secs}s listen)")
    counts: Counter = Counter()
    samples: dict = {}

    def classify(msg: str) -> str:
        m = re.match(r'^\d+(\["?([A-Za-z]+)"?)?', msg or "")
        if msg.startswith('42["'):
            try:
                return json.loads(msg[2:])[0]
            except Exception:  # noqa: BLE001
                return msg[:24]
        if msg.startswith("{"):
            try:
                return "json:" + ",".join(sorted(json.loads(msg).keys())[:4])
            except Exception:  # noqa: BLE001
                return "json:?"
        if msg and msg[0].isdigit():
            return f"sio:{m.group(0)[:12]}" if m else msg[:12]
        return msg[:24]

    try:
        handler = await api.create_raw_handler(Validator.custom(lambda m: True))
        # nudge the server: ask for sentiment-ish channels some clients use
        for probe_msg in (
            f'42["changeSymbol",{{"asset":"{asset}","period":1}}]',
            '42["favorite/get"]',
        ):
            try:
                await api.send_raw_message(probe_msg)
            except Exception:  # noqa: BLE001
                pass

        t0 = _time.time()
        while _time.time() - t0 < secs:
            try:
                msg = await asyncio.wait_for(handler.wait_next(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            key = classify(str(msg))
            counts[key] += 1
            if key not in samples:
                samples[key] = str(msg)[:220]
    except Exception as e:  # noqa: BLE001
        print(f"  raw handler ERROR ({e}); channel catalogue unavailable")
        REPORT["channels"] = {"error": str(e)[:120]}
        return

    print(f"  {sum(counts.values())} messages, {len(counts)} distinct types:")
    for key, n in counts.most_common(25):
        print(f"  {n:>5}×  {key}")
        print(f"         {samples[key][:160]}")
    REPORT["channels"] = {"counts": dict(counts), "samples": samples}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="EURUSD_otc")
    ap.add_argument("--secs", type=int, default=25)
    args = ap.parse_args()

    api = PocketOptionAsync(settings.po_ssid)
    await api.wait_for_assets(timeout=60.0)
    print("connected; demo =", api.is_demo(), "| server_time =", await api.get_server_time())

    await probe_assets(api)
    await probe_history(api, args.asset)
    await probe_ticks(api, args.asset, args.secs)
    await probe_channels(api, args.asset, args.secs)

    out = Path("data/po_probe_report.json")
    out.write_text(json.dumps(REPORT, indent=1, default=str))
    print(f"\nreport → {out}")
    try:
        await api.shutdown()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    asyncio.run(main())
