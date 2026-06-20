"""Martingale stake manager: per-pair loss-streak doubling.

All tunable parameters (multiplier, max_level, WR gates) are passed at
call-time rather than stored at construction — the manager reads them
from the live settings object, so dashboard edits take effect immediately
without restarting the bot.
"""

from __future__ import annotations

from utils.logger import log


class MartingaleTracker:
    """Track per-pair consecutive loss streaks and return scaled stakes.

    Rules:
    - After a loss on pair P: next stake on P = base × multiplier^streak.
    - After a win on pair P: streak resets; next stake = base.
    - Doubling is gated on pair WR: only scales if live WR >= min_pair_wr
      AND n_samples >= min_wr_samples.  If gate fails, returns base_stake.
    - Streak is capped at max_level: stake never exceeds base × multiplier^max_level.
    - Balance safety: if scaled stake > balance / min_balance_multiplier,
      returns base_stake (can't afford the scale, skip martingale this trade).

    No tunable state is stored on the object — only the loss-streak dict.
    Pass current settings values from the caller each time.
    """

    def __init__(self) -> None:
        self._streak: dict[str, int] = {}  # pair → consecutive loss count

    # ── public API ────────────────────────────────────────────────────────────

    def get_stake(
        self,
        pair: str,
        base_stake: float,
        pair_wr: float,
        n_samples: int,
        balance: float,
        min_balance_multiplier: float,
        *,
        multiplier: float = 2.0,
        max_level: int = 2,
        min_pair_wr: float = 0.521,
        min_wr_samples: int = 10,
    ) -> float:
        """Return the stake for this pair's next trade.

        Returns base_stake when no scaling applies; otherwise base × multiplier^level.
        All tunable thresholds are keyword args — pass current settings values.
        """
        level = min(self._streak.get(pair, 0), max_level)
        if level == 0:
            return base_stake

        # Gate: only scale on confirmed positive-EV pairs
        if n_samples < min_wr_samples or pair_wr < min_pair_wr:
            log.debug(
                "Martingale {}: level={} but WR gate failed (wr={:.3f} n={}) — using base",
                pair, level, pair_wr, n_samples,
            )
            return base_stake

        scaled = base_stake * (multiplier ** level)

        # Balance safety: can't bet more than balance / min_balance_multiplier
        if balance > 0:
            max_affordable = balance / min_balance_multiplier
            if scaled > max_affordable:
                log.info(
                    "Martingale {}: level={} stake ${:.2f} exceeds balance floor — using base ${:.2f}",
                    pair, level, scaled, base_stake,
                )
                return base_stake

        log.info(
            "Martingale {}: level={} ({:.2g}× base) → stake ${:.2f}  [wr={:.1f}% n={}]",
            pair, level, multiplier ** level, scaled, pair_wr * 100, n_samples,
        )
        return scaled

    def record_outcome(self, pair: str, is_win: bool, *, max_level: int = 2, multiplier: float = 2.0) -> None:
        """Update the streak for this pair after a resolved trade."""
        if is_win:
            if pair in self._streak:
                log.info("Martingale {}: WIN — streak reset (was level {})", pair, self._streak[pair])
                del self._streak[pair]
        else:
            self._streak[pair] = self._streak.get(pair, 0) + 1
            level = min(self._streak[pair], max_level)
            log.info(
                "Martingale {}: LOSS — streak={} (level={}, next stake {:.2g}× base)",
                pair, self._streak[pair], level, multiplier ** level,
            )

    def current_level(self, pair: str, *, max_level: int = 2) -> int:
        return min(self._streak.get(pair, 0), max_level)

    def state(self) -> dict[str, int]:
        """Active streaks for all pairs (raw counts, not capped at max_level)."""
        return dict(self._streak)
