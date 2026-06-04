"""PocketOptionBot v2 — Telegram-driven, API-executed entrypoint.

Usage
-----
    python3 main_v2.py               # run indefinitely (Ctrl-C to stop)
    python3 main_v2.py --cycles 1    # one cycle then exit (dry-run / smoke test)

The bot:
1. Connects to po_broker_bot via an existing Telethon user session (MTProto).
2. Navigates the bot menus to read the top pair + direction.
3. Confirms with internal TA signals (ConfluenceEngine, 5 indicators).
4. Places a CALL/PUT trade via the PocketOption WebSocket API if all gates pass.
5. Awaits the outcome and logs everything to data/decisions.jsonl.

Safety:
- TRADE_MODE=DEMO is the default; LIVE requires an explicit env var override.
- The Navigator MUST NEVER click an amount/stake button (that places a
  martingale bot trade, not our API trade).
- Only one Telethon session writer may run at a time. Ensure the legacy
  pocket_robot_trader.py is stopped before running this.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from config.settings import settings, TradeMode
from utils.logger import log, setup_logger

# ── setup_logger must be called once before any use of `log` ─────────────────
import pathlib
setup_logger(pathlib.Path(__file__).parent)


def _build_components():
    """Instantiate and wire all components. Returns (client, manager)."""
    from telethon import TelegramClient

    from broker.po_api import PocketOptionAPIClient
    from signals.bollinger import BollingerSignal
    from signals.candle_pattern import CandlePatternSignal
    from signals.confluence import ConfluenceEngine
    from signals.ema_cross import EMASignal
    from signals.macd import MACDSignal
    from signals.rsi import RSISignal
    from strategy.risk import RiskManager
    from strategy.win_rate import WinRateTracker
    from strategy.manager_v2 import StrategyManagerV2
    from telegram_feed.navigator import Navigator

    # ── Telethon client ───────────────────────────────────────────────────────
    tg_client = TelegramClient(
        settings.telegram_session,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    # ── PocketOption API client ───────────────────────────────────────────────
    # demo mode is encoded in the SSID and enforced inside the client via the
    # demo guard — no separate flag needed here.
    api_client = PocketOptionAPIClient(
        ssid=settings.po_ssid,
        dry_run=settings.dry_run,
    )

    # ── 5-signal TA confluence engine ─────────────────────────────────────────
    signals = [
        RSISignal(period=14),
        MACDSignal(),
        BollingerSignal(),
        EMASignal(fast=9, slow=21),
        CandlePatternSignal(),
    ]
    confluence = ConfluenceEngine(signals)

    # ── Risk + win-rate tracker ───────────────────────────────────────────────
    risk = RiskManager(
        trade_amount=settings.stake_amount,
        max_trades_per_hour=settings.max_trades_per_hour,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        cooldown_after_loss_seconds=settings.cooldown_after_loss_seconds,
        min_balance_multiplier=settings.min_balance_multiplier,
    )
    tracker = WinRateTracker()

    # ── Navigator (Telegram button driver) ───────────────────────────────────
    navigator = Navigator(
        client=tg_client,
        bot_username=settings.signal_bot_username,
        click_trade_anyway=settings.click_trade_anyway,
    )

    # ── Orchestrator ─────────────────────────────────────────────────────────
    manager = StrategyManagerV2(
        navigator=navigator,
        api_client=api_client,
        confluence_engine=confluence,
        risk_manager=risk,
        tracker=tracker,
    )

    return tg_client, manager


async def main(cycles: int = 0) -> None:
    """Run the bot.

    Parameters
    ----------
    cycles:
        Number of trade cycles to attempt. 0 means run indefinitely.
    """
    log.info("PocketOptionBot v2 starting — mode=%s dry_run=%s cycles=%s",
             settings.trade_mode, settings.dry_run, cycles or "∞")

    if settings.trade_mode == TradeMode.LIVE and not settings.dry_run:
        log.warning("⚠  LIVE mode active — real money at stake!")

    tg_client, manager = _build_components()

    async with tg_client:
        count = 0
        while True:
            try:
                await manager.run_once()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                log.error("run_once error (will retry): %s", exc, exc_info=True)

            count += 1
            if cycles and count >= cycles:
                log.info("Completed %d cycle(s) — exiting.", count)
                break

            # Brief pause between cycles to avoid hammering the bot
            await asyncio.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PocketOptionBot v2")
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Number of cycles to run (0 = unlimited)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(main(cycles=args.cycles))
    except KeyboardInterrupt:
        log.info("Interrupted by user — goodbye.")
        sys.exit(0)
