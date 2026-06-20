"""Martingale stake manager: per-pair loss-streak doubling.

Only doubles when the pair's live WR is above the break-even threshold
and sufficient samples exist. Resets to base stake on any win.
"""

from __future__ import annotations

from utils.logger import log


class MartingaleTracker:
    """Track per-pair consecutive loss streaks and return scaled stakes.

    Rules:
    - After a loss on pair P: next stake on P = base × 2^(loss_streak).
    - After a win on pair P: streak resets; next stake = base.
    - Doubling is gated on pair WR: only doubles if live WR >= min_pair_wr
      AND n_samples >= min_wr_samples.  If gate fails, returns base_stake.
    - Streak is capped at max_level: stake never exceeds base × 2^max_level.
    - Balance safety: if doubled stake > balance / min_balance_multiplier,
      returns base_stake (can't afford the double, skip martingale).
    """

    def __init__(
        self,
        max_level: int = 3,
        min_pair_wr: float = 0.521,
        min_wr_samples: int = 10,
    ) -> None:
        self.max_level = max_level
        self.min_pair_wr = min_pair_wr
        self.min_wr_samples = min_wr_samples
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
    ) -> float:
        """Return the stake for this pair's next trade.

        Returns base_stake when no doubling applies; otherwise base × 2^level.
        """
        level = min(self._streak.get(pair, 0), self.max_level)
        if level == 0:
            return base_stake

        # Gate: only double on confirmed positive-EV pairs
        if n_samples < self.min_wr_samples or pair_wr < self.min_pair_wr:
            log.debug(
                "Martingale {}: level={} but WR gate failed (wr={:.3f} n={}) — using base",
                pair, level, pair_wr, n_samples,
            )
            return base_stake

        doubled = base_stake * (2 ** level)

        # Balance safety: can't bet more than balance / multiplier
        if balance > 0:
            max_affordable = balance / min_balance_multiplier
            if doubled > max_affordable:
                log.info(
                    "Martingale {}: level={} stake ${:.2f} exceeds balance floor — using base ${:.2f}",
                    pair, level, doubled, base_stake,
                )
                return base_stake

        log.info(
            "Martingale {}: level={} ({}× base) → stake ${:.2f}  [wr={:.1f}% n={}]",
            pair, level, 2 ** level, doubled, pair_wr * 100, n_samples,
        )
        return doubled

    def record_outcome(self, pair: str, is_win: bool) -> None:
        """Update the streak for this pair after a resolved trade."""
        if is_win:
            if pair in self._streak:
                log.info("Martingale {}: WIN — streak reset (was level {})", pair, self._streak[pair])
                del self._streak[pair]
        else:
            self._streak[pair] = self._streak.get(pair, 0) + 1
            level = min(self._streak[pair], self.max_level)
            log.info(
                "Martingale {}: LOSS — streak={} (level={}, next mult={}×)",
                pair, self._streak[pair], level, 2 ** level,
            )

    def current_level(self, pair: str) -> int:
        return min(self._streak.get(pair, 0), self.max_level)

    def state(self) -> dict[str, int]:
        """Active streaks for all pairs (raw counts, not capped at max_level)."""
        return dict(self._streak)
