"""Candlestick pattern recognition signal."""

import pandas as pd

from signals.base import BaseSignal, SignalResult


class CandlePatternSignal(BaseSignal):
    """Recognize candlestick patterns."""

    name = "CandlePattern"
    weight = 0.25

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < 2:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="Need at least 2 candles",
                )

            # Get last 3 candles
            candles = df.iloc[-3:].to_dict("records")
            current = candles[-1]
            prev = candles[-2] if len(candles) > 1 else None

            # Bullish Engulfing
            if prev and current["o"] < prev["c"] and current["c"] > prev["o"]:
                if current["o"] < prev["l"]:
                    return SignalResult(
                        name=self.name,
                        direction="CALL",
                        confidence=0.8,
                        reason="Bullish Engulfing",
                    )

            # Bearish Engulfing
            if prev and current["o"] > prev["c"] and current["c"] < prev["o"]:
                if current["o"] > prev["h"]:
                    return SignalResult(
                        name=self.name,
                        direction="PUT",
                        confidence=0.8,
                        reason="Bearish Engulfing",
                    )

            # Hammer (small body, long lower wick)
            body = abs(current["c"] - current["o"])
            wick_low = current["o"] - current["l"] if current["o"] < current["c"] else current["c"] - current["l"]
            if wick_low > body * 2:
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=0.7,
                    reason="Hammer pattern",
                )

            # Shooting Star (small body, long upper wick)
            wick_high = current["h"] - current["o"] if current["o"] > current["c"] else current["h"] - current["c"]
            if wick_high > body * 2:
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=0.7,
                    reason="Shooting Star pattern",
                )

            # Doji (open ≈ close)
            if body < (current["h"] - current["l"]) * 0.1:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.3,
                    reason="Doji (indecision)",
                )

            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason="No clear pattern",
            )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"Error: {str(e)}",
            )
