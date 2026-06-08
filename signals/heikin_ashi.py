"""Heikin-Ashi trend persistence signal.

Heikin-Ashi is a price *transformation* — not an indicator — that smooths candle
noise by averaging each bar with the previous one:

    HA_Close = (open + high + low + close) / 4
    HA_Open  = (prev_HA_open + prev_HA_close) / 2
    HA_High  = max(high, HA_open, HA_close)
    HA_Low   = min(low, HA_open, HA_close)

This dampens bar-level spikes that MACD/EMA still weight heavily, making it
orthogonal to every other signal in the stack. Consecutive same-colour HA bars
measure directional *persistence* — a concept that no moving-average derivative
can express.

Why this matters for 30s OTC pairs: OTC synthetics have high bar-level noise.
A 3-bar HA run has survived the noise filter; it's a stronger statement than
three raw green candles.

Signals:
- ≥3 consecutive bullish bars: CALL, confidence scales with run length
- ≥3 consecutive bearish bars: PUT, confidence scales with run length
- Colour switch after ≥3-bar run: reversal signal, confidence 0.35
- < 3 consecutive bars or mixed: no signal
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from signals.base import BaseSignal, SignalResult


class HeikinAshiSignal(BaseSignal):
    """Heikin-Ashi trend persistence and reversal signal.

    Observation-only Tier 3 signal (weight > 0, not in decision_signals).
    Collect ~500 resolved trades then run analyze_signals.py to decide on
    promotion or retirement.
    """

    name = "HeikinAshi"
    weight = 0.12  # Tier 3: observation signal — orthogonal to MACD/EMA

    def __init__(self, min_consecutive: int = 3):
        """
        Args:
            min_consecutive: Minimum consecutive same-colour HA bars for a trend signal.
        """
        self.min_consecutive = min_consecutive

    def _compute_ha(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame with ha_open, ha_high, ha_low, ha_close columns."""
        ha = pd.DataFrame(index=df.index)

        # HA Close: average of all four prices
        ha["ha_close"] = (df["o"] + df["h"] + df["l"] + df["c"]) / 4.0

        # HA Open: iterative — starts from first bar's midpoint, then averages forward
        ha_open = np.empty(len(df))
        ha_open[0] = (df["o"].iloc[0] + df["c"].iloc[0]) / 2.0
        for i in range(1, len(df)):
            ha_open[i] = (ha_open[i - 1] + ha["ha_close"].iloc[i - 1]) / 2.0
        ha["ha_open"] = ha_open

        # HA High / Low: envelope that wraps HA open + close
        ha["ha_high"] = pd.concat(
            [df["h"], ha["ha_open"], ha["ha_close"]], axis=1
        ).max(axis=1)
        ha["ha_low"] = pd.concat(
            [df["l"], ha["ha_open"], ha["ha_close"]], axis=1
        ).min(axis=1)

        return ha

    def _bar_color(self, ha_close: pd.Series, ha_open: pd.Series) -> pd.Series:
        """Return a series of +1 (bullish), -1 (bearish), 0 (doji/flat).

        A doji is when HA close and HA open are identical (or within floating-
        point epsilon), indicating no directional information — it breaks any run.
        """
        diff = ha_close - ha_open
        colors = pd.Series(0, index=ha_close.index, dtype=int)
        colors[diff > 0] = 1
        colors[diff < 0] = -1
        # Exact equality (diff == 0) stays 0 — doji
        return colors

    def _count_consecutive(self, colors: pd.Series) -> int:
        """Count the current run of same non-zero colour at the end of the series.

        Returns positive int for bullish run, negative for bearish. A doji (0)
        breaks any run, so returns 0 if the last bar is a doji.
        """
        if len(colors) == 0:
            return 0

        current = colors.iloc[-1]
        if current == 0:
            return 0  # Doji — no run

        count = 0
        for val in reversed(colors.tolist()):
            if val == current:
                count += 1
            else:
                break

        return count if current > 0 else -count

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        min_rows = self.min_consecutive + 2  # need a few extra for HA warm-up
        if len(df) < min_rows:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"Insufficient data: {len(df)} rows (need ≥{min_rows})",
            )

        try:
            ha = self._compute_ha(df)
            ha_close = ha["ha_close"]
            ha_open = ha["ha_open"]

            colors = self._bar_color(ha_close, ha_open)

            prev_color = colors.iloc[-2]
            curr_color = colors.iloc[-1]

            run = self._count_consecutive(colors)
            abs_run = abs(run)

            # ── Doji: no directional information ─────────────────────────────
            if curr_color == 0:
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason="HA doji — no directional signal",
                )

            # ── Reversal: colour just switched after a sustained run ──────────
            if prev_color != 0 and prev_color != curr_color and abs_run == 1:
                prev_run = self._count_consecutive(colors.iloc[:-1])
                if abs(prev_run) >= self.min_consecutive:
                    direction = "CALL" if curr_color > 0 else "PUT"
                    return SignalResult(
                        name=self.name,
                        direction=direction,
                        confidence=0.35,
                        reason=(
                            f"HA reversal after {abs(prev_run)}-bar "
                            f"{'bearish' if curr_color > 0 else 'bullish'} run → {direction}"
                        ),
                    )
                return SignalResult(
                    name=self.name,
                    direction=None,
                    confidence=0.0,
                    reason=f"HA colour switch but prior run only {abs(prev_run)} bars (need ≥{self.min_consecutive})",
                )

            # ── Trend persistence: run of ≥ min_consecutive same-colour bars ──
            if abs_run >= self.min_consecutive:
                direction = "CALL" if run > 0 else "PUT"
                # Confidence: 0.25 at exactly min_consecutive, +0.25 per extra bar, cap 1.0
                confidence = min(1.0, (abs_run - self.min_consecutive + 1) * 0.25)
                return SignalResult(
                    name=self.name,
                    direction=direction,
                    confidence=confidence,
                    reason=(
                        f"HA {abs_run}-bar {'bullish' if run > 0 else 'bearish'} run → {direction} "
                        f"(conf={confidence:.2f})"
                    ),
                )

            # ── No signal: run too short ──────────────────────────────────────
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"HA run only {abs_run} bar(s) — below min {self.min_consecutive}",
            )

        except Exception as exc:
            return SignalResult(
                name=self.name,
                direction=None,
                confidence=0.0,
                reason=f"HeikinAshi error: {exc}",
            )
