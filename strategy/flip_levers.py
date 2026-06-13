"""Live-tunable flip-strategy levers.

The flip entry thresholds are read from ``data/flip_levers.json`` on every cycle
(mtime-cached, so it's effectively free), falling back to the ``settings``
defaults for any key the file omits or that's invalid. This lets the thresholds
be refined over time — by the monitoring loop or by hand — **without restarting
the bot**: edit the JSON, and the next scan picks it up.

The resolved lever dict is also stamped onto every DecisionRow (``flip_levers``)
so each trade records exactly which thresholds produced it, for historical review.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from config.settings import settings

LEVERS_PATH = "data/flip_levers.json"

# The tunable surface. Keys map 1:1 onto FlipParams fields (+ are recorded per
# trade). Defaults come from settings so an absent file = current behaviour.
_LEVER_KEYS = (
    "st_period", "st_multiplier", "flip_window_bars",
    "adx_flip_min", "adx_trend_min", "adx_max",
    "require_adx_rising", "atr_distance_min",
)

_lock = threading.Lock()
_cache: dict = {"sig": None, "overrides": {}}


def _defaults() -> dict:
    return {
        "st_period": settings.st_period,
        "st_multiplier": settings.st_multiplier,
        "flip_window_bars": settings.flip_window_bars,
        "adx_flip_min": settings.flip_adx_min,
        "adx_trend_min": settings.trend_adx_min,
        "adx_max": settings.flip_adx_max,
        "require_adx_rising": settings.trend_require_adx_rising,
        "atr_distance_min": settings.trend_atr_distance_min,
    }


def load_levers(path: str | None = None) -> dict:
    """Return the active levers = settings defaults overlaid with the JSON file.

    Cached by (mtime, size); re-reads only when the file changes. Unknown or
    null keys in the file are ignored. Never raises — bad file → defaults.
    """
    p = Path(path or LEVERS_PATH)
    levers = _defaults()
    if not p.exists():
        return levers
    try:
        st = p.stat()
        sig = (st.st_mtime, st.st_size)
        with _lock:
            if _cache["sig"] != sig:
                raw = json.loads(p.read_text(encoding="utf-8"))
                _cache["overrides"] = {
                    k: raw[k] for k in _LEVER_KEYS
                    if isinstance(raw, dict) and raw.get(k) is not None
                }
                _cache["sig"] = sig
            overrides = dict(_cache["overrides"])
    except Exception:
        return levers
    levers.update(overrides)
    return levers
