"""Event-driven strategy manager.

Consumes raw Telegram signal text from a queue, runs it through the gate
pipeline, checks risk, places trades, and spawns per-trade outcome tasks
that feed results back into the tracker and risk manager.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from config.settings import settings
from telegram_feed.parser import parse_signal
from utils.logger import log


class StrategyManager:
    """Event-driven decision loop.

    Constructor args:
        signal_queue:  asyncio.Queue fed by TelegramSignalFeed
        signal_gate:   SignalGate (3 gates)
        risk_manager:  RiskManager
        api_client:    PocketOptionAPIClient
        tracker:       WinRateTracker
    """

    def __init__(
        self,
        signal_queue: asyncio.Queue,
        signal_gate,
        risk_manager,
        api_client,
        tracker,
    ) -> None:
        self._queue = signal_queue
        self._gate = signal_gate
        self._risk = risk_manager
        self._api = api_client
        self._tracker = tracker

        # Track in-flight trade tasks to cap concurrency
        self._open_trades: set[asyncio.Task] = set()

    # ──────────────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main event loop. Runs until cancelled."""
        log.info("StrategyManager started (event-driven mode)")

        try:
            while True:
                try:
                    raw_text = await self._queue.get()
                    await self._handle_raw(raw_text)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.error("StrategyManager loop error: %s", exc)

        except asyncio.CancelledError:
            log.info("StrategyManager stopped — waiting for open trades...")
            if self._open_trades:
                await asyncio.gather(*self._open_trades, return_exceptions=True)
            log.info("StrategyManager stopped cleanly")
            raise

    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_raw(self, raw_text: str) -> None:
        """Handle a single raw message string from the queue."""
        # ── Parse ─────────────────────────────────────────────────────────────
        signal = parse_signal(raw_text)
        if signal is None:
            log.debug("StrategyManager: message could not be parsed — skipped")
            return

        log.info(
            "Signal received: pair=%s direction=%s expiry=%ds stated_wr=%s",
            signal.pair,
            signal.direction,
            signal.expiry_seconds,
            f"{signal.stated_win_rate:.1%}" if signal.stated_win_rate is not None else "N/A",
        )

        # ── Gate evaluation ───────────────────────────────────────────────────
        gate_result = await self._gate.evaluate(signal)
        if not gate_result.passed:
            log.info("Signal BLOCKED by gate: %s", gate_result.reason)
            return

        log.info("Signal passed gates: %s", gate_result.reason)

        # ── Concurrency cap ───────────────────────────────────────────────────
        # Clean up completed tasks first
        self._open_trades = {t for t in self._open_trades if not t.done()}
        if len(self._open_trades) >= settings.max_open_trades:
            log.warning(
                "StrategyManager: max_open_trades=%d reached — signal skipped",
                settings.max_open_trades,
            )
            return

        # ── Risk check ────────────────────────────────────────────────────────
        balance = await self._api.balance()
        if not self._risk.is_allowed(balance):
            log.warning("Trade BLOCKED by risk manager: %s", self._risk.block_reason)
            return

        # ── Place trade ───────────────────────────────────────────────────────
        log.info(
            "Placing %s on %s (amount=%.2f expiry=%ds)",
            signal.direction, signal.pair, settings.trade_amount, signal.expiry_seconds,
        )

        if signal.direction == "CALL":
            trade_result = await self._api.buy(
                signal.pair, settings.trade_amount, signal.expiry_seconds
            )
        else:
            trade_result = await self._api.sell(
                signal.pair, settings.trade_amount, signal.expiry_seconds
            )

        if trade_result.status in ("ERROR",):
            log.error("Trade failed: %s", trade_result.error)
            return

        if trade_result.status == "DRY_RUN":
            log.info("DRY RUN — trade not placed, skipping check_win")
            return

        # ── Spawn per-trade outcome task ──────────────────────────────────────
        if trade_result.trade_id:
            task = asyncio.create_task(
                self._await_outcome(signal, trade_result)
            )
            self._open_trades.add(task)
            task.add_done_callback(self._open_trades.discard)
        else:
            log.warning("Trade placed but no trade_id returned — cannot track outcome")

    async def _await_outcome(self, signal, trade_result) -> None:
        """Wait for check_win, then record in tracker and risk manager."""
        try:
            log.info(
                "Awaiting outcome for trade_id=%s (pair=%s expiry=%ds)",
                trade_result.trade_id, signal.pair, signal.expiry_seconds,
            )
            outcome = await self._api.check_win(trade_result.trade_id)
            log.info(
                "Trade outcome: %s for %s %s trade_id=%s",
                outcome.upper(), signal.direction, signal.pair, trade_result.trade_id,
            )

            # Update win-rate tracker
            self._tracker.record(
                signal.pair, signal.direction, signal.expiry_seconds, outcome
            )

            # Update risk manager (map to WIN/LOSS/PENDING)
            risk_result = {
                "win": "WIN",
                "loss": "LOSS",
                "draw": "PENDING",  # draws don't count as win or loss
            }.get(outcome.lower(), "PENDING")

            self._risk.record_trade(
                signal.direction, settings.trade_amount, risk_result
            )

        except asyncio.CancelledError:
            log.info("Outcome task cancelled for trade_id=%s", trade_result.trade_id)
            raise
        except Exception as exc:
            log.error(
                "Error awaiting outcome for trade_id=%s: %s",
                trade_result.trade_id, exc,
            )
