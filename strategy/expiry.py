"""Pure expiry/timeframe selection. PocketOption supports 5s/10s/15s/30s/1m/…"""
from __future__ import annotations


def select_expiry(default: int, allowed: tuple[int, ...], requested: int | None = None) -> int:
    """Return a valid expiry in seconds.

    If `requested` is given, snap it to the nearest allowed value; otherwise
    return `default` (which must itself be an allowed value).
    """
    if requested is None:
        return default
    return min(allowed, key=lambda a: abs(a - requested))
