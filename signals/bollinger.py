"""Bollinger Bands signal."""

import pandas as pd

from signals.base import BaseSignal, SignalResult


class BollingerSignal(BaseSignal):
    """Bollinger Bands mean reversion signal.

    - CALL if price touches/breaks lower band + shows reversal
    - PUT if price touches/breaks upper band + shows reversal
    """

    name = "Bollinger"
    weight = 0.20

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        self.period = period
        self.std_dev = std_dev

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < self.period:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {self.period}",
                )

            sma = df["c"].rolling(window=self.period).mean()
            std = df["c"].rolling(window=self.period).std()
            upper = sma + self.std_dev * std
            lower = sma - self.std_dev * std
            price = df["c"].iloc[-1]

            if sma.isna().iloc[-1] or std.isna().iloc[-1]:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="Bollinger Bands calculation failed",
                )

            upper_val = upper.iloc[-1]
            lower_val = lower.iloc[-1]

            # Check for reversal
            if price <= lower_val:
                confidence = min(1.0, (lower_val - price) / (std.iloc[-1] or 0.0001))
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=confidence,
                    reason=f"Price below lower band: {price:.5f} < {lower_val:.5f}",
                )
            elif price >= upper_val:
                confidence = min(1.0, (price - upper_val) / (std.iloc[-1] or 0.0001))
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=confidence,
                    reason=f"Price above upper band: {price:.5f} > {upper_val:.5f}",
                )
            else:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Price within bands: {lower_val:.5f} < {price:.5f} < {upper_val:.5f}",
                )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"Bollinger error: {e}",
            )
