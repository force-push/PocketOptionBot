"""RSI (Relative Strength Index) signal."""

import pandas as pd
import numpy as np

from signals.base import BaseSignal, SignalResult


class RSISignal(BaseSignal):
    """RSI-based mean reversion signal.

    Fires when RSI is in extreme territory (oversold → CALL, overbought → PUT).
    Confidence scales linearly with distance from the threshold so a deeply
    oversold RSI of 15 is weighted higher than one just at 29.

    Thresholds are configurable (RSI_OVERSOLD / RSI_OVERBOUGHT in .env) so
    they can be tightened or loosened based on observed pair volatility without
    a code change.  Tighter thresholds (e.g. 20/80) fire less often but with
    higher-quality entries; looser ones (e.g. 35/65) fire more often at lower
    confidence.
    """

    name = "RSI"
    weight = 0.20

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

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

            if current_rsi < self.oversold:
                confidence = min(1.0, (self.oversold - current_rsi) / self.oversold)
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=confidence,
                    reason=f"RSI oversold: {current_rsi:.1f} (threshold {self.oversold})",
                )
            elif current_rsi > self.overbought:
                confidence = min(1.0, (current_rsi - self.overbought) / (100 - self.overbought))
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=confidence,
                    reason=f"RSI overbought: {current_rsi:.1f} (threshold {self.overbought})",
                )
            else:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"RSI neutral: {current_rsi:.1f} (range {self.oversold}–{self.overbought})",
                )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"RSI error: {e}",
            )
