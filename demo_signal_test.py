#!/usr/bin/env python3
"""Offline demo: feed synthetic signal messages through the gate pipeline.

No network, no SSID, no Telegram credentials needed.
Mirrors demo_test.py but for the new Telegram-driven, event-driven pipeline.

What this script exercises:
  1. parse_signal() against representative messages of each format
  2. SignalGate (3 gates) with:
       - a MOCKED PO API client returning synthetic candles
       - a seeded WinRateTracker using a temp JSON file
       - the real ConfluenceEngine (real TA signals)
  3. Prints gate decisions for each synthetic signal
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd

# Ensure repo root is on the path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from data.candles import candles_to_df
from signals.bollinger import BollingerSignal
from signals.candle_pattern import CandlePatternSignal
from signals.confluence import ConfluenceEngine
from signals.ema_cross import EMASignal
from signals.macd import MACDSignal
from signals.rsi import RSISignal
from strategy.signal_gate import SignalGate
from strategy.win_rate import WinRateTracker
from telegram_feed.parser import parse_signal
from utils.logger import setup_logger, log

PROJECT_ROOT = Path(__file__).parent

# ──────────────────────────────────────────────────────────────────────────────
# Synthetic signal messages (representative formats)
# ──────────────────────────────────────────────────────────────────────────────

SYNTHETIC_MESSAGES = [
    # Should PASS gate 1 (87% ≥ 80%) — gates 2 and 3 depend on TA
    ("EUR/USD OTC CALL M1 Win rate: 87%",     "high stated wr, CALL"),
    ("EUR/USD OTC PUT M5 Win rate: 92%",      "high stated wr, PUT"),
    # Should FAIL gate 1 (65% < 80%)
    ("GBP/USD CALL M1 Win rate: 65%",         "low stated wr → gate 1 fail"),
    # No win rate → gate 1 fail (fail-closed)
    ("USDJPY_otc CALL M1",                    "no win rate → gate 1 fail"),
    # BUY/SELL aliases
    ("EURUSD BUY 1 min Win rate: 88%",        "BUY alias, 60s expiry"),
    ("GBPUSD SELL 5 min Win rate: 90%",       "SELL alias, 300s expiry"),
    # UP/DOWN aliases
    ("EUR/USD OTC UP M1 WR 82%",              "UP alias"),
    ("EUR/USD OTC DOWN M1 WR 85%",            "DOWN alias"),
    # Arrow symbols
    ("EURUSD OTC ↑ M1 Win rate: 91%",        "arrow UP"),
    # Expiry variants
    ("EUR/USD CALL expiry 60s Win rate: 80%", "expiry 60s"),
    # Garbage — should be silently skipped
    ("Hello, how are you?",                   "garbage → parse fail"),
    ("",                                       "empty string → parse fail"),
]


# ──────────────────────────────────────────────────────────────────────────────
# Synthetic candle generator
# ──────────────────────────────────────────────────────────────────────────────

def _generate_call_candles(n: int = 100) -> list[dict]:
    """Strong downtrend → RSI oversold → CALL signal from ConfluenceEngine."""
    np.random.seed(42)
    prices = np.linspace(100.0, 70.0, n)
    idx = pd.date_range(datetime.now(tz=timezone.utc), periods=n, freq="1min")
    rows = []
    for ts, p in zip(idx, prices):
        rows.append({
            "time": ts.timestamp(),
            "open": p,
            "high": p + 0.5,
            "low": p - 0.5,
            "close": p,
            "volume": float(np.random.uniform(1000, 5000)),
        })
    return rows


def _generate_put_candles(n: int = 100) -> list[dict]:
    """Strong uptrend → RSI overbought → PUT signal from ConfluenceEngine."""
    np.random.seed(99)
    prices = np.linspace(70.0, 100.0, n)
    idx = pd.date_range(datetime.now(tz=timezone.utc), periods=n, freq="1min")
    rows = []
    for ts, p in zip(idx, prices):
        rows.append({
            "time": ts.timestamp(),
            "open": p,
            "high": p + 0.5,
            "low": p - 0.5,
            "close": p,
            "volume": float(np.random.uniform(1000, 5000)),
        })
    return rows


def _build_mock_api(direction: str = "CALL"):
    """Build a mock API client that returns synthetic candles."""
    candles = _generate_call_candles() if direction == "CALL" else _generate_put_candles()
    api = MagicMock()
    api.get_candles = AsyncMock(return_value=candles)
    api.balance = AsyncMock(return_value=1000.0)
    return api


# ──────────────────────────────────────────────────────────────────────────────
# Main demo
# ──────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    setup_logger(PROJECT_ROOT, level="INFO")

    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║  PocketOptionBot — demo_signal_test.py           ║")
    log.info("║  Offline gate pipeline demo (no network/SSID)    ║")
    log.info("╚══════════════════════════════════════════════════╝")
    log.info("")

    # ── Build components ──────────────────────────────────────────────────────

    log.info("[1] Building components...")

    signals_list = [
        RSISignal(period=14),
        MACDSignal(fast=12, slow=26, signal=9),
        BollingerSignal(period=20, std_dev=2.0),
        EMASignal(fast=9, slow=21),
        CandlePatternSignal(),
    ]
    confluence_engine = ConfluenceEngine(signals_list)
    log.info(f"  ✓ ConfluenceEngine with {len(signals_list)} signals")

    # Temp win-rate tracker pre-seeded with some data
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = WinRateTracker(json_path=Path(tmpdir) / "demo_win_rates.json")
        # Seed with 15 wins + 5 losses for EURUSD_otc CALL 60s (warm, 75%)
        for _ in range(15):
            tracker.record("EURUSD_otc", "CALL", 60, "win")
        for _ in range(5):
            tracker.record("EURUSD_otc", "CALL", 60, "loss")
        log.info("  ✓ WinRateTracker seeded (EURUSD_otc CALL 60s: 15W/5L = 75%)")

        # Mock API returns CALL-biased candles
        mock_api = _build_mock_api(direction="CALL")
        log.info("  ✓ Mock API client (returns strong CALL candles)")

        gate = SignalGate(
            confluence_engine=confluence_engine,
            tracker=tracker,
            api_client=mock_api,
        )
        log.info("  ✓ SignalGate assembled")
        log.info("")

        # ── Settings snapshot ──────────────────────────────────────────────────
        log.info("[2] Active gate thresholds:")
        log.info(f"  MIN_CHANNEL_WIN_RATE  = {settings.min_channel_win_rate:.0%}")
        log.info(f"  MIN_TRACKED_WIN_RATE  = {settings.min_tracked_win_rate:.0%}")
        log.info(f"  MIN_TRACKED_SAMPLES   = {settings.min_tracked_samples}")
        log.info(f"  MIN_CONFLUENCE_SCORE  = {settings.min_confluence_score:.2f}")
        log.info(f"  TRADE_MODE            = {settings.trade_mode}")
        log.info(f"  DRY_RUN               = {settings.dry_run}")
        log.info("")

        # ── Feed synthetic messages ────────────────────────────────────────────
        log.info(f"[3] Processing {len(SYNTHETIC_MESSAGES)} synthetic messages:")
        log.info("─" * 60)

        passed = 0
        failed_gate = 0
        unparseable = 0

        for raw_text, description in SYNTHETIC_MESSAGES:
            display_text = repr(raw_text) if raw_text else "<empty>"
            log.info("")
            log.info(f"  Message  : {display_text}")
            log.info(f"  Scenario : {description}")

            signal = parse_signal(raw_text)
            if signal is None:
                log.info("  Result   : ✗ UNPARSEABLE — skipped (fail-soft)")
                unparseable += 1
                continue

            wr_str = f"{signal.stated_win_rate:.0%}" if signal.stated_win_rate is not None else "N/A"
            log.info(
                f"  Parsed   : pair={signal.pair} dir={signal.direction} "
                f"expiry={signal.expiry_seconds}s wr={wr_str}"
            )

            gate_result = await gate.evaluate(signal)
            if gate_result.passed:
                log.info(f"  Gate     : ✅ PASSED — {gate_result.reason}")
                passed += 1
            else:
                log.info(f"  Gate     : ✗ BLOCKED — {gate_result.reason}")
                failed_gate += 1

        log.info("")
        log.info("─" * 60)
        log.info("[4] Summary:")
        log.info(f"  Unparseable  : {unparseable}")
        log.info(f"  Gate blocked : {failed_gate}")
        log.info(f"  Gate passed  : {passed}")
        log.info(f"  Total        : {len(SYNTHETIC_MESSAGES)}")
        log.info("")

        # ── Candle adapter demo ────────────────────────────────────────────────
        log.info("[5] Candle adapter demo (data/candles.py):")
        raw_candles = _generate_call_candles(n=20)
        df = candles_to_df(raw_candles)
        log.info(
            f"  Converted {len(raw_candles)} API candle dicts → "
            f"DataFrame shape={df.shape}"
        )
        log.info(f"  Columns: {list(df.columns)}")
        row0 = df.iloc[0]
        log.info(
            f"  First row: o={row0['o']:.4f} h={row0['h']:.4f} "
            f"l={row0['l']:.4f} c={row0['c']:.4f} v={row0['v']:.0f}"
        )
        log.info("")

        log.info("✅ demo_signal_test.py completed successfully (all offline).")


if __name__ == "__main__":
    asyncio.run(main())
