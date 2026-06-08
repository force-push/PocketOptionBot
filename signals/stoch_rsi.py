"""Stochastic RSI signal.

Stoch-RSI applies the Stochastic Oscillator formula to RSI values rather than
directly to price. This makes it a second-order indicator:

    RSI = standard 14-period RSI of close prices
    StochK = 100 * (RSI - min(RSI, stoch_period)) / (max(RSI, stoch_period) - min(RSI, stoch_period))
    StochD = smooth_d-period SMA of StochK

Plain RSI was found to be noise (~45% WR regardless of direction). Plain Stochastic
was added as Tier 2. Stoch-RSI is more specific: it asks "is *momentum itself*
overbought/oversold?" rather than "is price at a range extreme?". This distinction
matters for short OTC expiry — a deeply oversold RSI that is *also* at a Stoch extreme
is a stronger reversal candidate than either signal alone.

K < 20: momentum oversold → CALL (reversal from exhausted selling)
K > 80: momentum overbought → PUT (reversal from exhausted buying)
K crossing D in oversold/overbought zone: momentum shift confirmation
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from signals.base import BaseSignal, SignalResult


class StochRSISignal(BaseSignal):
    """Stochastic RSI momentum exhaustion signal.

    Observation-only Tier 3 signal (weight > 0, not in decision_signals).
    Faster and more sensitive than plain RSI or plain Stochastic — trades
    off noise tolerance for earlier reversal detection.
    """

    name = "StochRSI"
    weight = 0.10

    def __init__(
        self,
        rsi_period: int = 14,
        stoch_period: int = 14,
        smooth_k: int = 3,
        smooth_d: int = 3,
        oversold: float = 20.0,
        overbought: float = 80.0,
    ):
        """
        Args:
            rsi_period: Period for the inner RSI calculation.
            stoch_period: Lookback period for the Stochastic applied to RSI.
            smooth_k: SMA smoothing period for K% line.
            smooth_d: SMA smoothing period for D% line (signal line).
            oversold: K% below this value fires a CALL.
            overbought: K% above this value fires a PUT.
        """
        self.rsi_period = rsi_period
        self.stoch_period = stoch_period
        self.smooth_k = smooth_k
        self.smooth_d = smooth_d
        self.oversold = oversold
        self.overbought = overbought

    def _rsi(self, prices: pd.Series) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=self.rsi_period).mean()
        # When loss=0 and gain>0: RSI=100. When gain=0 and loss>0: RSI=0.
        # Avoid division by zero; preserve NaN from insufficient data.
        rsi = pd.Series(np.nan, index=prices.index)
        both_zero = (gain == 0) & (loss == 0)
        gain_only = (gain > 0) & (loss == 0)
        loss_only = (gain == 0) & (loss > 0)
        normal = (loss > 0) & (gain >= 0)
        rsi[both_zero] = 50.0  # no movement — neutral
        rsi[gain_only] = 100.0
        rsi[loss_only] = 0.0
        rsi[normal] = 100.0 - (100.0 / (1.0 + gain[normal] / loss[normal]))
        return rsi

    def _stoch_rsi(self, rsi: pd.Series) -> tuple[pd.Series, pd.Series]:
        lowest = rsi.rolling(window=self.stoch_period).min()
        highest = rsi.rolling(window=self.stoch_period).max()
        denom = (highest - lowest).replace(0, np.nan)
        k_raw = 100.0 * (rsi - lowest) / denom
        k_raw = k_raw.fillna(50.0)  # neutral when range is zero
        k = k_raw.rolling(window=self.smooth_k).mean()
        d = k.rolling(window=self.smooth_d).mean()
        return k, d

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        min_rows = self.rsi_period + self.stoch_period + self.smooth_k + self.smooth_d
        if len(df) < min_rows:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"Insufficient data: {len(df)} rows (need ≥{min_rows})",
            )

        try:
            rsi = self._rsi(df["c"])
            k, d = self._stoch_rsi(rsi)

            curr_k = k.iloc[-1]
            curr_d = d.iloc[-1]
            prev_k = k.iloc[-2] if len(k) > 1 else curr_k
            prev_d = d.iloc[-2] if len(d) > 1 else curr_d

            if pd.isna(curr_k) or pd.isna(curr_d):
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="StochRSI calculation produced NaN",
                )

            # ── Oversold: K < oversold threshold ─────────────────────────────
            if curr_k < self.oversold:
                confidence = min(1.0, (self.oversold - curr_k) / self.oversold)
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=confidence,
                    reason=f"StochRSI oversold: K={curr_k:.1f} D={curr_d:.1f}",
                )

            # ── Overbought: K > overbought threshold ──────────────────────────
            if curr_k > self.overbought:
                confidence = min(1.0, (curr_k - self.overbought) / (100.0 - self.overbought))
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=confidence,
                    reason=f"StochRSI overbought: K={curr_k:.1f} D={curr_d:.1f}",
                )

            # ── Bullish K/D crossover in oversold zone ────────────────────────
            if (prev_k <= prev_d and curr_k > curr_d and curr_k < 50.0
                    and not pd.isna(prev_k) and not pd.isna(prev_d)):
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=0.40,
                    reason=f"StochRSI bullish cross: K={curr_k:.1f} > D={curr_d:.1f}",
                )

            # ── Bearish K/D crossover in overbought zone ──────────────────────
            if (prev_k >= prev_d and curr_k < curr_d and curr_k > 50.0
                    and not pd.isna(prev_k) and not pd.isna(prev_d)):
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=0.40,
                    reason=f"StochRSI bearish cross: K={curr_k:.1f} < D={curr_d:.1f}",
                )

            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"StochRSI neutral: K={curr_k:.1f} D={curr_d:.1f}",
            )

        except Exception as exc:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"StochRSI error: {exc}",
            )
