"""Per-pair post-loss cooldown.

Data finding (2026-06-15): binary-option outcomes are positively autocorrelated
per pair — trades placed <60s after a loss on the same pair win only ~42% of the
time (vs ~53% after a win). Skipping that window flipped the allowed-set backtest
from −$471 to +$107. This module tracks the last loss time per pair so the poll
loop and FocusSession can skip a pair while it's "cooling off" and trade others
instead (no idle time — the scan/rotation just moves to the next-best pair).

State only — the cooldown duration is read from settings each check so it stays
live-tunable. ``now`` is injectable for deterministic tests; it defaults to a
monotonic clock so it's immune to wall-clock jumps.
"""
from __future__ import annotations

import time


class PairCooldown:
    def __init__(self, seconds: float | None = None) -> None:
        # pair → monotonic timestamp of its last losing trade
        self._last_loss: dict[str, float] = {}
        # Optional fixed duration (tests). When None, read from settings per check.
        self._fixed_seconds = seconds

    def _seconds(self) -> float:
        if self._fixed_seconds is not None:
            return float(self._fixed_seconds)
        from config.settings import settings
        return float(getattr(settings, "post_loss_pair_cooldown_seconds", 0) or 0)

    def record_loss(self, pair: str, now: float | None = None) -> None:
        if not pair:
            return
        self._last_loss[pair] = time.monotonic() if now is None else now

    def is_cooling(self, pair: str, now: float | None = None) -> bool:
        secs = self._seconds()
        if secs <= 0:
            return False
        t = self._last_loss.get(pair)
        if t is None:
            return False
        clock = time.monotonic() if now is None else now
        return 0 <= (clock - t) < secs

    def cooling(self, now: float | None = None) -> set[str]:
        """Return the set of pairs currently cooling (for logging/filters)."""
        secs = self._seconds()
        if secs <= 0:
            return set()
        clock = time.monotonic() if now is None else now
        return {p for p, t in self._last_loss.items() if 0 <= (clock - t) < secs}
