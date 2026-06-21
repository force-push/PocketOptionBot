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
        self._streak: dict[str, int] = {}         # pair → consecutive loss count
        self._session_trades: dict[str, int] = {}  # pair → resolved trades this session

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
        min_session_trades: int = 3,
    ) -> float:
        """Return the stake for this pair's next trade.

        Returns base_stake when no scaling applies; otherwise base × multiplier^level.
        All tunable thresholds are keyword args — pass current settings values.
        """
        level = min(self._streak.get(pair, 0), max_level)
        if level == 0:
            return base_stake

        # Gate: pair must have enough resolved trades this session before doubling
        session_n = self._session_trades.get(pair, 0)
        if session_n < min_session_trades:
            log.debug(
                "Martingale {}: level={} but session gate failed ({}/{} trades) — using base",
                pair, level, session_n, min_session_trades,
            )
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
        """Update the streak and session trade count for this pair after a resolved trade."""
        self._session_trades[pair] = self._session_trades.get(pair, 0) + 1
        if is_win:
            if pair in self._streak:
                log.info("Martingale {}: WIN — streak reset (was level {})", pair, self._streak[pair])
                del self._streak[pair]
        else:
            current = self._streak.get(pair, 0)
            if current >= max_level:
                # Already at max level and lost again — reset rather than staying capped.
                # Keeping max-level stake indefinitely on a losing pair compounds damage.
                del self._streak[pair]
                log.info(
                    "Martingale {}: LOSS at max level {} — RESET to base (streak was {})",
                    pair, max_level, current,
                )
            else:
                self._streak[pair] = current + 1
                level = min(self._streak[pair], max_level)
                log.info(
                    "Martingale {}: LOSS — streak={} (level={}, next stake {:.2g}× base)",
                    pair, self._streak[pair], level, multiplier ** level,
                )

    def seed_from_db(self, db_path: str, *, max_level: int = 2, lookback_hours: float = 6.0) -> None:
        """Reconstruct loss streaks and session counts from the decisions DB.

        Called on startup so a restart after a crash/reconnect picks up where the
        bot left off rather than starting every pair at level 0.

        For each pair: walk the most-recent resolved trades (newest-first) and
        count consecutive tail losses — that becomes the restored streak.
        Session trade count is set to the total resolved trades in the window.
        """
        from datetime import datetime, timezone, timedelta
        from data.decisions_store import tail_outcomes_by_pair

        since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        try:
            tails = tail_outcomes_by_pair(db_path, since_iso=since, max_per_pair=max_level + 2)
        except Exception as exc:
            log.warning("MartingaleTracker.seed_from_db failed — starting fresh: {}", exc)
            return

        restored = 0
        for pair, outcomes in tails.items():  # outcomes = newest-first
            self._session_trades[pair] = len(outcomes)
            streak = 0
            for outcome in outcomes:  # newest → oldest
                if outcome == "loss":
                    streak += 1
                else:
                    break  # hit a win/draw — streak resets here
            if streak:
                self._streak[pair] = min(streak, max_level)
                restored += 1

        log.info(
            "MartingaleTracker seeded from DB ({:.0f}h lookback): {} pairs with active streaks — {}",
            lookback_hours,
            restored,
            {p: v for p, v in self._streak.items()},
        )

    def current_level(self, pair: str, *, max_level: int = 2) -> int:
        return min(self._streak.get(pair, 0), max_level)

    def state(self) -> dict[str, int]:
        """Active streaks for all pairs (raw counts, not capped at max_level)."""
        return dict(self._streak)
