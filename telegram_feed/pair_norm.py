"""Normalize a displayed pair label to a PocketOption API symbol.

Try the curated table (telegram_feed.parser._PAIR_MAP) first; otherwise apply
the generic rule  XX…XXXXX/XX…XXXXX [OTC] -> XXXXXX[_otc], where each code is
2–5 letters. Handles both "ETH/USD OTC" and "ETH/USDotc" (no space) formats.
"""
from __future__ import annotations

import re

from telegram_feed.parser import _PAIR_MAP

# Match pairs like "ETH/USD", "ETH/USD OTC", "ETH/USDotc", "ETH/USD OTC"
# Group 1: base (e.g. ETH), Group 2: quote (e.g. USD), Group 3: OTC marker (optional, with/without space)
_GENERIC_RE = re.compile(r"\b([A-Z]{2,5})\s*/\s*([A-Z]{2,5})(otc|\s+OTC)?\b", re.IGNORECASE)


def normalize_pair(label: str) -> str | None:
    if not label:
        return None
    key = label.strip().upper()
    if key in _PAIR_MAP:
        return _PAIR_MAP[key]
    m = _GENERIC_RE.search(key)
    if not m:
        return None
    base, quote, otc = m.group(1).upper(), m.group(2).upper(), m.group(3)
    symbol = f"{base}{quote}"
    return f"{symbol}_otc" if otc else symbol
