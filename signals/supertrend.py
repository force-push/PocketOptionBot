"""Supertrend indicator — standard trend-state flip implementation.

Supertrend plots an ATR-based band that sits *below* price in an uptrend and
*above* price in a downtrend, flipping when price closes through the active
band. The flip is the platform's green "Buy" / red "Sell" label.

This module exposes a pure helper, ``compute_supertrend``, returning the
Supertrend line and a per-bar trend state (+1 up / −1 down). Both the
``SupertrendSignal`` (confluence/dashboard) and ``strategy/flip_strategy`` use
it so they agree exactly on flips.

The previous implementation used the midpoint of the two bands (`price >
midpoint = CALL`), which is *not* Supertrend and never produced true flips — see
git history. This replaces it with the conventional carry-forward band + trend
algorithm.
"""

import numpy as np
import pandas as pd

from signals.base import BaseSignal, SignalResult


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-smoothed Average True Range."""
    high, low, close = df["h"], df["l"], df["c"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    # Wilder's RMA = EMA with alpha = 1/period.
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def compute_supertrend(
    df: pd.DataFrame, period: int = 10, multiplier: float = 3.0
) -> tuple[pd.Series, pd.Series]:
    """Return (supertrend_line, trend) where trend is +1 (up/CALL) or −1 (down/PUT).

    Standard algorithm: ATR bands with carry-forward final bands, trend flips
    when close crosses the active final band.
    """
    n = len(df)
    hl2 = (df["h"] + df["l"]) / 2.0
    atr = _atr(df, period)
    upper = (hl2 + multiplier * atr).to_numpy(dtype=float)
    lower = (hl2 - multiplier * atr).to_numpy(dtype=float)
    close = df["c"].to_numpy(dtype=float)

    final_ub = np.full(n, np.nan)
    final_lb = np.full(n, np.nan)
    st = np.full(n, np.nan)
    trend = np.ones(n, dtype=int)

    for i in range(n):
        if i == 0 or not (np.isfinite(upper[i]) and np.isfinite(lower[i])):
            final_ub[i] = upper[i]
            final_lb[i] = lower[i]
            st[i] = lower[i]
            trend[i] = 1
            continue

        final_ub[i] = (
            upper[i] if (upper[i] < final_ub[i - 1] or close[i - 1] > final_ub[i - 1])
            else final_ub[i - 1]
        )
        final_lb[i] = (
            lower[i] if (lower[i] > final_lb[i - 1] or close[i - 1] < final_lb[i - 1])
            else final_lb[i - 1]
        )

        # Trend continues unless price closes through the opposite final band.
        if trend[i - 1] == 1:
            trend[i] = -1 if close[i] < final_lb[i] else 1
        else:
            trend[i] = 1 if close[i] > final_ub[i] else -1

        st[i] = final_lb[i] if trend[i] == 1 else final_ub[i]

    return pd.Series(st, index=df.index), pd.Series(trend, index=df.index)


class SupertrendSignal(BaseSignal):
    """Supertrend trend-following signal (true flip logic)."""

    name = "Supertrend"
    weight = 0.15

    def __init__(self, period: int = 10, multiplier: float = 3.0):
        self.period = period
        self.multiplier = multiplier

    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        try:
            if len(df) < self.period * 2:
                return SignalResult(
                    name=self.name, direction=None, confidence=0.0,
                    reason=f"Insufficient data: {len(df)} < {self.period * 2}",
                )

            st, trend = compute_supertrend(df, self.period, self.multiplier)
            t = int(trend.iloc[-1])
            t_prev = int(trend.iloc[-2]) if len(trend) > 1 else t
            price = float(df["c"].iloc[-1])
            st_val = float(st.iloc[-1])
            atr = _atr(df, self.period).iloc[-1]

            if not np.isfinite(st_val) or not np.isfinite(atr) or atr == 0:
                return SignalResult(
                    name=self.name, direction=None, confidence=0.0,
                    reason="Supertrend calculation failed",
                )

            distance = abs(price - st_val) / atr if atr > 0 else 0.0
            confidence = min(1.0, distance / 3.0)
            flipped = t != t_prev
            direction = "CALL" if t == 1 else "PUT"
            kind = "flip" if flipped else "trend"
            return SignalResult(
                name=self.name, direction=direction, confidence=confidence,
                reason=(
                    f"Supertrend {direction} ({kind}): price {price:.5f} "
                    f"{'>' if t == 1 else '<'} ST {st_val:.5f} (dist={distance:.2f} ATR)"
                ),
            )
        except Exception as e:  # noqa: BLE001
            return SignalResult(
                name=self.name, direction=None, confidence=0.0,
                reason=f"Supertrend error: {e}",
            )
