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
    """Combine multiple signals into a single trading decision."""

    def __init__(self, signals: list[BaseSignal]):
        self.signals = signals
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

        # Determine final direction
        agreeing_signals = sum(
            1 for r in results.values() if r.direction in ("CALL", "PUT")
        )

        if agreeing_signals < 3:
            return ConfluenceResult(
                direction=None,
                score=0.0,
                breakdown={
                    r.name: (r.direction, r.confidence) for r in results.values()
                },
                reason=f"Only {agreeing_signals} signals agree (need ≥3)",
            )

        if call_score > put_score:
            final_score = call_score
            direction = "CALL"
        elif put_score > call_score:
            final_score = put_score
            direction = "PUT"
        else:
            return ConfluenceResult(
                direction=None,
                score=0.0,
                breakdown={
                    r.name: (r.direction, r.confidence) for r in results.values()
                },
                reason="Conflicting signals (CALL ≈ PUT)",
            )

        breakdown = {r.name: (r.direction, r.confidence) for r in results.values()}

        # Log the full breakdown
        log.debug(
            f"Confluence Score: {direction}={final_score:.2f} | {breakdown}"
        )

        return ConfluenceResult(
            direction=direction,
            score=final_score,
            breakdown=breakdown,
            reason=f"{direction} confluence={final_score:.2f}",
        )
