"""Per-pair cooldowns: post-loss (short) and performance-based (long).

Short cooldown (post_loss_pair_cooldown_seconds, default 120s):
  After any single loss on a pair, skip it for the cooldown window. Data finding
  (2026-06-15): trades <60s after a loss win only ~42% vs ~53% after a win.

Long cooldown (perf_cooldown_hours, default 12h):
  If a pair's rolling win-rate over the last perf_cooldown_window_hours falls below
  perf_cooldown_max_wr after at least perf_cooldown_min_trades, it is benched for
  perf_cooldown_hours. This replaces permanent blocklist additions for pairs that
  underperform repeatedly — they can recover once conditions change.

Both states are persisted to disk so restarts don't reset active cooldowns.
``now`` is injectable for deterministic tests. When ``seconds`` is provided
(test mode) disk persistence is disabled.
"""
from __future__ import annotations

import json
import os
import time

_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "pair_cooldown.json")
_PERF_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "pair_perf_cooldown.json")


class PairCooldown:
    def __init__(
        self,
        seconds: float | None = None,
        state_file: str | None = None,
        perf_state_file: str | None = None,
    ) -> None:
        self._last_loss: dict[str, float] = {}
        self._fixed_seconds = seconds
        persist = seconds is None  # test mode disables disk I/O
        self._state_file: str | None = (state_file or _STATE_FILE) if persist else None
        self._perf_state_file: str | None = (perf_state_file or _PERF_STATE_FILE) if persist else None

        # Performance cooldown: pair → expiry timestamp (persisted)
        self._perf_until: dict[str, float] = {}
        # Rolling outcome buffer: pair → [(timestamp, is_win), ...] (in-memory only)
        self._recent: dict[str, list[tuple[float, bool]]] = {}

        if self._state_file:
            self._load()
        if self._perf_state_file:
            self._load_perf()

    # ── short cooldown persistence ────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if not self._state_file or not os.path.exists(self._state_file):
                return
            with open(self._state_file) as f:
                data = json.load(f)
            now = time.time()
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

    # ── performance cooldown persistence ─────────────────────────────────────

    def _load_perf(self) -> None:
        try:
            if not self._perf_state_file or not os.path.exists(self._perf_state_file):
                return
            with open(self._perf_state_file) as f:
                data = json.load(f)
            now = time.time()
            self._perf_until = {
                p: float(t)
                for p, t in data.items()
                if isinstance(t, (int, float)) and float(t) > now
            }
        except Exception:
            pass

    def _save_perf(self) -> None:
        if not self._perf_state_file:
            return
        try:
            os.makedirs(os.path.dirname(self._perf_state_file), exist_ok=True)
            tmp = self._perf_state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._perf_until, f)
            os.replace(tmp, self._perf_state_file)
        except Exception:
            pass

    # ── settings helpers ──────────────────────────────────────────────────────

    def _seconds(self) -> float:
        if self._fixed_seconds is not None:
            return float(self._fixed_seconds)
        from config.settings import settings
        return float(getattr(settings, "post_loss_pair_cooldown_seconds", 0) or 0)

    def _perf_cfg(self) -> tuple[int, float, float, float]:
        """(min_trades, max_wr, window_secs, cooldown_secs)"""
        if self._fixed_seconds is not None:
            return 3, 0.40, 3 * 3600, 12 * 3600
        from config.settings import settings
        min_t = int(getattr(settings, "perf_cooldown_min_trades", 5) or 5)
        max_wr = float(getattr(settings, "perf_cooldown_max_wr", 0.40) or 0.40)
        win_h = float(getattr(settings, "perf_cooldown_window_hours", 3.0) or 3.0)
        cd_h = float(getattr(settings, "perf_cooldown_hours", 12.0) or 12.0)
        return min_t, max_wr, win_h * 3600, cd_h * 3600

    # ── public API ────────────────────────────────────────────────────────────

    def record_loss(self, pair: str, now: float | None = None) -> None:
        if not pair:
            return
        self._last_loss[pair] = time.time() if now is None else now
        self._save()

    def record_outcome(self, pair: str, is_win: bool, now: float | None = None) -> bool:
        """Record a trade outcome; return True if this triggered a 12h perf cooldown."""
        if not pair:
            return False
        clock = time.time() if now is None else now
        min_trades, max_wr, window_secs, cooldown_secs = self._perf_cfg()

        buf = self._recent.setdefault(pair, [])
        buf.append((clock, is_win))
        cutoff = clock - window_secs
        self._recent[pair] = [(t, w) for t, w in buf if t >= cutoff]

        recent = self._recent[pair]
        if len(recent) >= min_trades:
            wr = sum(1 for _, w in recent if w) / len(recent)
            if wr < max_wr:
                self._perf_until[pair] = clock + cooldown_secs
                self._save_perf()
                return True
        return False

    def is_cooling(self, pair: str, now: float | None = None) -> bool:
        clock = time.time() if now is None else now
        # Short post-loss cooldown
        secs = self._seconds()
        if secs > 0:
            t = self._last_loss.get(pair)
            if t is not None and 0 <= (clock - t) < secs:
                return True
        # Long performance cooldown
        until = self._perf_until.get(pair)
        if until is not None and clock < until:
            return True
        return False

    def cooling_reason(self, pair: str, now: float | None = None) -> str | None:
        """Human-readable reason for why a pair is cooling, or None."""
        clock = time.time() if now is None else now
        secs = self._seconds()
        if secs > 0:
            t = self._last_loss.get(pair)
            if t is not None and 0 <= (clock - t) < secs:
                return f"post-loss {int(secs - (clock - t))}s left"
        until = self._perf_until.get(pair)
        if until is not None and clock < until:
            h = (until - clock) / 3600
            return f"perf-cooldown {h:.1f}h remaining"
        return None

    def cooling(self, now: float | None = None) -> set[str]:
        """All pairs currently cooling under either cooldown type."""
        clock = time.time() if now is None else now
        result: set[str] = set()
        secs = self._seconds()
        if secs > 0:
            result.update(p for p, t in self._last_loss.items() if 0 <= (clock - t) < secs)
        result.update(p for p, until in self._perf_until.items() if clock < until)
        return result
