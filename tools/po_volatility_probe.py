"""Per-pair volatility vs flip-strategy win-rate.

Hypothesis: the poor-performing allowlist pairs are too *quiet* at 1s resolution
(many flat bars / low ATR), so the indicators fire on noise → coin-flip outcomes.
Measures ATR(14)/price (bps), stdev of 1s log-returns (bps), and % flat 1s bars
per allowlist pair, then joins each pair's resolved 5s flip win-rate from the DB.

Run with the bot STOPPED.
    .venv/bin/python tools/po_volatility_probe.py
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402
from data import decisions_store as store  # noqa: E402
from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync  # noqa: E402


def _wr_by_pair() -> dict:
    rows = store.all_records(settings.decisions_db_path)
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        if r.get("decision") != "TRADE" or r.get("expiry_seconds") != 5 or r.get("shadow"):
            continue
        o = (r.get("outcome") or "").lower()
        if o == "win":
            agg[r["pair_api"]][0] += 1
        elif o == "loss":
            agg[r["pair_api"]][1] += 1
    return agg


def _vol(candles) -> dict:
    c = np.array([float(x["close"]) for x in candles], dtype=float)
    h = np.array([float(x["high"]) for x in candles], dtype=float)
    lo = np.array([float(x["low"]) for x in candles], dtype=float)
    if len(c) < 30:
        return {}
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - lo, np.abs(h - prev_c), np.abs(lo - prev_c)])
    atr = tr[-100:].mean()
    price = c[-1]
    ret = np.diff(np.log(c))
    ret = ret[np.isfinite(ret)]
    flat_pct = float((h == lo).mean()) * 100
    return {
        "atr_bps": atr / price * 1e4,          # ATR as basis points of price
        "ret_std_bps": ret.std() * 1e4,        # 1s log-return stdev, bps
        "flat_pct": flat_pct,                  # % of 1s bars with no high-low range
        "n": len(c),
    }


async def main() -> None:
    api = PocketOptionAsync(settings.po_ssid)
    await api.wait_for_assets(timeout=60.0)
    print("connected; demo =", api.is_demo())
    wr = _wr_by_pair()

    rows = []
    for pair in settings.allowed_pairs:
        try:
            candles = list(await asyncio.wait_for(api.history(pair, 1), timeout=20))
            v = _vol(candles)
            if not v:
                continue
            w, l = wr.get(pair, [0, 0])
            n = w + l
            rows.append((pair, v, (100 * w / n if n else None), n))
        except Exception as e:  # noqa: BLE001
            print(f"  {pair}: ERROR {e}")

    rows.sort(key=lambda r: (r[2] if r[2] is not None else -1), reverse=True)
    print(f"\n{'PAIR':12s} {'WR%':>5} {'n':>4}  {'ATR_bps':>8} {'ret_std_bps':>11} {'flat%':>6}")
    for pair, v, w, n in rows:
        wrs = f"{w:.0f}" if w is not None else "—"
        print(f"{pair:12s} {wrs:>5} {n:>4}  {v['atr_bps']:8.2f} {v['ret_std_bps']:11.2f} {v['flat_pct']:6.1f}")

    try:
        await api.shutdown()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    asyncio.run(main())
