"""SuperTrend-flip scalping strategy (5s expiry).

Direction comes from SuperTrend; a trade is taken only when MACD agrees and ADX
confirms real movement. Two ways in:

  • FLIP        — SuperTrend just flipped this bar (the chart's Buy/Sell label),
                  MACD on the same side, ADX ≥ adx_flip_min.
  • CONTINUATION— SuperTrend already established on this side (no fresh flip),
                  MACD agrees, and the trend is *strong*: ADX ≥ adx_trend_min,
                  ADX rising, and price is beyond the SuperTrend band by
                  ≥ atr_distance_min × ATR. The stricter bar keeps continuation
                  entries on genuine runs, not sideways drift.

Pure function (no I/O) → fully offline-testable. The manager calls
``evaluate_flip(df, params)`` and trades the returned direction.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from signals.supertrend import compute_supertrend, _atr
from signals.macd import compute_macd
from signals.adx_dmi import compute_adx


@dataclass(frozen=True)
class FlipParams:
    st_period: int = 10
    st_multiplier: float = 3.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    adx_period: int = 14
    adx_flip_min: float = 22.0      # min ADX to confirm a fresh flip
    adx_trend_min: float = 25.0     # higher bar for trend continuation
    require_adx_rising: bool = True  # continuation needs ADX rising
    atr_distance_min: float = 0.5   # continuation: price ≥ this×ATR from ST band
    min_candles: int = 40


@dataclass(frozen=True)
class FlipDecision:
    direction: str | None      # "CALL" | "PUT" | None
    entry_kind: str | None     # "flip" | "trend" | None
    reason: str
    metrics: dict | None = None  # {entry_kind, adx, adx_rising, plus_di, minus_di,
                                 #  dist, macd_gap, st_dir} — stamped on the row so
                                 #  losses can be analysed by feature later.


def evaluate_flip(df: pd.DataFrame, params: FlipParams = FlipParams()) -> FlipDecision:
    """Apply the flip-or-strong-continuation rule to a candle DataFrame."""
    n = 0 if df is None else len(df)
    if n < params.min_candles:
        return FlipDecision(None, None, f"insufficient candles ({n} < {params.min_candles})")

    st, trend = compute_supertrend(df, params.st_period, params.st_multiplier)
    macd_line, signal_line, _hist = compute_macd(
        df, params.macd_fast, params.macd_slow, params.macd_signal
    )
    pos_di, neg_di, adx = compute_adx(df, params.adx_period)
    atr = _atr(df, params.st_period)

    t = int(trend.iloc[-1])
    t_prev = int(trend.iloc[-2]) if len(trend) > 1 else t
    direction = "CALL" if t == 1 else "PUT"
    flipped = t != t_prev

    ml, sl = macd_line.iloc[-1], signal_line.iloc[-1]
    adx_now = adx.iloc[-1]
    adx_prev = adx.iloc[-2] if len(adx) > 1 else adx_now
    pdi, ndi = pos_di.iloc[-1], neg_di.iloc[-1]
    if pd.isna(ml) or pd.isna(sl) or pd.isna(adx_now):
        return FlipDecision(None, None, "indicator warmup (NaN)")

    price = float(df["c"].iloc[-1])
    st_val = float(st.iloc[-1])
    a = atr.iloc[-1]
    dist = abs(price - st_val) / a if (np.isfinite(a) and a > 0) else 0.0

    adx_rising = bool(adx_now > adx_prev)
    diag = (f"ST={direction} adx={adx_now:.1f}{'↑' if adx_rising else '↓'} "
            f"+DI={pdi:.1f} -DI={ndi:.1f} macd_gap={ml - sl:.6f} dist={dist:.2f}ATR")
    metrics = {
        "st_dir": direction, "flipped": bool(flipped), "adx": round(float(adx_now), 2),
        "adx_rising": adx_rising, "plus_di": round(float(pdi), 2),
        "minus_di": round(float(ndi), 2), "dist_atr": round(float(dist), 3),
        "macd_gap": float(ml - sl),
    }

    macd_ok = (ml > sl) if direction == "CALL" else (ml < sl)
    di_ok = (pdi > ndi) if direction == "CALL" else (ndi > pdi)
    if not macd_ok:
        return FlipDecision(None, None, f"MACD disagrees ({diag})", metrics)
    if not di_ok:
        return FlipDecision(None, None, f"DI disagrees ({diag})", metrics)

    if flipped:
        if adx_now >= params.adx_flip_min:
            return FlipDecision(direction, "flip", f"FLIP {direction} confirmed ({diag})",
                                {**metrics, "entry_kind": "flip"})
        return FlipDecision(None, None, f"flip but ADX<{params.adx_flip_min} ({diag})", metrics)

    # Established trend → continuation requires the stronger gate.
    rising_ok = adx_rising or not params.require_adx_rising
    strong = adx_now >= params.adx_trend_min and rising_ok and dist >= params.atr_distance_min
    if strong:
        return FlipDecision(direction, "trend", f"TREND {direction} continuation ({diag})",
                            {**metrics, "entry_kind": "trend"})
    return FlipDecision(None, None, f"trend not strong enough ({diag})", metrics)
