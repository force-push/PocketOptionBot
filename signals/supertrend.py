"""Supertrend indicator signal.

Supertrend is a trend-following indicator that uses ATR (volatility) to set
dynamic support/resistance bands. It's excellent for confirming trends and
detecting reversals without the lag of moving averages.

The indicator plots above/below price:
- Above price: price in downtrend, bearish (PUT)
- Below price: price in uptrend, bullish (CALL)
Confidence increases with distance from the band (stronger trend).
"""

import pandas as pd
import numpy as np

from signals.base import BaseSignal, SignalResult


class SupertrendSignal(BaseSignal):
    """Supertrend trend-following signal.

    Uses ATR-based bands to determine trend direction. More responsive than
    moving average crossovers, particularly good at catching trend changes.
    """

    name = "Supertrend"
    weight = 0.15  # Tier 2: contribute to confluence but lower than MACD/EMA

    def __init__(self, period: int = 10, multiplier: float = 3.0):
        """
        Args:
            period: ATR period (default 10 for short-term trading)
            multiplier: ATR multiplier for band width (default 3.0 for tighter bands)
        """
        self.period = period
        self.multiplier = multiplier

    def _true_range(self, df: pd.DataFrame) -> pd.Series:
        """Calculate True Range."""
        high = df["h"]
        low = df["l"]
        close_prev = df["c"].shift(1)

        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()

        return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    def _supertrend(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Supertrend bands and trend line."""
        hl_avg = (df["h"] + df["l"]) / 2
        tr = self._true_range(df)
        atr = tr.rolling(window=self.period).mean()

        # Forward-fill initial ATR NaN values to stabilize bands early
        atr = atr.fillna(method='bfill').fillna(tr.mean())

        # Basic bands
        basic_ub = hl_avg + self.multiplier * atr
        basic_lb = hl_avg - self.multiplier * atr

        # Initialize final bands with basic bands
        final_ub = basic_ub.copy()
        final_lb = basic_lb.copy()

        # Smooth the bands (don't let them increase/decrease too quickly)
        for i in range(1, len(df)):
            if np.isfinite(basic_ub.iloc[i]) and np.isfinite(final_ub.iloc[i - 1]):
                final_ub.iloc[i] = min(basic_ub.iloc[i], final_ub.iloc[i - 1]) \
                    if df["c"].iloc[i - 1] > final_ub.iloc[i - 1] \
                    else final_ub.iloc[i - 1]

            if np.isfinite(basic_lb.iloc[i]) and np.isfinite(final_lb.iloc[i - 1]):
                final_lb.iloc[i] = max(basic_lb.iloc[i], final_lb.iloc[i - 1]) \
                    if df["c"].iloc[i - 1] < final_lb.iloc[i - 1] \
                    else final_lb.iloc[i - 1]

        # For supertrend, just use midpoint between bands for simplicity
        # In uptrend, trend value = lower band; in downtrend, trend value = upper band
        supertrend = (final_ub + final_lb) / 2

        return supertrend, final_ub, final_lb

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < self.period * 2:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {self.period * 2}",
                )

            supertrend, upper, lower = self._supertrend(df)
            current_st = supertrend.iloc[-1]
            current_price = df["c"].iloc[-1]
            current_atr = (upper.iloc[-1] - lower.iloc[-1]) / (2 * self.multiplier)

            if not np.isfinite(current_st) or not np.isfinite(current_atr) or current_atr == 0:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="Supertrend calculation failed",
                )

            # Distance from supertrend (normalized by ATR for scale-invariance)
            distance = abs(current_price - current_st) / current_atr if current_atr > 0 else 0

            if current_price > current_st:
                # Price above supertrend = uptrend (CALL)
                confidence = min(1.0, distance / 3.0)  # normalize to 1.0 at 3*ATR distance
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=confidence,
                    reason=(
                        f"Supertrend bullish: price {current_price:.5f} > ST {current_st:.5f} "
                        f"(distance={distance:.2f} ATR)"
                    ),
                )
            else:
                # Price below supertrend = downtrend (PUT)
                confidence = min(1.0, distance / 3.0)
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=confidence,
                    reason=(
                        f"Supertrend bearish: price {current_price:.5f} < ST {current_st:.5f} "
                        f"(distance={distance:.2f} ATR)"
                    ),
                )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"Supertrend error: {e}",
            )
