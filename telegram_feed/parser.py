"""Parse Telegram signal messages into TelegramSignal dataclasses.

TODO: Refine regex patterns against real po_broker_bot message samples once
they are available. Current patterns cover common signal formats but may need
adjustment to match the actual bot's formatting.

All patterns are centralized at the top of this module for easy updating.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# Pair-name normalizer: maps human-readable names → API symbols
# (e.g. "EUR/USD OTC" → "EURUSD_otc", "EUR/USD" → "EURUSD")
# Extend this table when new pairs appear in bot messages.
# ──────────────────────────────────────────────────────────────────────────────

_PAIR_MAP: dict[str, str] = {
    # Forex OTC
    "EUR/USD OTC": "EURUSD_otc",
    "EURUSD OTC": "EURUSD_otc",
    "EUR/USD-OTC": "EURUSD_otc",
    "GBP/USD OTC": "GBPUSD_otc",
    "GBPUSD OTC": "GBPUSD_otc",
    "USD/JPY OTC": "USDJPY_otc",
    "USDJPY OTC": "USDJPY_otc",
    "AUD/USD OTC": "AUDUSD_otc",
    "AUDUSD OTC": "AUDUSD_otc",
    "USD/CAD OTC": "USDCAD_otc",
    "USDCAD OTC": "USDCAD_otc",
    "USD/CHF OTC": "USDCHF_otc",
    "USDCHF OTC": "USDCHF_otc",
    "NZD/USD OTC": "NZDUSD_otc",
    "NZDUSD OTC": "NZDUSD_otc",
    "EUR/GBP OTC": "EURGBP_otc",
    "EURGBP OTC": "EURGBP_otc",
    "EUR/JPY OTC": "EURJPY_otc",
    "EURJPY OTC": "EURJPY_otc",
    # Forex non-OTC
    "EUR/USD": "EURUSD",
    "EURUSD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "GBPUSD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "USDJPY": "USDJPY",
    "AUD/USD": "AUDUSD",
    "AUDUSD": "AUDUSD",
    "USD/CAD": "USDCAD",
    "USDCAD": "USDCAD",
    "USD/CHF": "USDCHF",
    "USDCHF": "USDCHF",
    "NZD/USD": "NZDUSD",
    "NZDUSD": "NZDUSD",
    "EUR/GBP": "EURGBP",
    "EURGBP": "EURGBP",
    "EUR/JPY": "EURJPY",
    "EURJPY": "EURJPY",
    # Crypto OTC (common PocketOption assets)
    "BTC/USD OTC": "BTCUSD_otc",
    "BTCUSD OTC": "BTCUSD_otc",
    "ETH/USD OTC": "ETHUSD_otc",
    "ETHUSD OTC": "ETHUSD_otc",
    # Crypto non-OTC
    "BTC/USD": "BTCUSD",
    "BTCUSD": "BTCUSD",
    "ETH/USD": "ETHUSD",
    "ETHUSD": "ETHUSD",
}

# ──────────────────────────────────────────────────────────────────────────────
# Regex patterns (centralized — update here when bot format changes)
# ──────────────────────────────────────────────────────────────────────────────

# Matches pair names like: EUR/USD, EUR/USD OTC, EURUSD, EURUSD OTC, BTC/USD OTC
_RE_PAIR = re.compile(
    r"""
    (?P<pair>
        [A-Z]{3,6}          # base currency letters
        (?:/[A-Z]{3,4})?    # optional /QUOTE
        (?:\s*-?\s*OTC)?    # optional OTC suffix
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Direction patterns: CALL/PUT, BUY/SELL, UP/DOWN, ↑/↓
_RE_DIRECTION = re.compile(
    r"\b(CALL|PUT|BUY|SELL|UP|DOWN)\b|([↑↓])",
    re.IGNORECASE,
)

# Expiry patterns:
#   M1, M5, M15, M30  (minute abbreviations)
#   1 min, 5 min, 1 minute, 5 minutes
#   expiry 60s, expiry: 60 sec, 60 seconds
#   60s, 60sec
_RE_EXPIRY = re.compile(
    r"""
    (?:expiry\s*:?\s*)?         # optional "expiry" label
    (?:
        M(?P<M>\d+)             # M1, M5, M15
        |(?P<min_val>\d+)\s*min(?:ute)?s?    # 1 min, 5 minutes
        |(?P<sec_val>\d+)\s*s(?:ec(?:ond)?s?)?   # 60s, 60sec, 60 seconds
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Win rate patterns: "Win rate: 87%", "WR 87%", "87%", "win rate 0.87"
_RE_WIN_RATE = re.compile(
    r"""
    (?:win\s*rate\s*:?\s*|wr\s*:?\s*)?   # optional label
    (?P<pct>\d{1,3}(?:\.\d+)?)\s*%       # 87% or 87.5%
    |
    (?:win\s*rate\s*:?\s*|wr\s*:?\s*)    # required label for decimal form
    (?P<dec>0\.\d+)                       # 0.87
    """,
    re.VERBOSE | re.IGNORECASE,
)

# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TelegramSignal:
    """Parsed signal from a Telegram bot message."""

    pair: str            # API symbol, e.g. "EURUSD_otc"
    direction: str       # "CALL" or "PUT"
    expiry_seconds: int  # trade expiry in seconds
    stated_win_rate: Optional[float]  # 0.0–1.0 or None if not stated
    raw: str             # original message text
    timestamp: datetime  # UTC parse time


def _normalize_pair(raw_pair: str) -> Optional[str]:
    """Normalize a raw pair string to an API symbol.

    Returns None if the pair cannot be mapped.
    """
    cleaned = raw_pair.strip()

    # Try exact match (case-insensitive)
    upper = cleaned.upper()
    for k, v in _PAIR_MAP.items():
        if k.upper() == upper:
            return v

    # Try removing spaces and re-matching
    compact = re.sub(r"\s+", "", cleaned).upper()
    for k, v in _PAIR_MAP.items():
        if re.sub(r"\s+", "", k).upper() == compact:
            return v

    # Best-effort: if it already looks like a valid API symbol, keep it
    # e.g. "EURUSD_otc" or "EURUSD"
    if re.match(r"^[A-Z]{6}(_otc)?$", upper):
        return upper if "_otc" not in cleaned else cleaned

    return None


def _parse_direction(text: str) -> Optional[str]:
    """Extract direction (CALL/PUT) from text."""
    m = _RE_DIRECTION.search(text)
    if not m:
        return None
    word = (m.group(1) or m.group(2) or "").upper()
    mapping = {
        "CALL": "CALL",
        "BUY": "CALL",
        "UP": "CALL",
        "↑": "CALL",
        "PUT": "PUT",
        "SELL": "PUT",
        "DOWN": "PUT",
        "↓": "PUT",
    }
    return mapping.get(word)


def _parse_expiry(text: str) -> Optional[int]:
    """Extract expiry in seconds from text."""
    for m in _RE_EXPIRY.finditer(text):
        if m.group("M"):
            return int(m.group("M")) * 60
        if m.group("min_val"):
            return int(m.group("min_val")) * 60
        if m.group("sec_val"):
            return int(m.group("sec_val"))
    return None


def _parse_win_rate(text: str) -> Optional[float]:
    """Extract stated win rate as a float 0.0–1.0."""
    for m in _RE_WIN_RATE.finditer(text):
        if m.group("pct"):
            pct = float(m.group("pct"))
            if 0.0 <= pct <= 100.0:
                return pct / 100.0
        if m.group("dec"):
            dec = float(m.group("dec"))
            if 0.0 <= dec <= 1.0:
                return dec
    return None


def _extract_pair(text: str) -> Optional[str]:
    """Try to find and normalize a pair name in the text."""
    # Walk through all _PAIR_MAP keys sorted by length (longest first)
    # to match "EUR/USD OTC" before "EUR/USD"
    upper_text = text.upper()
    for k in sorted(_PAIR_MAP.keys(), key=len, reverse=True):
        if k.upper() in upper_text:
            return _PAIR_MAP[k]

    # Fallback: use regex to find something that looks like a pair
    m = _RE_PAIR.search(text)
    if m:
        return _normalize_pair(m.group("pair"))

    return None


def parse_signal(text: str) -> Optional[TelegramSignal]:
    """Parse a raw Telegram message into a TelegramSignal.

    Returns None for any unparseable or incomplete message — never raises.
    This function is FAIL-SOFT by design.

    TODO: Refine patterns once real po_broker_bot message samples are
    available. The patterns here handle several common signal formats but
    may not cover the exact bot output.
    """
    if not text or not isinstance(text, str):
        return None

    try:
        pair = _extract_pair(text)
        if pair is None:
            return None

        direction = _parse_direction(text)
        if direction is None:
            return None

        expiry = _parse_expiry(text)
        if expiry is None:
            # Default to 60s if not specified but everything else parsed
            expiry = 60

        win_rate = _parse_win_rate(text)

        return TelegramSignal(
            pair=pair,
            direction=direction,
            expiry_seconds=expiry,
            stated_win_rate=win_rate,
            raw=text,
            timestamp=datetime.now(tz=timezone.utc),
        )

    except Exception:
        # Fail-soft: never propagate exceptions out of the parser
        return None
