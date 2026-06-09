"""ATR (Average True Range) signal.

Observation-only (weight=0.0) — used for research/analysis, not trading decisions.
ATR measures volatility (price movement magnitude).
High ATR = volatile market, Low ATR = low volatility.
No inherent direction (doesn't predict CALL/PUT), only reports volatility state.
"""

import pandas as pd
import numpy as np

from signals.base import BaseSignal, SignalResult


class ATRSignal(BaseSignal):
    """ATR volatility-based reversal signal.

    ATR (Average True Range) measures the average size of price movements.
    Extreme volatility often precedes mean reversion: very high ATR (>80th) suggests
    a squeeze may follow → PUT (bearish correction). Very low ATR (<20th) suggests
    momentum building → CALL (upside break). Normal volatility returns no signal.

    This orthogonal view catches "quiet before the storm" setups that MA-based
    signals miss. Weight raised from 0.0 to 0.10 to participate in decisions.
    """

    name = "ATR"
    weight = 0.10  # Now a direction-producing signal

    def __init__(self, period: int = 14):
        self.period = period

    def _true_range(self, df: pd.DataFrame) -> pd.Series:
        """Calculate True Range (max of: H-L, |H-Close_prev|, |L-Close_prev|)."""
        high = df["h"]
        low = df["l"]
        close_prev = df["c"].shift(1)

        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()

        return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < self.period:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {self.period}",
                )

            tr = self._true_range(df)
            atr = tr.rolling(window=self.period).mean()
            current_atr = atr.iloc[-1]

            if pd.isna(current_atr):
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="ATR calculation failed",
                )

            # Calculate volatility percentile (where does current ATR sit vs recent history?)
            # Use last 100 bars to establish baseline
            recent_atr = atr.iloc[max(0, -100) :]
            atr_min = recent_atr.min()
            atr_max = recent_atr.max()
            atr_range = atr_max - atr_min

            if atr_range > 0:
                atr_percentile = (current_atr - atr_min) / atr_range
            else:
                atr_percentile = 0.5

            # Determine regime and direction
            if atr_percentile < 0.20:
                regime = "low_volatility"
                direction = "CALL"  # Low ATR → momentum may break upward
                confidence = 1.0 - atr_percentile  # Higher confidence when deeper in the low zone
            elif atr_percentile > 0.80:
                regime = "high_volatility"
                direction = "PUT"  # High ATR → momentum may reverse downward
                confidence = atr_percentile  # Higher confidence when deeper in the high zone
            else:
                regime = "normal_volatility"
                direction = None  # Middle ground = neutral
                confidence = 0.0

            return SignalResult(
                name=self.name,
                direction=direction,
                confidence=confidence,
                reason=(
                    f"ATR {regime}: {current_atr:.6f} "
                    f"(min={atr_min:.6f}, max={atr_max:.6f}, percentile={atr_percentile:.1%})"
                ),
            )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"ATR error: {e}",
            )
