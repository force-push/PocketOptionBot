"""Parse the post-pair-selection direction/stake screen caption."""
from __future__ import annotations

import re
from dataclasses import dataclass

_DIR_RE = re.compile(r"direction\s*[:\-]?\s*[^A-Za-z]*(buy|sell)", re.IGNORECASE | re.DOTALL)
_BULL_RE = re.compile(r"bullish", re.IGNORECASE)
_BEAR_RE = re.compile(r"bearish", re.IGNORECASE)
_IND_RE = re.compile(r"(MACD|RSI|EMA|Bollinger|momentum|overbought|oversold)", re.IGNORECASE)


@dataclass(frozen=True)
class DirectionScreen:
    direction: str          # "CALL" or "PUT"
    setup: str              # "bullish" | "bearish" | "unknown"
    indicators_raw: str     # the prose line naming the bot's indicators


def parse_direction_screen(text: str) -> DirectionScreen | None:
    if not text:
        return None
    m = _DIR_RE.search(text)
    if not m:
        return None
    word = m.group(1).lower()
    direction = "CALL" if word == "buy" else "PUT"
    setup = "bullish" if _BULL_RE.search(text) else "bearish" if _BEAR_RE.search(text) else "unknown"
    ind_lines = [ln.strip() for ln in text.splitlines()
                 if _IND_RE.search(ln) and "direction" not in ln.lower()]
    return DirectionScreen(direction=direction, setup=setup,
                           indicators_raw=" ".join(ind_lines).strip())
