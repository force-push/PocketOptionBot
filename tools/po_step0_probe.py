"""Step-0 probe for the SuperTrend-flip build.

Verifies (a) whether the API serves real 1-second OHLC candles (non-flat wicks),
and (b) the exact API symbols + live payouts for the curated allowlist (FX +
crypto). Run with the bot STOPPED — one WS session per SSID.

    .venv/bin/python tools/po_step0_probe.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402
from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync  # noqa: E402

# Display-name fragments we want to locate exact symbols for.
WANT = [
    "EUR/USD", "USD/JPY", "AED/CNY", "EUR/CHF", "USD/MXN", "ZAR/USD",
    "GBP/USD", "AUD/USD", "Dogecoin", "Ethereum", "TRON", "Doge", "ETH", "TRX",
]


def _flat(candles) -> bool:
    return all(
        c.get("open") == c.get("high") == c.get("low") == c.get("close")
        for c in candles[:50]
    ) if candles else None


async def _test_period(api, pair: str, period: int) -> None:
    try:
        c = list(await asyncio.wait_for(api.history(pair, period), timeout=20))
        span = (c[-1]["timestamp"] - c[0]["timestamp"]) if len(c) > 1 else 0
        print(f"  history({pair}, {period}): n={len(c)} span={span}s "
              f"flat_ohlc={_flat(c)}")
        if c:
            print(f"    last candle: {c[-1]}")
    except Exception as e:  # noqa: BLE001
        print(f"  history({pair}, {period}) ERROR: {e}")


async def main() -> None:
    api = PocketOptionAsync(settings.po_ssid)
    await api.wait_for_assets(timeout=60.0)
    print("connected; demo =", api.is_demo())

    assets = await api.active_assets()
    active = [a for a in assets if a.get("is_active")]
    active.sort(key=lambda a: -(a.get("payout") or 0))

    print(f"\n=== ACTIVE ASSETS @ payout (n={len(active)}) — symbol | name | type | payout ===")
    for a in active:
        print(f"  {str(a.get('symbol')):16s} {str(a.get('name'))[:24]:24s} "
              f"{str(a.get('asset_type'))[:11]:11s} {a.get('payout')}")

    print("\n=== ALLOWLIST MATCHES (symbol | name | payout) ===")
    for a in active:
        name = str(a.get("name") or "")
        if any(w.lower() in name.lower() for w in WANT):
            print(f"  {str(a.get('symbol')):16s} {name[:26]:26s} {a.get('payout')}%")

    print("\n=== 1-SECOND OHLC FEED TEST ===")
    for pair in ("EURUSD_otc", "USDJPY_otc"):
        await _test_period(api, pair, 1)
    print("\n=== 5-SECOND baseline (for comparison) ===")
    await _test_period(api, "EURUSD_otc", 5)

    try:
        await api.shutdown()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    asyncio.run(main())
