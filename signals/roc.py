"""Rate of Change (RoC) momentum signal.

RoC is the simplest possible truly independent momentum indicator:

    RoC = (close[now] - close[N bars ago]) / close[N bars ago]  × 100

It measures raw directional momentum with no smoothing. Unlike MACD and EMA
(which are exponentially-smoothed price derivatives), RoC is a direct
N-bar percentage change with zero lag — it captures whether price is continuing
or stalling *before* MACD/EMA update.

For 30s OTC expiry with 5s candles, period=5 gives a 25s lookback:
roughly one trade expiry window of momentum context.

Signals:
- RoC > threshold: continuing momentum → CALL
- RoC < -threshold: continuing momentum → PUT
- abs(RoC) ≤ threshold: flat/indecision → no signal
"""

from __future__ import annotations

import pandas as pd

from signals.base import BaseSignal, SignalResult


class RoCSignal(BaseSignal):
    """Rate of Change momentum signal.

    Observation-only Tier 3 signal (weight > 0, not in decision_signals).
    Uses a completely different computation path from all MACD/EMA derivatives.
    """

    name = "RoC"
    weight = 0.08

    def __init__(
        self,
        period: int = 5,
        threshold: float = 0.20,
        confidence_cap_pct: float = 0.50,
    ):
        """
        Args:
            period: Lookback period in bars. At 5s candles, period=5 = 25s lookback.
            threshold: Minimum |RoC| % to fire a signal. Filters flat/noise bars.
            confidence_cap_pct: RoC % at which confidence reaches 1.0.
        """
        self.period = period
        self.threshold = threshold
        self.confidence_cap_pct = confidence_cap_pct

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        min_rows = self.period + 1
        if len(df) < min_rows:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"Insufficient data: {len(df)} rows (need ≥{min_rows})",
            )

        try:
            close = df["c"]
            prior_close = close.iloc[-(self.period + 1)]
            current_close = close.iloc[-1]

            if prior_close == 0:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="RoC: prior close is zero — cannot compute",
                )

            roc = ((current_close - prior_close) / prior_close) * 100.0
            abs_roc = abs(roc)

            if abs_roc <= self.threshold:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"RoC flat: {roc:+.4f}% (threshold ±{self.threshold}%)",
                )

            direction = "CALL" if roc > 0 else "PUT"
            confidence = min(1.0, abs_roc / self.confidence_cap_pct)

            return SignalResult(
                name=self.name,
                direction=direction,
                confidence=confidence,
                reason=(
                    f"RoC {roc:+.4f}% over {self.period} bars → {direction} "
                    f"(conf={confidence:.2f})"
                ),
            )

        except Exception as exc:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"RoC error: {exc}",
            )
