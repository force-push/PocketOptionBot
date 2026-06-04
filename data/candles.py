"""Adapter: convert binaryoptionstoolsv2 candle dicts into the o/h/l/c/v
time-indexed pandas DataFrame consumed by the signal engine.

The API returns candles as a list of dicts. Common key variants seen in
different versions of the library:

    { "open": float, "high": float, "low": float, "close": float,
      "time": int/float (unix seconds), "volume": float }

or (older variants):

    { "o": float, "h": float, "l": float, "c": float,
      "t": int/float, "v": float }

This adapter is defensive about missing keys and type coercions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


# Key aliases: maps expected output column → list of possible input keys
_COLUMN_ALIASES: dict[str, list[str]] = {
    "o": ["open", "o", "Open"],
    "h": ["high", "h", "High"],
    "l": ["low", "l", "Low"],
    "c": ["close", "c", "Close"],
    "v": ["volume", "v", "vol", "Volume"],
}

_TIME_KEYS = ["time", "t", "timestamp", "Time"]


def _extract(candle: dict[str, Any], keys: list[str], default: float = 0.0) -> float:
    """Extract the first matching key from a candle dict, return default if absent."""
    for k in keys:
        if k in candle:
            try:
                return float(candle[k])
            except (TypeError, ValueError):
                pass
    return default


def _extract_time(candle: dict[str, Any]) -> datetime:
    """Extract and normalise the timestamp from a candle dict."""
    for k in _TIME_KEYS:
        if k in candle:
            raw = candle[k]
            try:
                ts = float(raw)
                # Unix seconds → datetime (UTC)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (TypeError, ValueError):
                pass
    # Fallback: current time (should not happen with real data)
    return datetime.now(tz=timezone.utc)


def candles_to_df(candles: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert a list of API candle dicts to a time-indexed o/h/l/c/v DataFrame.

    Returns an empty DataFrame if the input is empty or all rows are invalid.
    The returned DataFrame matches the shape expected by the signal engine:
        - Index: DatetimeIndex (UTC)
        - Columns: o, h, l, c, v (all float)
        - Sorted ascending by time
    """
    if not candles:
        return pd.DataFrame(columns=["o", "h", "l", "c", "v"])

    rows = []
    for candle in candles:
        if not isinstance(candle, dict):
            continue
        row = {
            "time": _extract_time(candle),
            "o": _extract(candle, _COLUMN_ALIASES["o"]),
            "h": _extract(candle, _COLUMN_ALIASES["h"]),
            "l": _extract(candle, _COLUMN_ALIASES["l"]),
            "c": _extract(candle, _COLUMN_ALIASES["c"]),
            "v": _extract(candle, _COLUMN_ALIASES["v"]),
        }
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["o", "h", "l", "c", "v"])

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()

    # Ensure all value columns are float
    for col in ["o", "h", "l", "c", "v"]:
        df[col] = df[col].astype(float)

    return df
