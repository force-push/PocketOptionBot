"""EMA Crossover + trend-direction signal.

Design rationale
----------------
The original implementation only fired on the exact bar where the fast EMA
crossed the slow EMA.  Like MACD (same root cause), a crossover is a
single-bar event; in a 100-candle window it may never occur, so the signal
was returning null on most cycles.

Revised behaviour (two tiers):
  1. FRESH CROSSOVER — fast EMA just crossed slow EMA on the last bar.
     Confidence scales with the gap as a percentage of the slow EMA.
     Max confidence = 1.0.

  2. ESTABLISHED TREND — fast EMA is above/below slow EMA without a fresh
     cross.  Fires as a directional bias with confidence capped at
     TREND_CONF_CAP (default 0.55).  Slightly lower cap than MACD because
     EMA crossovers on short timeframes are noisier — the trend-direction
     signal from EMA is the weakest of the two tier-2 signals.

Why two tiers?
--------------
For short binary options, momentum alignment is what matters.  If the fast
EMA has been above the slow EMA for the last 30 bars and all other signals
agree, ignoring that context makes the system unnecessarily conservative.
The cap ensures that only when a fresh crossover occurs does EMA push the
confluence score toward the high-confidence zone.

Parameters
----------
  fast  — fast EMA period  (default 9)
  slow  — slow EMA period  (default 21)
  trend_conf_cap — confidence ceiling for established-trend signal (0.55)
"""

import pandas as pd

from signals.base import BaseSignal, SignalResult

_TREND_CONF_CAP = 0.55


class EMASignal(BaseSignal):
    """EMA crossover + trend-direction signal."""

    name = "EMA_Cross"
    weight = 0.15

    def __init__(
        self,
        fast: int = 9,
        slow: int = 21,
        trend_conf_cap: float = _TREND_CONF_CAP,
    ):
        self.fast = fast
        self.slow = slow
        self.trend_conf_cap = trend_conf_cap

    def _ema(self, series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < self.slow:
                return SignalResult(
                    name=self.name, direction=None, confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {self.slow}",
                )

            fast_ema = self._ema(df["c"], self.fast)
            slow_ema = self._ema(df["c"], self.slow)

            fv = fast_ema.iloc[-1]
            sv = slow_ema.iloc[-1]

            if pd.isna(fv) or pd.isna(sv):
                return SignalResult(
                    name=self.name, direction=None, confidence=0.0,
                    reason="EMA NaN — insufficient history for EMA warmup",
                )

            prev_fv = fast_ema.iloc[-2] if len(fast_ema) > 1 else fv
            prev_sv = slow_ema.iloc[-2] if len(slow_ema) > 1 else sv

            gap = abs(fv - sv)
            gap_pct = gap / max(abs(sv), 1e-9)

            # ── Tier 1: fresh crossover ──────────────────────────────────────
            if fv > sv and prev_fv <= prev_sv:
                conf = min(1.0, gap_pct * 100)
                return SignalResult(
                    name=self.name, direction="CALL", confidence=conf,
                    reason=f"EMA golden cross  fast={fv:.5f} > slow={sv:.5f}",
                )
            if fv < sv and prev_fv >= prev_sv:
                conf = min(1.0, gap_pct * 100)
                return SignalResult(
                    name=self.name, direction="PUT", confidence=conf,
                    reason=f"EMA death cross  fast={fv:.5f} < slow={sv:.5f}",
                )

            # ── Tier 2: established trend ────────────────────────────────────
            conf = min(self.trend_conf_cap, gap_pct * 50)

            if fv > sv:
                return SignalResult(
                    name=self.name, direction="CALL", confidence=conf,
                    reason=f"EMA bullish trend  fast={fv:.5f} above slow={sv:.5f}  gap={gap:.5f}",
                )
            if fv < sv:
                return SignalResult(
                    name=self.name, direction="PUT", confidence=conf,
                    reason=f"EMA bearish trend  fast={fv:.5f} below slow={sv:.5f}  gap={gap:.5f}",
                )

            return SignalResult(
                name=self.name, direction=None, confidence=0.0,
                reason=f"EMA flat: fast={fv:.5f}  slow={sv:.5f}",
            )

        except Exception as exc:
            return SignalResult(
                name=self.name, direction=None, confidence=0.0,
                reason=f"EMA error: {exc}",
            )
