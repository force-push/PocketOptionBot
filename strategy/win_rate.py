"""Win-rate tracker: per-(pair, direction, expiry-bucket) win/loss counts.

Persisted to data/win_rates.json. Cold-start behavior: when n < min_samples
the gate returns True (pass) so statistics can warm up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

from utils.logger import log

# Default persistence path (relative to project root)
_DEFAULT_JSON_PATH = Path(__file__).parent.parent / "data" / "win_rates.json"

# Valid outcome values
_OUTCOMES = {"win", "loss", "draw"}


def _expiry_bucket(expiry_seconds: int) -> str:
    """Map expiry seconds to a coarse bucket label for keying.

    Buckets: 60s → "1m", 120s → "2m", 300s → "5m", etc.
    """
    minutes = expiry_seconds // 60
    remainder = expiry_seconds % 60
    if remainder == 0 and minutes > 0:
        return f"{minutes}m"
    return f"{expiry_seconds}s"


class WinRateTracker:
    """Track per-(pair, direction, expiry-bucket) win/loss counts.

    Key is a tuple (pair, direction, expiry_bucket) but stored in JSON as a
    string "|" separator.

    Draws are recorded in ``draws`` but do not count towards win or loss
    (they don't affect the rate calculation).
    """

    def __init__(self, json_path: Optional[Path] = None) -> None:
        self._path = Path(json_path) if json_path else _DEFAULT_JSON_PATH
        # {key_str: {"wins": int, "losses": int, "draws": int}}
        self._data: dict[str, dict[str, int]] = {}
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _key_str(self, pair: str, direction: str, expiry_seconds: int) -> str:
        bucket = _expiry_bucket(expiry_seconds)
        return f"{pair}|{direction}|{bucket}"

    def _load(self) -> None:
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    self._data = json.load(fh)
                log.debug("WinRateTracker loaded from %s", self._path)
            except Exception as exc:
                log.warning("WinRateTracker: could not load %s: %s — starting fresh", self._path, exc)
                self._data = {}

    @property
    def has_data(self) -> bool:
        """True if any records have been loaded or recorded."""
        return bool(self._data)

    def save(self) -> None:
        """Persist current state to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
            log.debug("WinRateTracker saved to %s", self._path)
        except Exception as exc:
            log.error("WinRateTracker: could not save to %s: %s", self._path, exc)

    # ── public API ───────────────────────────────────────────────────────────

    def record(self, pair: str, direction: str, expiry_seconds: int, outcome: str) -> None:
        """Record a trade outcome.

        Args:
            pair:           API symbol, e.g. "EURUSD_otc".
            direction:      "CALL" or "PUT".
            expiry_seconds: Trade expiry in seconds.
            outcome:        "win", "loss", or "draw".
                            Draws are stored but not counted for the rate.
        """
        outcome = outcome.lower()
        if outcome not in _OUTCOMES:
            log.warning("WinRateTracker.record: unknown outcome %r (must be win/loss/draw)", outcome)
            return

        key = self._key_str(pair, direction, expiry_seconds)
        if key not in self._data:
            self._data[key] = {"wins": 0, "losses": 0, "draws": 0}

        if outcome == "win":
            self._data[key]["wins"] += 1
        elif outcome == "loss":
            self._data[key]["losses"] += 1
        elif outcome == "draw":
            self._data[key]["draws"] += 1

        self.save()
        log.debug(
            "WinRateTracker.record: %s → %s (now %s)",
            key, outcome, self._data[key],
        )

    def seed_from_po_history(self, deals: list[dict], default_expiry_seconds: int = 30) -> int:
        """Seed the tracker from PocketOption closed-deal history.

        Only seeds when ``self._data`` is empty — skips entirely if any records
        already exist, to avoid double-counting on subsequent runs.

        For each deal: maps direction ("buy"→"CALL", "sell"→"PUT"), validates the
        result ("win"/"loss"/"draw"), and derives expiry from the deal's
        ``timestamp`` dict (``closed``-``created``, clamped to 5–3600s) falling
        back to ``default_expiry_seconds``. Calls ``record()`` per valid deal.

        Returns the count of seeded records. Saves once at the end if count > 0.
        """
        if self._data:
            log.debug("WinRateTracker.seed_from_po_history: data not empty — skipping seed")
            return 0

        seeded = 0
        for deal in deals:
            try:
                asset = deal.get("asset")
                raw_dir = deal.get("direction")
                result = deal.get("result")
                if not asset or not raw_dir or not result:
                    continue
                direction = {"buy": "CALL", "sell": "PUT"}.get(str(raw_dir).lower())
                if direction is None:
                    continue
                outcome = str(result).lower()
                if outcome not in _OUTCOMES:
                    continue

                expiry_seconds = default_expiry_seconds
                ts = deal.get("timestamp")
                if isinstance(ts, dict):
                    created = ts.get("created", ts.get("open"))
                    closed = ts.get("closed", ts.get("close"))
                    if isinstance(created, int) and isinstance(closed, int):
                        duration = closed - created
                        if 5 <= duration <= 3600:
                            expiry_seconds = duration

                self.record(asset, direction, expiry_seconds, outcome)
                seeded += 1
            except Exception as exc:
                log.debug("WinRateTracker.seed_from_po_history: skipping deal: {}", exc)
                continue

        if seeded > 0:
            self.save()
        log.info("WinRateTracker.seed_from_po_history: seeded {} records", seeded)
        return seeded

    def rate(self, pair: str, direction: str, expiry_seconds: int) -> Tuple[float, int]:
        """Return (win_rate, n) for the given key.

        win_rate is 0.0–1.0; n includes wins + losses + draws (draws count as wins).
        Returns (0.0, 0) if no data exists.
        """
        key = self._key_str(pair, direction, expiry_seconds)
        entry = self._data.get(key, {})
        wins = int(entry.get("wins", 0))
        losses = int(entry.get("losses", 0))
        draws = int(entry.get("draws", 0))
        n = wins + losses + draws
        if n == 0:
            return 0.0, 0
        return (wins + draws) / n, n

    def pair_rate(self, pair: str) -> Tuple[float, int]:
        """Return (win_rate, n) aggregated across ALL of a pair's keys.

        Sums wins/losses over every (direction, expiry-bucket) entry whose key
        starts with ``pair|``. Used to rank pairs by overall historical
        performance (direction/expiry-agnostic). Returns (0.0, 0) if no data.
        """
        prefix = f"{pair}|"
        wins = losses = draws = 0
        for key, entry in self._data.items():
            if key.startswith(prefix):
                wins += int(entry.get("wins", 0))
                losses += int(entry.get("losses", 0))
                draws += int(entry.get("draws", 0))
        n = wins + losses + draws
        if n == 0:
            return 0.0, 0
        return (wins + draws) / n, n

    def passes(
        self,
        pair: str,
        direction: str,
        expiry_seconds: int,
        min_rate: float,
        min_samples: int,
    ) -> bool:
        """Return True if the tracked win rate meets the threshold.

        Cold start: if n < min_samples returns True so stats can warm up.
        """
        win_rate, n = self.rate(pair, direction, expiry_seconds)
        if n < min_samples:
            log.debug(
                "WinRateTracker.passes: %s|%s cold-start (n=%d < %d) — pass",
                pair, direction, n, min_samples,
            )
            return True
        result = win_rate >= min_rate
        log.debug(
            "WinRateTracker.passes: %s|%s rate=%.2f n=%d min_rate=%.2f → %s",
            pair, direction, win_rate, n, min_rate, result,
        )
        return result
