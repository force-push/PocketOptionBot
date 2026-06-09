"""ADX (Average Directional Index) and DMI (Directional Movement Index) signal.

Observation-only (weight=0.0) — used for research/analysis, not trading decisions.
ADX measures trend strength (0-100): <20 weak, 20-40 moderate, 40+ strong.
DMI +/- lines show trend direction: +DI > -DI = uptrend (CALL), -DI > +DI = downtrend (PUT).
"""

import pandas as pd
import numpy as np

from signals.base import BaseSignal, SignalResult


class ADXDMISignal(BaseSignal):
    """ADX/DMI trend strength and direction indicator.

    Returns CALL if +DI > -DI (uptrend), PUT if -DI > +DI (downtrend).
    Confidence scales with ADX strength (higher ADX = stronger trend = higher confidence).
    Directional contributor: small weight so it participates in the confluence
    vote and probability score (2026-06-10 — all signals enabled for decisions).
    """

    name = "ADX_DMI"
    weight = 0.08  # Directional, modest weight (trend-strength confirmer)

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

    def _directional_movement(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Calculate +DM and -DM."""
        high = df["h"]
        low = df["l"]
        high_diff = high.diff()
        low_diff = -low.diff()

        pos_dm = pd.Series(0.0, index=df.index)
        neg_dm = pd.Series(0.0, index=df.index)

        # +DM: max(H - H_prev, 0) if it's > -DM, else 0
        pos_dm = high_diff.where((high_diff > 0) & (high_diff > low_diff), 0)
        pos_dm = pos_dm.where(pos_dm > 0, 0)

        # -DM: max(L_prev - L, 0) if it's > +DM, else 0
        neg_dm = low_diff.where((low_diff > 0) & (low_diff > high_diff), 0)
        neg_dm = neg_dm.where(neg_dm > 0, 0)

        return pos_dm, neg_dm

    def _calculate_dmi(
        self, df: pd.DataFrame, period: int
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate +DI, -DI, and ADX."""
        tr = self._true_range(df)
        atr = tr.rolling(window=period).mean()

        pos_dm, neg_dm = self._directional_movement(df)
        pos_dm_smooth = pos_dm.rolling(window=period).mean()
        neg_dm_smooth = neg_dm.rolling(window=period).mean()

        # Avoid division by zero
        pos_di = (100 * pos_dm_smooth / atr).fillna(0)
        neg_di = (100 * neg_dm_smooth / atr).fillna(0)

        # ADX = smoothed average of DI difference
        di_diff = (pos_di - neg_di).abs()
        adx = di_diff.rolling(window=period).mean()

        return pos_di, neg_di, adx

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < self.period * 2:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {self.period * 2}",
                )

            pos_di, neg_di, adx = self._calculate_dmi(df, self.period)

            current_pos_di = pos_di.iloc[-1]
            current_neg_di = neg_di.iloc[-1]
            current_adx = adx.iloc[-1]

            if pd.isna(current_adx) or pd.isna(current_pos_di) or pd.isna(current_neg_di):
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="ADX/DMI calculation failed",
                )

            # Determine direction: +DI > -DI = CALL, -DI > +DI = PUT
            if current_pos_di > current_neg_di:
                # Confidence scales with ADX (0-100), normalized to 0-1
                # At ADX=20, confidence=0.2; at ADX=40, confidence=0.4; at ADX=100, confidence=1.0
                confidence = min(1.0, current_adx / 100.0)
                return SignalResult(
                    name=self.name,
                    direction="CALL",
                    confidence=confidence,
                    reason=(
                        f"ADX bullish: +DI={current_pos_di:.1f} > -DI={current_neg_di:.1f} "
                        f"(ADX={current_adx:.1f})"
                    ),
                )
            elif current_neg_di > current_pos_di:
                confidence = min(1.0, current_adx / 100.0)
                return SignalResult(
                    name=self.name,
                    direction="PUT",
                    confidence=confidence,
                    reason=(
                        f"ADX bearish: -DI={current_neg_di:.1f} > +DI={current_pos_di:.1f} "
                        f"(ADX={current_adx:.1f})"
                    ),
                )
            else:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"ADX neutral: +DI ≈ -DI (ADX={current_adx:.1f})",
                )

        except Exception as e:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"ADX/DMI error: {e}",
            )
