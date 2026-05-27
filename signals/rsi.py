"""RSI (Relative Strength Index) signal."""

import pandas as pd
import numpy as np

from signals.base import BaseSignal, SignalResult


class RSISignal(BaseSignal):
    """RSI-based mean reversion signal.

    - CALL if RSI < 30 (oversold)
    - PUT if RSI > 70 (overbought)
    """

    name = "RSI"
    weight = 0.20

    def __init__(self, period: int = 14):
        self.period = period

    def _rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI using pure pandas/numpy."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < self.period:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {self.period}",
                )

            rsi = self._rsi(df["c"], self.period)
            current_rsi = rsi.iloc[-1]

            if pd.isna(current_rsi):
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="RSI calculation failed",
                )

            if current_rsi < 30:
                confidence = min(1.0, (30 - current_rsi) / 20)  # scale 0-30 to 0-1
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=confidence,
                    reason=f"RSI oversold: {current_rsi:.1f}",
                )
            elif current_rsi > 70:
                confidence = min(1.0, (current_rsi - 70) / 20)  # scale 70-100 to 0-1
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=confidence,
                    reason=f"RSI overbought: {current_rsi:.1f}",
                )
            else:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"RSI neutral: {current_rsi:.1f}",
                )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"RSI error: {e}",
            )
