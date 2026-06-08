"""Entry point for the PocketOption trading bot (event-driven pipeline)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from config.settings import settings, TradeMode
from signals.confluence import ConfluenceEngine
from signals.ema_cross import EMASignal
from signals.macd import MACDSignal
from signals.rsi import RSISignal
from strategy.manager import StrategyManager
from strategy.risk import RiskManager
from strategy.signal_gate import SignalGate
from strategy.win_rate import WinRateTracker
from telegram_feed.client import TelegramSignalFeed
from broker.po_api import PocketOptionAPIClient
from utils.logger import setup_logger, log

# Legacy CDP modules — kept but NOT in the live path
# from broker.connector import CDPConnector
# from broker.executor import TradeExecutor
# from broker.scraper import PocketOptionScraper
# from data.feed import PriceFeed

# ──────────────────────────────────────────────────────────────────────────────


async def main() -> None:
    """Build and start the event-driven pipeline."""

    project_root = Path(__file__).parent
    setup_logger(project_root, level="INFO")

    log.info("╔════════════════════════════════════════╗")
    log.info("║  PocketOption Trading Bot v0.2.0      ║")
    log.info("║  Mode: %-30s ║", settings.trade_mode)
    log.info("╚════════════════════════════════════════╝")

    # ── LIVE mode banner ──────────────────────────────────────────────────────

    if settings.trade_mode == TradeMode.LIVE:
        log.critical("⚠️  LIVE TRADING MODE ENABLED ⚠️")
        log.critical("   Only proceed if you have verified:")
        log.critical("   1. This code has been thoroughly tested in DEMO")
        log.critical("   2. You understand the risks")
        log.critical("   3. You can afford to lose all capital risked")
        await asyncio.sleep(3)
    else:
        log.info("✓ DEMO mode active — no real trades will be placed")

    if settings.dry_run:
        log.info("✓ DRY_RUN=true — API calls will be logged but NOT executed")

    # ── Credential check ──────────────────────────────────────────────────────

    if not settings.telegram_api_id or not settings.telegram_api_hash:
        log.error(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH are not set in .env. "
            "The bot cannot connect to Telegram."
        )
        return

    if not settings.po_ssid:
        log.error(
            "PO_SSID is not set in .env. "
            "Copy the full 42[\"auth\",...] string from your browser."
        )
        return

    # ── Build components ──────────────────────────────────────────────────────

    log.info("Initializing components...")

    # Telegram feed (owns the signal queue)
    feed = TelegramSignalFeed()

    # PO API client
    api_client = PocketOptionAPIClient()
    try:
        await api_client.connect()
        log.info("✓ PocketOption API connected")
    except Exception as exc:
        log.error("Failed to connect to PocketOption API: %s", exc)
        return

    # TA signals + confluence engine (legacy path — Bollinger/CandlePattern removed)
    signals = [
        RSISignal(period=14),
        MACDSignal(fast=12, slow=26, signal=9),
        EMASignal(fast=9, slow=21),
    ]
    confluence_engine = ConfluenceEngine(signals)

    # Risk manager
    risk_manager = RiskManager(
        max_trades_per_hour=settings.max_trades_per_hour,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        cooldown_after_loss_seconds=settings.cooldown_after_loss_seconds,
        trade_amount=settings.trade_amount,
        min_balance_multiplier=settings.min_balance_multiplier,
    )

    # Win-rate tracker
    tracker = WinRateTracker()

    # Signal gate (3 gates)
    gate = SignalGate(
        confluence_engine=confluence_engine,
        tracker=tracker,
        api_client=api_client,
    )

    # Strategy manager (event-driven)
    strategy_manager = StrategyManager(
        signal_queue=feed.queue,
        signal_gate=gate,
        risk_manager=risk_manager,
        api_client=api_client,
        tracker=tracker,
    )

    # ── Start ─────────────────────────────────────────────────────────────────

    log.info("Starting Telegram feed and strategy loop...")

    feed_task = asyncio.create_task(feed.start())
    strategy_task = asyncio.create_task(strategy_manager.run())

    try:
        await asyncio.gather(feed_task, strategy_task)
    except KeyboardInterrupt:
        log.info("Keyboard interrupt — shutting down...")
        feed_task.cancel()
        strategy_task.cancel()
        try:
            await asyncio.gather(feed_task, strategy_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass
    except asyncio.CancelledError:
        feed_task.cancel()
        strategy_task.cancel()
        try:
            await asyncio.gather(feed_task, strategy_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
