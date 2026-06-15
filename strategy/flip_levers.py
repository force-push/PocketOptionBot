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
from typing import TYPE_CHECKING

from config.settings import settings

if TYPE_CHECKING:
    from strategy.flip_strategy import FlipParams

LEVERS_PATH = "data/flip_levers.json"

# The tunable surface. Keys map 1:1 onto FlipParams fields (+ are recorded per
# trade). Defaults come from settings so an absent file = current behaviour.
_LEVER_KEYS = (
    "st_period", "st_multiplier", "flip_window_bars",
    "adx_flip_min", "adx_trend_min", "adx_max",
    "require_adx_rising", "atr_distance_min", "atr_distance_max",
    "cont_macd_gap_min", "cont_rsi_min",
    # flip wait-and-confirm
    "flip_confirm_bars", "flip_gap_expansion_min",
    "flip_adx_dead_lo", "flip_adx_dead_hi",
    # moderate-volatility regime gate
    "bb_width_min", "bb_width_max",
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
        "atr_distance_max": 999.0,   # no cap by default; tune via levers file
        "cont_macd_gap_min": settings.cont_macd_gap_min,
        "cont_rsi_min": 0.0,         # disabled by default; tune via levers file
        "flip_confirm_bars": 1,      # 1 = enter at the turn (legacy); raise to wait for confirmation
        "flip_gap_expansion_min": 0.0,  # disabled by default (capture-only); tune via levers file
        "flip_adx_dead_lo": 0.0,     # disabled by default; tune via levers file
        "flip_adx_dead_hi": 0.0,
        "bb_width_min": 0.0,         # disabled by default; tune via levers file
        "bb_width_max": 0.0,
    }


def build_flip_params(levers: dict) -> "FlipParams":
    """Construct FlipParams from a levers dict.

    Uses _LEVER_KEYS as the authoritative list of tunable fields so that adding
    a new key to _LEVER_KEYS automatically wires it into FlipParams everywhere —
    no call-site updates needed.  Non-tunable fields (macd_fast/slow/signal,
    adx_period, rsi_period, bb_period, min_candles) keep their FlipParams defaults.
    """
    from strategy.flip_strategy import FlipParams  # local import avoids circular dep
    return FlipParams(**{k: levers[k] for k in _LEVER_KEYS if k in levers})


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
