# telegram_feed/prediction_parser.py
"""Parse a po_broker_bot 'Bot Prediction' message into pairs + win rates."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Match pair: Win rate XX% with flexible whitespace.
# Handles: "AUD/USD OTC: Win rate ≈78%", "AUD/USD OTC : Win rate ≈ 78%"
_LINE_RE = re.compile(
    r"([A-Z]{2,5}/[A-Z]{2,5}(?:\s+OTC)?)\s*:\s*(?:Win\s+)?rate\s*[≈~]?\s*(\d+)\s*%",
    re.IGNORECASE
)
_TOP_RE = re.compile(r"🏆")


@dataclass(frozen=True)
class PairPrediction:
    pair_raw: str
    win_rate: float  # 0.0–1.0
    is_top: bool


@dataclass(frozen=True)
class PredictionScreen:
    pairs: tuple[PairPrediction, ...]

    def top_pick(self) -> PairPrediction | None:
        for p in self.pairs:
            if p.is_top:
                return p
        return self.pairs[0] if self.pairs else None


def parse_prediction(text: str) -> PredictionScreen | None:
    if not text or "bot prediction" not in text.lower():
        return None

    from utils.logger import log
    out: list[PairPrediction] = []
    for line in text.splitlines():
        m = _LINE_RE.search(line)
        if not m:
            continue
        out.append(PairPrediction(
            pair_raw=m.group(1).strip().upper().replace("  ", " "),
            win_rate=float(m.group(2)) / 100.0,
            is_top=bool(_TOP_RE.search(line)),
        ))

    if not out:
        # No pairs parsed; log the raw text for debugging
        log.warning("parse_prediction: got 'bot prediction' marker but matched zero pairs. Text:\n{}", text)

    return PredictionScreen(pairs=tuple(out)) if out else None
