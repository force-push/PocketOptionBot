"""Signal gate: runs the three quality gates and returns pass/fail + reason.

Gate 1: signal.stated_win_rate >= settings.min_channel_win_rate
Gate 2: WinRateTracker.passes(...) — skipped cold-start
Gate 3: ConfluenceEngine.score(candles) direction == signal.direction
         AND score >= settings.min_confluence_score
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config.settings import settings
from data.candles import candles_to_df
from signals.confluence import ConfluenceEngine
from strategy.win_rate import WinRateTracker
from telegram_feed.parser import TelegramSignal
from utils.logger import log


@dataclass(frozen=True)
class GateResult:
    """Result of the three-gate evaluation."""

    passed: bool
    reason: str


class SignalGate:
    """Evaluate a TelegramSignal through all three quality gates.

    Inject dependencies:
        confluence_engine: ConfluenceEngine (reuses the existing TA signals)
        tracker:           WinRateTracker
        api_client:        PocketOptionAPIClient (for get_candles)
    """

    def __init__(
        self,
        confluence_engine: ConfluenceEngine,
        tracker: WinRateTracker,
        api_client,  # PocketOptionAPIClient — avoid circular import with string type
    ) -> None:
        self._confluence = confluence_engine
        self._tracker = tracker
        self._api = api_client

    async def evaluate(self, signal: TelegramSignal) -> GateResult:
        """Run all three gates; return the first failure or a pass.

        Never raises — errors in individual gates are caught and treated as
        gate failures.
        """
        try:
            return await self._evaluate_inner(signal)
        except Exception as exc:
            msg = f"SignalGate exception: {exc}"
            log.error(msg)
            return GateResult(passed=False, reason=msg)

    async def _evaluate_inner(self, signal: TelegramSignal) -> GateResult:
        # ── Gate 1: stated win rate ──────────────────────────────────────────
        if signal.stated_win_rate is None:
            reason = (
                "Gate 1 FAIL: no stated win rate in signal "
                "(fail-closed; po_broker_bot may not include it)"
            )
            log.info(reason)
            return GateResult(passed=False, reason=reason)

        if signal.stated_win_rate < settings.min_channel_win_rate:
            reason = (
                f"Gate 1 FAIL: stated win rate {signal.stated_win_rate:.1%} "
                f"< threshold {settings.min_channel_win_rate:.1%}"
            )
            log.info(reason)
            return GateResult(passed=False, reason=reason)

        log.debug(
            "Gate 1 PASS: stated win rate %s", f"{signal.stated_win_rate:.1%}"
        )

        # ── Gate 2: tracked win rate ─────────────────────────────────────────
        if not self._tracker.passes(
            signal.pair,
            signal.direction,
            signal.expiry_seconds,
            settings.min_tracked_win_rate,
            settings.min_tracked_samples,
        ):
            win_rate, n = self._tracker.rate(
                signal.pair, signal.direction, signal.expiry_seconds
            )
            reason = (
                f"Gate 2 FAIL: tracked win rate {win_rate:.1%} (n={n}) "
                f"< threshold {settings.min_tracked_win_rate:.1%}"
            )
            log.info(reason)
            return GateResult(passed=False, reason=reason)

        log.debug("Gate 2 PASS: tracked win rate")

        # ── Gate 3: TA confluence ────────────────────────────────────────────
        try:
            candle_list = await self._api.get_candles(
                signal.pair,
                period=signal.expiry_seconds,
                count=settings.history_length,
            )
        except Exception as exc:
            reason = f"Gate 3 FAIL: could not fetch candles: {exc}"
            log.error(reason)
            return GateResult(passed=False, reason=reason)

        df = candles_to_df(candle_list)

        if df.empty or len(df) < 5:
            reason = (
                f"Gate 3 FAIL: insufficient candle data "
                f"({len(df)} candles, need ≥5)"
            )
            log.info(reason)
            return GateResult(passed=False, reason=reason)

        confluence = await self._confluence.score(df)

        if confluence.direction != signal.direction:
            reason = (
                f"Gate 3 FAIL: TA confluence direction={confluence.direction!r} "
                f"disagrees with signal direction={signal.direction!r} "
                f"(score={confluence.score:.2f})"
            )
            log.info(reason)
            return GateResult(passed=False, reason=reason)

        if confluence.score < settings.min_confluence_score:
            reason = (
                f"Gate 3 FAIL: confluence score {confluence.score:.2f} "
                f"< threshold {settings.min_confluence_score:.2f}"
            )
            log.info(reason)
            return GateResult(passed=False, reason=reason)

        log.debug(
            "Gate 3 PASS: confluence %s score=%.2f",
            confluence.direction, confluence.score,
        )

        return GateResult(
            passed=True,
            reason=(
                f"All gates passed — stated_wr={signal.stated_win_rate:.1%} "
                f"confluence={confluence.direction} score={confluence.score:.2f}"
            ),
        )
