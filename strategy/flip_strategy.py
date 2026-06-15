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


def _rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


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
    adx_max: float = 999.0          # skip entries above this ADX (over-extended/exhausted)
    require_adx_rising: bool = True  # continuation needs ADX rising
    atr_distance_min: float = 0.5   # continuation: price ≥ this×ATR from ST band
    atr_distance_max: float = 999.0  # continuation: skip if price > this×ATR from band (over-extended)
    cont_macd_gap_min: float = 0.0  # continuation: require |MACD-signal|/ATR ≥ this (momentum)
    cont_rsi_min: float = 0.0       # continuation: RSI > this for CALL / < (100-this) for PUT (0=off)
    rsi_period: int = 14            # RSI period for continuation confirmation
    flip_window_bars: int = 3       # treat as fresh flip if trend started ≤ this many bars ago
    bb_period: int = 20             # Bollinger period for band-width volatility metric
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
    rsi_series = _rsi(df["c"], params.rsi_period)
    rsi_val = rsi_series.iloc[-1]

    t = int(trend.iloc[-1])
    direction = "CALL" if t == 1 else "PUT"
    # Bars since the current trend began (1 = flipped on the last bar). A flip is
    # a 1-bar event; the scan samples each pair every few seconds, so accept it as
    # "fresh" if it started within the last flip_window_bars bars.
    tv = trend.to_numpy()
    bars_in_trend = 1
    for i in range(len(tv) - 2, -1, -1):
        if int(tv[i]) == t:
            bars_in_trend += 1
        else:
            break
    flipped = bars_in_trend <= params.flip_window_bars

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
    # Volatility metrics for loss-vs-win analysis: ATR as bps of price, and
    # Bollinger Band Width (upper-lower)/mid as bps (regime: narrow=chop).
    atr_bps = round(float(a) / price * 1e4, 3) if (np.isfinite(a) and price) else None
    close = df["c"]
    mid = close.rolling(params.bb_period).mean().iloc[-1]
    sd = close.rolling(params.bb_period).std().iloc[-1]
    bb_width_bps = (round(float(4 * sd / mid) * 1e4, 3)
                    if (np.isfinite(mid) and mid and np.isfinite(sd)) else None)
    # MACD momentum, ATR-normalised so it's comparable across pairs (raw macd_gap
    # is price-scale-dependent). This gates continuation entries — large gap =
    # real momentum (data: large-gap continuations ~53% WR vs small-gap ~47%).
    macd_gap_atr = round(abs(float(ml - sl)) / float(a), 3) if (np.isfinite(a) and a > 0) else 0.0
    rsi_now = round(float(rsi_val), 1) if (not pd.isna(rsi_val)) else None
    diag = (f"ST={direction} adx={adx_now:.1f}{'↑' if adx_rising else '↓'} "
            f"+DI={pdi:.1f} -DI={ndi:.1f} macd_gap={ml - sl:.6f} gapATR={macd_gap_atr} "
            f"dist={dist:.2f}ATR rsi={rsi_now} atr={atr_bps}bps bbw={bb_width_bps}bps")
    metrics = {
        "st_dir": direction, "flipped": bool(flipped), "bars_in_trend": bars_in_trend,
        "adx": round(float(adx_now), 2), "adx_rising": adx_rising,
        "plus_di": round(float(pdi), 2), "minus_di": round(float(ndi), 2),
        "dist_atr": round(float(dist), 3), "macd_gap": float(ml - sl),
        "macd_gap_atr": macd_gap_atr, "rsi": rsi_now,
        "atr_bps": atr_bps, "bb_width_bps": bb_width_bps,
    }

    # Over-extension cap: very high ADX = exhausted/climaxing move that tends to
    # revert inside a 5s expiry (data: ADX 45+ ~17% WR vs 25-35 ~61%).
    if adx_now > params.adx_max:
        return FlipDecision(None, None, f"ADX {adx_now:.1f} > max {params.adx_max} exhausted ({diag})", metrics)

    macd_ok = (ml > sl) if direction == "CALL" else (ml < sl)
    di_ok = (pdi > ndi) if direction == "CALL" else (ndi > pdi)
    if not macd_ok:
        return FlipDecision(None, None, f"MACD disagrees ({diag})", metrics)
    if not di_ok:
        return FlipDecision(None, None, f"DI disagrees ({diag})", metrics)

    if flipped:
        if macd_gap_atr < params.cont_macd_gap_min:
            return FlipDecision(None, None,
                                f"flip but weak MACD gap {macd_gap_atr}<{params.cont_macd_gap_min} ({diag})", metrics)
        if adx_now >= params.adx_flip_min:
            return FlipDecision(direction, "flip", f"FLIP {direction} confirmed ({diag})",
                                {**metrics, "entry_kind": "flip"})
        return FlipDecision(None, None, f"flip but ADX<{params.adx_flip_min} ({diag})", metrics)

    # Established trend → continuation. Edge requires: ADX strength + rising, price
    # within the 1–2 ATR "confirmed but not over-extended" zone, MACD momentum
    # gap, and RSI direction confirmation (if cont_rsi_min > 0).
    # Data (n=923): dist 1-2 ATR = 54-63% WR; dist >2 ATR = 47-49% (climaxing).
    rising_ok = adx_rising or not params.require_adx_rising
    macd_strong = macd_gap_atr >= params.cont_macd_gap_min
    dist_in_zone = params.atr_distance_min <= dist <= params.atr_distance_max
    strong = adx_now >= params.adx_trend_min and rising_ok and dist_in_zone and macd_strong
    if strong:
        if params.cont_rsi_min > 0 and rsi_now is not None:
            rsi_ok = (rsi_now > params.cont_rsi_min if direction == "CALL"
                      else rsi_now < 100 - params.cont_rsi_min)
            if not rsi_ok:
                threshold = params.cont_rsi_min if direction == "CALL" else 100 - params.cont_rsi_min
                op = ">" if direction == "CALL" else "<"
                return FlipDecision(None, None,
                                    f"RSI {rsi_now} doesn't confirm {direction} (need {op}{threshold:.0f}) ({diag})",
                                    metrics)
        return FlipDecision(direction, "trend", f"TREND {direction} continuation ({diag})",
                            {**metrics, "entry_kind": "trend"})
    if dist > params.atr_distance_max:
        return FlipDecision(None, None,
                            f"over-extended {dist:.2f}ATR > max {params.atr_distance_max} ({diag})", metrics)
    if not macd_strong:
        return FlipDecision(None, None, f"weak MACD gap {macd_gap_atr}<{params.cont_macd_gap_min} ({diag})", metrics)
    return FlipDecision(None, None, f"trend not strong enough ({diag})", metrics)
