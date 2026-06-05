"""MACD (Moving Average Convergence Divergence) signal.

Design rationale
----------------
The original implementation only fired on the exact bar of a crossover
(MACD line crossing the signal line).  A crossover is a single-bar event;
in any given 100-candle window there may be zero crossovers, so the signal
was returning null on most cycles — contributing nothing to the confluence
gate that requires ≥3 signals to agree.

Revised behaviour (two tiers):
  1. FRESH CROSSOVER — MACD line just crossed the signal line on the last bar.
     Confidence scales with histogram momentum (how much it moved vs the
     previous bar).  This is the strongest signal; max confidence = 1.0.

  2. ESTABLISHED TREND — MACD line is on one side of the signal line without
     a fresh cross.  Fires as a weaker directional bias.  Confidence scales
     with the gap magnitude but is capped at TREND_CONF_CAP (default 0.6) to
     keep it clearly below a genuine crossover signal.

Why this matters for binary options
------------------------------------
Short-expiry (30 s) binary options profit from momentum alignment, not just
from catching the exact crossover moment.  If MACD has been bullish for the
last 20 bars and all other signals agree, that context is relevant even
without a fresh cross on the last bar.

Parameters (configurable via BotSettings)
------------------------------------------
  fast  — fast EMA period  (default 12)
  slow  — slow EMA period  (default 26)
  signal_period — signal EMA period  (default 9)
  trend_conf_cap — max confidence for established-trend (no-cross) signal
                   (default 0.6, must be < 1.0 to distinguish from crossovers)
"""

import pandas as pd

from signals.base import BaseSignal, SignalResult

# Cap on confidence when reporting an established trend (not a fresh crossover).
# Keeps "we are trending" clearly weaker than "we just crossed" in the
# confluence score, which uses weighted confidences.
_TREND_CONF_CAP = 0.60


class MACDSignal(BaseSignal):
    """MACD crossover + trend-direction signal."""

    name = "MACD"
    weight = 0.20

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        trend_conf_cap: float = _TREND_CONF_CAP,
    ):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.trend_conf_cap = trend_conf_cap

    @staticmethod
    def _ema(prices: pd.Series, span: int) -> pd.Series:
        return prices.ewm(span=span, adjust=False).mean()

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            min_len = self.slow + self.signal
            if len(df) < min_len:
                return SignalResult(
                    name=self.name, direction=None, confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {min_len}",
                )

            prices     = df["c"]
            macd_line  = self._ema(prices, self.fast) - self._ema(prices, self.slow)
            signal_line = self._ema(macd_line, self.signal)
            histogram  = macd_line - signal_line

            mv = macd_line.iloc[-1]
            sv = signal_line.iloc[-1]
            hv = histogram.iloc[-1]

            if pd.isna(mv) or pd.isna(sv):
                return SignalResult(
                    name=self.name, direction=None, confidence=0.0,
                    reason="MACD NaN — insufficient history for EMA warmup",
                )

            prev_mv = macd_line.iloc[-2]  if len(macd_line)  > 1 else mv
            prev_sv = signal_line.iloc[-2] if len(signal_line) > 1 else sv
            prev_hv = histogram.iloc[-2]   if len(histogram)  > 1 else hv

            # ── Tier 1: fresh crossover ──────────────────────────────────────
            if mv > sv and prev_mv <= prev_sv:
                conf = min(1.0, abs(hv) / max(abs(prev_hv), 1e-9))
                return SignalResult(
                    name=self.name, direction="CALL", confidence=conf,
                    reason=f"MACD golden cross  line={mv:.5f}  sig={sv:.5f}  hist={hv:.5f}",
                )
            if mv < sv and prev_mv >= prev_sv:
                conf = min(1.0, abs(hv) / max(abs(prev_hv), 1e-9))
                return SignalResult(
                    name=self.name, direction="PUT", confidence=conf,
                    reason=f"MACD death cross  line={mv:.5f}  sig={sv:.5f}  hist={hv:.5f}",
                )

            # ── Tier 2: established trend ────────────────────────────────────
            # Scale confidence by gap size as a fraction of the signal line,
            # then cap at trend_conf_cap so established trend is always weaker
            # than a fresh crossover in the weighted confluence score.
            gap = abs(mv - sv)
            gap_pct = gap / max(abs(sv), 1e-9)
            conf = min(self.trend_conf_cap, gap_pct * 20)

            if mv > sv:
                return SignalResult(
                    name=self.name, direction="CALL", confidence=conf,
                    reason=f"MACD bullish trend  line={mv:.5f} > sig={sv:.5f}  gap={gap:.5f}",
                )
            if mv < sv:
                return SignalResult(
                    name=self.name, direction="PUT", confidence=conf,
                    reason=f"MACD bearish trend  line={mv:.5f} < sig={sv:.5f}  gap={gap:.5f}",
                )

            return SignalResult(
                name=self.name, direction=None, confidence=0.0,
                reason=f"MACD flat: line={mv:.5f}  sig={sv:.5f}",
            )

        except Exception as exc:
            return SignalResult(
                name=self.name, direction=None, confidence=0.0,
                reason=f"MACD error: {exc}",
            )
