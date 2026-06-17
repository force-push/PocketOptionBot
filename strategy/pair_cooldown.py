"""Per-pair post-loss cooldown.

Data finding (2026-06-15): binary-option outcomes are positively autocorrelated
per pair — trades placed <60s after a loss on the same pair win only ~42% of the
time (vs ~53% after a win). Skipping that window flipped the allowed-set backtest
from −$471 to +$107. This module tracks the last loss time per pair so the poll
loop and FocusSession can skip a pair while it's "cooling off" and trade others
instead (no idle time — the scan/rotation just moves to the next-best pair).

State is persisted to data/pair_cooldown.json so a bot restart does not reset
the cooldown — previously the in-memory dict was wiped on restart, letting the
bot immediately re-enter a pair that had just lost (33.9% WR on those trades,
2026-06-17 finding from analyze_failures).

``now`` is injectable for deterministic tests; it defaults to wall-clock time
(time.time). When seconds is provided (test mode) disk persistence is disabled.
"""
from __future__ import annotations

import json
import os
import time

_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "pair_cooldown.json")


class PairCooldown:
    def __init__(self, seconds: float | None = None, state_file: str | None = None) -> None:
        # pair → wall-clock timestamp (time.time()) of its last losing trade
        self._last_loss: dict[str, float] = {}
        # Optional fixed duration (tests). When None, read from settings per check.
        self._fixed_seconds = seconds
        # Disable disk persistence in test mode (seconds provided) or explicit override
        self._state_file: str | None = None if seconds is not None else (state_file or _STATE_FILE)
        if self._state_file:
            self._load()

    def _load(self) -> None:
        try:
            if not self._state_file or not os.path.exists(self._state_file):
                return
            with open(self._state_file) as f:
                data = json.load(f)
            now = time.time()
            # Keep entries that are still within a generous 1h window on load
            # (prunes truly ancient entries while preserving active cooldowns)
            self._last_loss = {
                p: float(t)
                for p, t in data.items()
                if isinstance(t, (int, float)) and 0 <= now - float(t) < 3600
            }
        except Exception:
            pass

    def _save(self) -> None:
        if not self._state_file:
            return
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            tmp = self._state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._last_loss, f)
            os.replace(tmp, self._state_file)
        except Exception:
            pass

    def _seconds(self) -> float:
        if self._fixed_seconds is not None:
            return float(self._fixed_seconds)
        from config.settings import settings
        return float(getattr(settings, "post_loss_pair_cooldown_seconds", 0) or 0)

    def record_loss(self, pair: str, now: float | None = None) -> None:
        if not pair:
            return
        self._last_loss[pair] = time.time() if now is None else now
        self._save()

    def is_cooling(self, pair: str, now: float | None = None) -> bool:
        secs = self._seconds()
        if secs <= 0:
            return False
        t = self._last_loss.get(pair)
        if t is None:
            return False
        clock = time.time() if now is None else now
        return 0 <= (clock - t) < secs

    def cooling(self, now: float | None = None) -> set[str]:
        """Return the set of pairs currently cooling (for logging/filters)."""
        secs = self._seconds()
        if secs <= 0:
            return set()
        clock = time.time() if now is None else now
        return {p for p, t in self._last_loss.items() if 0 <= (clock - t) < secs}
