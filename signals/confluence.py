"""Signal aggregator and confluence scoring engine."""

from dataclasses import dataclass

import pandas as pd

from signals.base import BaseSignal, SignalResult
from utils.logger import log


@dataclass(frozen=True)
class ConfluenceResult:
    direction: str | None  # CALL, PUT, or None
    score: float  # 0.0 to 1.0
    breakdown: dict  # Signal name -> (direction, confidence)
    reason: str


class ConfluenceEngine:
    """Combine multiple signals into a single trading decision.

    Two independent gates must both pass for a direction to be returned:
      1. Agreement gate  — at least ``min_agreement`` signals must agree on
         the same non-None direction (configurable via MIN_SIGNAL_AGREEMENT).
      2. Score floor     — the weighted confidence sum for the winning side must
         reach ``min_score`` (configurable via MIN_CONFLUENCE_SCORE in
         strategy/decision.py / settings).

    Keeping these gates separate allows independent tuning: you can require
    fewer signals to agree (gate 1) while maintaining a score floor (gate 2),
    or vice versa.
    """

    def __init__(self, signals: list[BaseSignal], min_agreement: int = 3):
        self.signals = signals
        self.min_agreement = min_agreement
        # Normalize weights
        total = sum(s.weight for s in signals)
        self.weights = {s.name: s.weight / total for s in signals} if total > 0 else {}

    async def score(self, df: pd.DataFrame) -> ConfluenceResult:
        """Evaluate all signals and return confluence result."""
        if df.empty:
            return ConfluenceResult(
                direction=None,
                score=0.0,
                breakdown={},
                reason="Empty DataFrame",
            )

        results: dict[str, SignalResult] = {}
        call_score = 0.0
        put_score = 0.0

        # Evaluate each signal
        for signal in self.signals:
            try:
                result = await signal.evaluate(df)
                results[signal.name] = result

                if result.direction == "CALL":
                    call_score += result.confidence * self.weights.get(signal.name, 0.0)
                elif result.direction == "PUT":
                    put_score += result.confidence * self.weights.get(signal.name, 0.0)

            except Exception as e:
                log.warning(f"Signal {signal.name} failed: {e}")
                results[signal.name] = SignalResult(
                    name=signal.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Exception: {str(e)}",
                )

        # Determine direction by weighted confidence score
        if call_score > put_score:
            direction = "CALL"
            final_score = call_score
        elif put_score > call_score:
            direction = "PUT"
            final_score = put_score
        else:
            return ConfluenceResult(
                direction=None,
                score=0.0,
                breakdown={r.name: (r.direction, r.confidence, r.reason) for r in results.values()},
                reason="Conflicting signals (CALL ≈ PUT)",
            )

        # Require ≥3 signals to agree on the winning direction.
        # Previously this counted CALL + PUT together, which allowed trades to
        # fire when e.g. 2 signals said CALL and 1 said PUT — not "agreement".
        agreeing_count = sum(1 for r in results.values() if r.direction == direction)
        breakdown = {r.name: (r.direction, r.confidence, r.reason) for r in results.values()}
        if agreeing_count < self.min_agreement:
            return ConfluenceResult(
                direction=None,
                score=0.0,
                breakdown=breakdown,
                reason=(
                    f"Only {agreeing_count} signal(s) agree on {direction} "
                    f"(need ≥{self.min_agreement} on the same side)"
                ),
            )

        return ConfluenceResult(
            direction=direction,
            score=final_score,
            breakdown=breakdown,
            reason=f"{direction} confluence={final_score:.2f}",
        )
