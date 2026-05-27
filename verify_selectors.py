#!/usr/bin/env python3
"""Quick test to verify selectors work on live PocketOption page.

Usage:
    python3 verify_selectors.py

This connects to CDP, finds the PocketOption page, and tests all selectors.
"""

import asyncio
import sys
from pathlib import Path

from broker.connector import CDPConnector
from broker.scraper import PocketOptionScraper
from config.settings import settings
from utils.logger import setup_logger, log

PROJECT_ROOT = Path(__file__).parent


async def main():
    setup_logger(PROJECT_ROOT, level="INFO")

    log.info("═══════════════════════════════════════")
    log.info("  Selector Verification")
    log.info("═══════════════════════════════════════")
    log.info(f"CDP URL: {settings.cdp_url}")

    # Connect
    log.info("\n[1] Connecting to CDP...")
    connector = CDPConnector(settings.cdp_url)
    try:
        page = await connector.connect()
        log.info("✓ Connected")
    except ConnectionError as e:
        log.error(f"✗ Connection failed: {e}")
        log.error("   Start Chrome with: google-chrome --remote-debugging-port=9222")
        return 1

    # Initialize scraper
    log.info("\n[2] Initializing scraper...")
    scraper = PocketOptionScraper(page)

    # Test each selector
    log.info("\n[3] Testing selectors...")
    results = {
        "price": await scraper.current_price(),
        "timer": await scraper.countdown_timer(),
        "balance": await scraper.account_balance(),
        "asset": await scraper.current_asset(),
        "last_result": await scraper.last_trade_result(),
        "is_demo": await scraper.is_demo_mode(),
    }

    # Display results
    log.info("\n[4] Results:")
    log.info("─" * 40)
    all_ok = True
    for key, value in results.items():
        status = "✓" if value is not None else "✗"
        log.info(f"{status} {key:15} = {value}")
        if value is None:
            all_ok = False

    log.info("─" * 40)
    if all_ok:
        log.info("✓ All selectors working!")
        return 0
    else:
        log.warning("✗ Some selectors returned None")
        log.warning("   You may need to update SELECTORS in broker/scraper.py")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        log.info("Interrupted")
        sys.exit(1)
