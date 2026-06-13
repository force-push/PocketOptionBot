"""One-off: dump the distinct raw WS message shapes after changeSymbol.

Connects, subscribes to a few assets (period:1), and for ~20s per asset records
every raw message, bucketed by a normalised "shape" (digits→#, collapse), so we
can see what actually arrives — and whether the traders'-choice [["SYM",int]]
frame is present in any form. Read-only diagnostic; run with the bot stopped.

    .venv/bin/python tools/po_raw_shapes.py
"""
from __future__ import annotations

import asyncio
import re
import sys
import time as _time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402
from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync  # noqa: E402
from BinaryOptionsToolsV2.validator import Validator  # noqa: E402

ASSETS = ["EURUSD_otc", "GBPUSD_otc", "BTCUSD_otc"]
SECS = 20
# Anything that looks like [["SYM",<1-3 digit int>]] in any whitespace variant
SENT_RE = re.compile(r'\[\s*\[\s*"[^"]+"\s*,\s*\d{1,3}\s*\]\s*\]')


def shape(msg: str) -> str:
    s = msg[:70]
    s = re.sub(r'\d', '#', s)
    return s


async def main() -> None:
    api = PocketOptionAsync(settings.po_ssid)
    await api.wait_for_assets(timeout=60.0)
    print(f"connected (demo={api.is_demo()})")
    handler = await api.create_raw_handler(Validator.custom(lambda m: True))

    shapes: Counter = Counter()
    sentiment_hits: list[str] = []
    short_frames: Counter = Counter()  # frames < 40 chars, verbatim

    for asset in ASSETS:
        await api.send_raw_message(f'42["changeSymbol",{{"asset":"{asset}","period":1}}]')
        t0 = _time.time()
        while _time.time() - t0 < SECS:
            try:
                msg = await asyncio.wait_for(handler.wait_next(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            s = str(msg)
            shapes[shape(s)] += 1
            if len(s) < 40:
                short_frames[s] += 1
            if SENT_RE.search(s):
                if len(sentiment_hits) < 20:
                    sentiment_hits.append(s[:80])
        print(f"  done {asset}")

    print("\n=== TOP 25 MESSAGE SHAPES (digits→#) ===")
    for sh, n in shapes.most_common(25):
        print(f"  {n:6d}  {sh!r}")

    print(f"\n=== SHORT FRAMES (<40 chars), top 25 ===")
    for fr, n in short_frames.most_common(25):
        print(f"  {n:6d}  {fr!r}")

    print(f"\n=== SENTIMENT-LIKE [[\"SYM\",int]] HITS: {len(sentiment_hits)} ===")
    for h in sentiment_hits:
        print(f"  {h!r}")

    try:
        await api.shutdown()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
