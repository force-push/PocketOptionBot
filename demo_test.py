#!/usr/bin/env python3
"""Demo mode test: Simulate price feed and test signal generation."""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from signals.rsi import RSISignal
from signals.macd import MACDSignal
from signals.bollinger import BollingerSignal
from signals.ema_cross import EMASignal
from signals.candle_pattern import CandlePatternSignal
from signals.confluence import ConfluenceEngine
from config.settings import settings
from utils.logger import setup_logger, log

PROJECT_ROOT = Path(__file__).parent


def generate_synthetic_data(n_candles: int = 100) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    
    # Start price
    price = 1.0800
    prices = [price]
    
    for _ in range(n_candles - 1):
        # Small random walk
        change = np.random.normal(0, 0.0002)
        price = max(price + change, 1.0700)
        prices.append(price)
    
    prices = np.array(prices)
    
    # Create OHLCV
    data = {
        'timestamp': [datetime.now() - timedelta(seconds=60*i) for i in range(n_candles-1, -1, -1)],
        'o': prices,
        'h': prices * (1 + np.abs(np.random.normal(0, 0.0001, n_candles))),
        'l': prices * (1 - np.abs(np.random.normal(0, 0.0001, n_candles))),
        'c': prices,
        'v': np.random.uniform(1000, 5000, n_candles),
    }
    
    df = pd.DataFrame(data)
    return df


async def main():
    """Run demo with synthetic data."""
    setup_logger(PROJECT_ROOT, level="INFO")
    
    log.info("╔════════════════════════════════════════════╗")
    log.info("║  PocketOptionBot — DEMO MODE (Synthetic)  ║")
    log.info("╚════════════════════════════════════════════╝")
    log.info("")
    
    # Generate synthetic data
    log.info("[1] Generating synthetic price data...")
    df = generate_synthetic_data(n_candles=100)
    log.info(f"✓ Generated {len(df)} candles")
    log.info(f"  Price range: {df['c'].min():.5f} - {df['c'].max():.5f}")
    log.info("")
    
    # Initialize signals
    log.info("[2] Initializing signals...")
    signals = [
        RSISignal(period=14),
        MACDSignal(fast=12, slow=26, signal=9),
        BollingerSignal(period=20, std_dev=2.0),
        EMASignal(fast=9, slow=21),
        CandlePatternSignal(),
    ]
    for sig in signals:
        log.info(f"  ✓ {sig.name} (weight={sig.weight})")
    log.info("")
    
    # Evaluate signals
    log.info("[3] Evaluating signals on latest candle...")
    results = []
    for signal in signals:
        result = await signal.evaluate(df)
        results.append(result)
        status = f"✓ {result.direction or 'NEUTRAL'}" if result.direction else "• NEUTRAL"
        log.info(f"  {status:15} {result.name:15} ({result.confidence:.2f}) — {result.reason}")
    log.info("")
    
    # Confluence scoring
    log.info("[4] Computing confluence score...")
    engine = ConfluenceEngine(signals)
    confluence = await engine.score(df)
    threshold = settings.min_confluence_score
    
    log.info(f"  Confluence Score: {confluence.score:.3f} (threshold: {threshold})")
    log.info(f"  Direction: {confluence.direction or 'NEUTRAL'}")
    log.info(f"  Reason: {confluence.reason}")
    
    if confluence.direction and confluence.score >= threshold:
        log.info(f"  ✅ TRADE SIGNAL: {confluence.direction} (confidence: {confluence.score:.1%})")
    else:
        log.info(f"  ⚪ No trade (insufficient confluence or direction)")
    log.info("")
    
    # Risk checks
    log.info("[5] Risk management checks...")
    log.info(f"  TRADE_MODE: {settings.trade_mode}")
    log.info(f"  DRY_RUN: {settings.dry_run}")
    log.info(f"  MAX_TRADES_PER_HOUR: {settings.max_trades_per_hour}")
    log.info(f"  MAX_DAILY_LOSS_USD: ${settings.max_daily_loss_usd}")
    log.info(f"  MIN_BALANCE_MULTIPLIER: {settings.min_balance_multiplier}x")
    log.info("")
    
    log.info("✅ Demo test completed successfully!")
    log.info("")
    log.info("📝 Next steps:")
    log.info("  1. Start Chrome with: google-chrome --remote-debugging-port=9222")
    log.info("  2. Navigate to PocketOption broker page")
    log.info("  3. Run: python3 main.py")
    log.info("  4. Check logs/bot.log and data/trades.jsonl")


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code or 0)
