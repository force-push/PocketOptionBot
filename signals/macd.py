"""MACD (Moving Average Convergence Divergence) signal."""

import pandas as pd

from signals.base import BaseSignal, SignalResult


class MACDSignal(BaseSignal):
    """MACD crossover signal.

    - CALL on golden cross (MACD > signal line, accelerating)
    - PUT on death cross (MACD < signal line, accelerating)
    """

    name = "MACD"
    weight = 0.20

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal

    @staticmethod
    def _ema(prices: pd.Series, span: int) -> pd.Series:
        """Calculate EMA using pandas ewm."""
        return prices.ewm(span=span, adjust=False).mean()

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            min_len = max(self.fast, self.slow) + self.signal
            if len(df) < min_len:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {min_len}",
                )

            prices = df["c"]
            fast_ema = self._ema(prices, self.fast)
            slow_ema = self._ema(prices, self.slow)
            macd_line = fast_ema - slow_ema
            signal_line = self._ema(macd_line, self.signal)
            histogram = macd_line - signal_line

            if macd_line.empty or signal_line.empty or histogram.empty:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="MACD calculation failed",
                )

            macd_val = macd_line.iloc[-1]
            signal_val = signal_line.iloc[-1]
            hist_val = histogram.iloc[-1]
            prev_hist = histogram.iloc[-2] if len(histogram) > 1 else hist_val

            if pd.isna(macd_val) or pd.isna(signal_val):
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="MACD NaN values",
                )

            # Crossover detection
            prev_macd = macd_line.iloc[-2] if len(macd_line) > 1 else macd_val
            prev_signal = signal_line.iloc[-2] if len(signal_line) > 1 else signal_val

            if macd_val > signal_val and prev_macd <= prev_signal:
                confidence = min(1.0, abs(hist_val) / max(abs(prev_hist), 0.001))
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=confidence,
                    reason=f"MACD golden cross: {macd_val:.4f} > {signal_val:.4f}",
                )
            elif macd_val < signal_val and prev_macd >= prev_signal:
                confidence = min(1.0, abs(hist_val) / max(abs(prev_hist), 0.001))
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=confidence,
                    reason=f"MACD death cross: {macd_val:.4f} < {signal_val:.4f}",
                )
            else:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"MACD no cross: {macd_val:.4f} vs {signal_val:.4f}",
                )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"MACD error: {e}",
            )
