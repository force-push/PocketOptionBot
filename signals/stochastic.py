"""Stochastic Oscillator signal.

The Stochastic Oscillator measures the position of the closing price within
the range of recent highs and lows. It's range-bound (0-100) and excellent
for identifying overbought/oversold conditions and momentum reversals.

K% = 100 * (close - lowest low) / (highest high - lowest low)
D% = 3-period simple moving average of K%

Signals:
- K% < 20: oversold → potential CALL (bounce)
- K% > 80: overbought → potential PUT (reversal)
- K% crossing D%: momentum shift
"""

import pandas as pd
import numpy as np

from signals.base import BaseSignal, SignalResult


class StochasticSignal(BaseSignal):
    """Stochastic Oscillator momentum signal.

    Identifies overbought/oversold conditions and momentum shifts through
    K% and D% crossovers. Excellent for mean-reversion on short timeframes.
    """

    name = "Stochastic"
    weight = 0.12  # Tier 2: supporting signal for momentum confirmation

    def __init__(self, period: int = 14, smooth_k: int = 3, smooth_d: int = 3):
        """
        Args:
            period: Lookback period for high/low range (default 14)
            smooth_k: Smoothing period for K% (default 3)
            smooth_d: Smoothing period for D% (default 3)
        """
        self.period = period
        self.smooth_k = smooth_k
        self.smooth_d = smooth_d

    def _stochastic(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Calculate K% and D% lines."""
        lowest_low = df["l"].rolling(window=self.period).min()
        highest_high = df["h"].rolling(window=self.period).max()

        # K% = 100 * (close - lowest low) / (highest high - lowest low)
        k_raw = 100 * (df["c"] - lowest_low) / (highest_high - lowest_low)
        k_raw = k_raw.fillna(50)  # Fill NaN from early period with neutral value

        # Smooth K%
        k_pct = k_raw.rolling(window=self.smooth_k).mean()

        # D% = moving average of K%
        d_pct = k_pct.rolling(window=self.smooth_d).mean()

        return k_pct, d_pct

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < self.period + self.smooth_k + self.smooth_d:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {self.period + self.smooth_k + self.smooth_d}",
                )

            k_pct, d_pct = self._stochastic(df)

            current_k = k_pct.iloc[-1]
            current_d = d_pct.iloc[-1]
            prev_k = k_pct.iloc[-2] if len(k_pct) > 1 else current_k
            prev_d = d_pct.iloc[-2] if len(d_pct) > 1 else current_d

            if pd.isna(current_k) or pd.isna(current_d):
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="Stochastic calculation failed",
                )

            # Detect K% crossover and extreme conditions
            direction = None
            confidence = 0.0
            reason = ""

            # Oversold: K% < 30 (loosened from 20 for more signals on OTC)
            if current_k < 30:
                direction = "CALL"
                confidence = min(1.0, (30 - current_k) / 30)
                reason = f"Stochastic oversold: K%={current_k:.1f} (D%={current_d:.1f})"

            # Overbought: K% > 70 (loosened from 80 for more signals on OTC)
            elif current_k > 70:
                direction = "PUT"
                confidence = min(1.0, (current_k - 70) / 30)
                reason = f"Stochastic overbought: K%={current_k:.1f} (D%={current_d:.1f})"

            # Bullish crossover: K% crosses above D%
            elif prev_k <= prev_d and current_k > current_d:
                direction = "CALL"
                confidence = 0.4  # Moderate confidence for crossover
                reason = f"Stochastic bullish cross: K%={current_k:.1f} > D%={current_d:.1f}"

            # Bearish crossover: K% crosses below D%
            elif prev_k >= prev_d and current_k < current_d:
                direction = "PUT"
                confidence = 0.4  # Moderate confidence for crossover
                reason = f"Stochastic bearish cross: K%={current_k:.1f} < D%={current_d:.1f}"

            # No signal
            else:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Stochastic neutral: K%={current_k:.1f}, D%={current_d:.1f}",
                )

            return SignalResult(
                name=self.name,
                direction=direction,
                confidence=confidence,
                reason=reason,
            )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"Stochastic error: {e}",
            )
