"""EMA Crossover signal."""

import pandas as pd

from signals.base import BaseSignal, SignalResult


class EMASignal(BaseSignal):
    """EMA crossover signal.

    - CALL on golden cross (fast EMA > slow EMA)
    - PUT on death cross (fast EMA < slow EMA)
    """

    name = "EMA_Cross"
    weight = 0.15

    def __init__(self, fast: int = 9, slow: int = 21):
        self.fast = fast
        self.slow = slow

    def _ema(self, series: pd.Series, span: int) -> pd.Series:
        """Calculate EMA using pandas ewm."""
        return series.ewm(span=span, adjust=False).mean()

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < self.slow:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {self.slow}",
                )

            fast_ema = self._ema(df["c"], self.fast)
            slow_ema = self._ema(df["c"], self.slow)

            if fast_ema is None or slow_ema is None:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="EMA calculation failed",
                )

            fast_val = fast_ema.iloc[-1]
            slow_val = slow_ema.iloc[-1]

            if pd.isna(fast_val) or pd.isna(slow_val):
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="EMA NaN values",
                )

            # Detect crossovers
            prev_fast = fast_ema.iloc[-2] if len(fast_ema) > 1 else fast_val
            prev_slow = slow_ema.iloc[-2] if len(slow_ema) > 1 else slow_val

            if fast_val > slow_val and prev_fast <= prev_slow:
                confidence = min(1.0, abs(fast_val - slow_val) / (slow_val or 0.0001) * 100)
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=confidence,
                    reason=f"EMA golden cross: {fast_val:.5f} > {slow_val:.5f}",
                )
            elif fast_val < slow_val and prev_fast >= prev_slow:
                confidence = min(1.0, abs(fast_val - slow_val) / (slow_val or 0.0001) * 100)
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=confidence,
                    reason=f"EMA death cross: {fast_val:.5f} < {slow_val:.5f}",
                )
            else:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"EMA no cross: fast={fast_val:.5f}, slow={slow_val:.5f}",
                )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"EMA error: {e}",
            )
