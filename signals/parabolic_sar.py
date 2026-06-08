"""Parabolic SAR (Stop and Reverse) signal.

Parabolic SAR is a trend-following indicator that provides entry and exit
points. It plots dots below price in uptrends and above price in downtrends.
The indicator reverses when price crosses the SAR line.

SAR calculation uses:
- AF (Acceleration Factor): starts at 0.02, increases by 0.02 each new extreme
- EP (Extreme Point): highest high in uptrend, lowest low in downtrend
- SAR = Previous SAR + AF * (EP - Previous SAR)

Advantage: provides natural stop-loss levels and trend confirmation.
"""

import pandas as pd
import numpy as np

from signals.base import BaseSignal, SignalResult


class ParabolicSARSignal(BaseSignal):
    """Parabolic SAR trend-following and reversal signal.

    Excellent for both trend confirmation and early reversal detection.
    Provides natural stop-loss levels via the SAR value.
    """

    name = "Parabolic_SAR"
    weight = 0.13  # Tier 2: supporting trend signal

    def __init__(self, initial_af: float = 0.02, max_af: float = 0.2, af_step: float = 0.02):
        """
        Args:
            initial_af: Starting acceleration factor (default 0.02)
            max_af: Maximum AF limit (default 0.2)
            af_step: AF increment per new extreme (default 0.02)
        """
        self.initial_af = initial_af
        self.max_af = max_af
        self.af_step = af_step

    def _parabolic_sar(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Calculate Parabolic SAR and trend.

        Returns:
            (sar_values, trend) where trend is 1 for uptrend, -1 for downtrend
        """
        sar = np.zeros(len(df))
        trend = np.zeros(len(df))  # 1 = uptrend, -1 = downtrend
        af = np.zeros(len(df))
        ep = np.zeros(len(df))

        # Initialize first values
        sar[0] = df["l"].iloc[0]
        trend[0] = 1  # Assume starting in uptrend
        af[0] = self.initial_af
        ep[0] = df["h"].iloc[0]

        for i in range(1, len(df)):
            close = df["c"].iloc[i]
            high = df["h"].iloc[i]
            low = df["l"].iloc[i]

            # Update SAR based on trend
            if trend[i - 1] == 1:  # Uptrend
                # SAR never goes above the last two lows
                sar[i] = sar[i - 1] + af[i - 1] * (ep[i - 1] - sar[i - 1])
                sar[i] = min(sar[i], df["l"].iloc[max(0, i - 1)])
                if i > 1:
                    sar[i] = min(sar[i], df["l"].iloc[i - 2])

                # Check for trend reversal
                if low < sar[i]:
                    trend[i] = -1  # Reverse to downtrend
                    sar[i] = ep[i - 1]
                    af[i] = self.initial_af
                    ep[i] = low
                else:
                    trend[i] = 1
                    af[i] = af[i - 1]
                    if high > ep[i - 1]:
                        ep[i] = high
                        af[i] = min(af[i - 1] + self.af_step, self.max_af)
                    else:
                        ep[i] = ep[i - 1]
            else:  # Downtrend
                # SAR never goes below the last two highs
                sar[i] = sar[i - 1] + af[i - 1] * (ep[i - 1] - sar[i - 1])
                sar[i] = max(sar[i], df["h"].iloc[max(0, i - 1)])
                if i > 1:
                    sar[i] = max(sar[i], df["h"].iloc[i - 2])

                # Check for trend reversal
                if high > sar[i]:
                    trend[i] = 1  # Reverse to uptrend
                    sar[i] = ep[i - 1]
                    af[i] = self.initial_af
                    ep[i] = high
                else:
                    trend[i] = -1
                    af[i] = af[i - 1]
                    if low < ep[i - 1]:
                        ep[i] = low
                        af[i] = min(af[i - 1] + self.af_step, self.max_af)
                    else:
                        ep[i] = ep[i - 1]

        return pd.Series(sar, index=df.index), pd.Series(trend, index=df.index)

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < 5:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < 5",
                )

            sar, trend = self._parabolic_sar(df)

            current_sar = sar.iloc[-1]
            current_trend = trend.iloc[-1]
            current_price = df["c"].iloc[-1]

            if pd.isna(current_sar):
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="Parabolic SAR calculation failed",
                )

            # Distance from SAR (normalized by recent range)
            recent_high = df["h"].iloc[-min(5, len(df)) :].max()
            recent_low = df["l"].iloc[-min(5, len(df)) :].min()
            recent_range = recent_high - recent_low
            distance_pct = (
                abs(current_price - current_sar) / recent_range
                if recent_range > 0
                else 0
            )

            if current_trend == 1:
                # Uptrend (CALL)
                confidence = min(1.0, distance_pct * 2)  # Scale to 0-1
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=confidence,
                    reason=(
                        f"Parabolic SAR uptrend: price {current_price:.5f} > SAR {current_sar:.5f} "
                        f"(distance={distance_pct:.1%})"
                    ),
                )
            else:
                # Downtrend (PUT)
                confidence = min(1.0, distance_pct * 2)
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=confidence,
                    reason=(
                        f"Parabolic SAR downtrend: price {current_price:.5f} < SAR {current_sar:.5f} "
                        f"(distance={distance_pct:.1%})"
                    ),
                )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"Parabolic SAR error: {e}",
            )
