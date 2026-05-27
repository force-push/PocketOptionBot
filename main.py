"""Entry point for the PocketOption trading bot."""

import asyncio
from pathlib import Path

from broker.connector import CDPConnector
from broker.executor import TradeExecutor
from broker.scraper import PocketOptionScraper
from config.settings import settings, TradeMode
from data.feed import PriceFeed
from signals.bollinger import BollingerSignal
from signals.candle_pattern import CandlePatternSignal
from signals.confluence import ConfluenceEngine
from signals.ema_cross import EMASignal
from signals.macd import MACDSignal
from signals.rsi import RSISignal
from strategy.manager import StrategyManager
from strategy.risk import RiskManager
from utils.dashboard import Dashboard
from utils.logger import setup_logger, log

# ────────────────────────────────────────────────────────────────


async def main():
    """Initialize bot and start trading loop."""

    # Setup
    project_root = Path(__file__).parent
    setup_logger(project_root, level="INFO")

    log.info("╔════════════════════════════════════════╗")
    log.info("║  PocketOption Trading Bot v0.1.0      ║")
    log.info("║  Mode: %s                              ║", settings.trade_mode)
    log.info("╚════════════════════════════════════════╝")

    # ─── SAFETY CHECK ──────────────────────────────────────────

    if settings.trade_mode == TradeMode.LIVE:
        log.critical("⚠️  LIVE TRADING MODE ENABLED ⚠️")
        log.critical("   Only proceed if you have verified:")
        log.critical("   1. This code has been thoroughly tested in DEMO")
        log.critical("   2. You understand the risks")
        log.critical("   3. You can afford to lose all capital risked")
        log.critical("")
        # In a real deployment, you'd require explicit user confirmation here
        # For now, we log it prominently but continue.
        await asyncio.sleep(3)
    else:
        log.info("✓ DEMO mode active — no real trades will be placed")

    # ─── CONNECT ───────────────────────────────────────────────

    log.info("Connecting to PocketOption via CDP...")
    connector = CDPConnector(settings.cdp_url)
    try:
        page = await connector.connect()
        log.info("✓ CDP connection established")
    except ConnectionError as e:
        log.error(f"Failed to connect: {e}")
        log.error("Ensure Chrome is running with: --remote-debugging-port=9222")
        return

    # ─── INITIALIZE COMPONENTS ────────────────────────────────

    scraper = PocketOptionScraper(page)
    data_feed = PriceFeed(scraper)
    risk_manager = RiskManager(
        max_trades_per_hour=settings.max_trades_per_hour,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        cooldown_after_loss_seconds=settings.cooldown_after_loss_seconds,
        trade_amount=settings.trade_amount,
        min_balance_multiplier=settings.min_balance_multiplier,
    )
    executor = TradeExecutor(page, scraper, dry_run=settings.dry_run)

    # Initialize signals
    signals = [
        RSISignal(period=14),
        MACDSignal(fast=12, slow=26, signal=9),
        BollingerSignal(period=20, std_dev=2.0),
        EMASignal(fast=9, slow=21),
        CandlePatternSignal(),
    ]
    confluence_engine = ConfluenceEngine(signals)

    strategy_manager = StrategyManager(
        data_feed=data_feed,
        confluence_engine=confluence_engine,
        risk_manager=risk_manager,
        executor=executor,
        scraper=scraper,
    )

    dashboard = Dashboard()

    # ─── START LOOPS ───────────────────────────────────────────

    log.info("Starting price feed and strategy loops...")
    feed_task = asyncio.create_task(data_feed.start())
    strategy_task = asyncio.create_task(strategy_manager.run())

    try:
        await asyncio.gather(feed_task, strategy_task)
    except KeyboardInterrupt:
        log.info("Shutting down...")
        feed_task.cancel()
        strategy_task.cancel()
        try:
            await asyncio.gather(feed_task, strategy_task)
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
