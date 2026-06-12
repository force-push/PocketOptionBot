"""Verify the suspected traders'-sentiment channel on PocketOption's WS.

The discovery probe (tools/po_probe.py) saw messages like [["EURUSD_otc",59]]
— single integers in the 0-100 range attached to an asset, arriving on the
live stream after changeSymbol. Hypothesis: this is the platform's traders'
sentiment widget (% of traders positioned CALL) — i.e. per-pair crowd
predictions, an orthogonal data source the bot has never used.

This tool cycles through N assets, collects those integer messages, and
reports per-asset: count, range, drift over time. Verification criteria:
  - values stay within 0-100
  - values differ per asset
  - values drift gradually (a live percentage, not a constant or a counter)

Usage (stop the bot first — one WS session per SSID):
    .venv/bin/python tools/po_sentiment_probe.py --assets EURUSD_otc,BTCUSD_otc,#AAPL_otc --secs 25
Appends raw observations to data/sentiment_probe.jsonl.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time as _time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402

from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync  # noqa: E402
from BinaryOptionsToolsV2.validator import Validator  # noqa: E402

# Matches [["SYMBOL",<int>]] with no decimal point (price ticks carry floats)
INT_MSG = re.compile(r'^\[\["([^"]+)",(\d{1,3})\]\]$')


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="EURUSD_otc,BTCUSD_otc,#AAPL_otc,USDJPY_otc")
    ap.add_argument("--secs", type=int, default=25, help="listen seconds per asset")
    args = ap.parse_args()
    assets = [a.strip() for a in args.assets.split(",") if a.strip()]

    api = PocketOptionAsync(settings.po_ssid)
    await api.wait_for_assets(timeout=60.0)
    print(f"connected (demo={api.is_demo()}); probing {len(assets)} assets, {args.secs}s each")

    handler = await api.create_raw_handler(Validator.custom(lambda m: True))
    obs: dict[str, list] = defaultdict(list)
    out_path = Path("data/sentiment_probe.jsonl")

    with out_path.open("a", encoding="utf-8") as fh:
        for asset in assets:
            await api.send_raw_message(f'42["changeSymbol",{{"asset":"{asset}","period":1}}]')
            t0 = _time.time()
            n_msgs = 0
            while _time.time() - t0 < args.secs:
                try:
                    msg = await asyncio.wait_for(handler.wait_next(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue
                n_msgs += 1
                m = INT_MSG.match(str(msg).strip())
                if m:
                    sym, val = m.group(1), int(m.group(2))
                    ts = _time.time()
                    obs[sym].append((ts, val))
                    fh.write(json.dumps({"ts": ts, "symbol": sym, "value": val}) + "\n")
            got = len([1 for s, v in obs.items() if s == asset])
            print(f"  {asset:<14} listened {args.secs}s  ({n_msgs} msgs total this window)")

    print(f"\n{'ASSET':<16} {'n':>3}  {'min':>4} {'max':>4}  values (time order)")
    verdict_ok = 0
    for sym, vals in sorted(obs.items()):
        seq = [v for _, v in vals]
        in_range = all(0 <= v <= 100 for v in seq)
        drifts = len(set(seq)) > 1
        flag = "✓ sentiment-like" if in_range and drifts else ("~ constant" if in_range else "✗ out of range")
        if in_range and drifts:
            verdict_ok += 1
        print(f"{sym:<16} {len(seq):>3}  {min(seq):>4} {max(seq):>4}  {seq[:14]}  {flag}")

    print(f"\nVERDICT: {verdict_ok}/{len(obs)} assets produced drifting 0-100 integers "
          f"({'CONSISTENT WITH TRADER SENTIMENT' if verdict_ok >= 2 else 'inconclusive — need more data'})")
    print(f"raw observations appended → {out_path}")
    try:
        await api.shutdown()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    asyncio.run(main())
