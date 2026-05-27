"""Main strategy manager: decision loop."""

import asyncio

from config.settings import settings
from utils.logger import log


class StrategyManager:
    """Main trading loop."""

    def __init__(self, data_feed, confluence_engine, risk_manager, executor, scraper):
        self.data_feed = data_feed
        self.confluence_engine = confluence_engine
        self.risk_manager = risk_manager
        self.executor = executor
        self.scraper = scraper

    async def run(self) -> None:
        """Main trading loop. Runs forever until cancelled."""
        log.info("Strategy Manager started")

        try:
            while True:
                try:
                    # Wait for a new candle
                    await asyncio.sleep(settings.candle_interval_seconds)

                    df = self.data_feed.df
                    if df.empty or len(df) < 5:
                        log.debug(f"Skipping: insufficient history ({len(df)} candles)")
                        continue

                    # Score signals
                    result = await self.confluence_engine.score(df)

                    # Check if we should trade
                    if result.score < settings.min_confluence_score:
                        log.debug(
                            f"Score too low: {result.score:.2f} < {settings.min_confluence_score:.2f}"
                        )
                        continue

                    # Check risk
                    balance = await self.scraper.account_balance()
                    if not self.risk_manager.is_allowed(balance):
                        log.warning(f"Trade blocked: {self.risk_manager.block_reason}")
                        continue

                    # Place trade
                    log.info(f"Placing trade: {result.direction} (score={result.score:.2f})")
                    trade = await self.executor.place_trade(
                        result.direction,
                        settings.trade_amount,
                        settings.expiry_seconds,
                    )

                    if trade:
                        log.info(f"Trade placed: {trade}")

                except Exception as e:
                    log.error(f"Strategy loop error: {e}")

        except asyncio.CancelledError:
            log.info("Strategy Manager stopped")
            raise
