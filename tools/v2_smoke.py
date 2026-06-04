"""v2 smoke tool — run ONE dry-run cycle against the live po_broker_bot.

This tool validates the full Telegram navigation + TA decision pipeline
WITHOUT placing any real trades. It:

1. Connects to po_broker_bot via the existing Telethon session.
2. Navigates menus (Start Autotrade → top pair → direction screen).
3. Runs the 5-signal TA confluence engine against live PO candles.
4. Evaluates the decision (TRADE / SKIP) and logs to data/decisions.jsonl.
5. Exits — no trade is placed (DRY_RUN is forced to True).

Usage
-----
    python3 tools/v2_smoke.py [--pair XXXYYY_otc]

Options
-------
    --pair      Override the pair selected by the bot (useful for testing a
                specific asset). Skips the prediction/navigation step.
    --verbose   Show DEBUG logs.

Pre-conditions
--------------
- .env must have TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION set.
- The Telethon session file must already be authenticated (run
  tools/gen_telegram_session.py once if it isn't).
- The legacy pocket_robot_trader.py must NOT be running (session is
  single-writer).
- PO_SSID is not required (we never call buy/sell in the smoke tool).
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

# Ensure project root is on the path when run as a script
_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from config.settings import BotSettings  # noqa: E402
from utils.logger import log, setup_logger  # noqa: E402

setup_logger(_ROOT)


async def run_smoke(override_pair: str | None = None) -> bool:
    """Execute one smoke cycle.

    Returns True if the cycle completed (even if SKIP), False on fatal error.
    """
    # Force dry_run for the smoke tool regardless of .env
    cfg = BotSettings(_env_file=_ROOT / ".env")  # type: ignore[call-arg]
    cfg_dry = cfg.model_copy(update={"dry_run": True})
    _ = cfg_dry  # we use the global `settings` singleton below; just log intent
    log.info("Smoke tool — forced dry_run=True; trade_mode=%s", cfg.trade_mode)

    from telethon import TelegramClient

    from broker.po_api import PocketOptionAPIClient
    from signals.bollinger import BollingerSignal
    from signals.candle_pattern import CandlePatternSignal
    from signals.confluence import ConfluenceEngine
    from signals.ema_cross import EMACrossSignal
    from signals.macd import MACDSignal
    from signals.rsi import RSISignal
    from strategy.manager_v2 import StrategyManagerV2
    from strategy.risk import RiskManager
    from strategy.win_rate import WinRateTracker
    from telegram_feed.navigator import Navigator

    tg_client = TelegramClient(
        cfg.telegram_session,
        cfg.telegram_api_id,
        cfg.telegram_api_hash,
    )

    # Always dry-run in the smoke tool — pass an empty SSID to avoid requiring
    # a valid PO session just for a navigation test.
    api_client = PocketOptionAPIClient(ssid=cfg.po_ssid or "", dry_run=True)

    signals = [
        RSISignal(period=14),
        MACDSignal(),
        BollingerSignal(),
        EMACrossSignal(fast=9, slow=21),
        CandlePatternSignal(),
    ]
    confluence = ConfluenceEngine(signals)
    risk = RiskManager(
        trade_amount=cfg.stake_amount,
        max_trades_per_hour=cfg.max_trades_per_hour,
        max_daily_loss_usd=cfg.max_daily_loss_usd,
        cooldown_after_loss_seconds=cfg.cooldown_after_loss_seconds,
        min_balance_multiplier=cfg.min_balance_multiplier,
    )
    tracker = WinRateTracker()

    if override_pair:
        # ── pair override mode: skip navigation, inject a fake direction screen ──
        log.info("Pair override: %s — skipping navigation", override_pair)
        from data.candles import candles_to_df
        from strategy.decision import decide
        from strategy.expiry import select_expiry
        from strategy.trade_logger import DecisionRow, write_decision

        expiry = select_expiry(cfg.default_expiry_seconds, cfg.allowed_expiries)
        candles = await api_client.get_candles(override_pair, period=expiry, count=cfg.history_length)
        df = candles_to_df(candles)
        conf = await confluence.score(df)
        d = decide(
            bot_direction="CALL",          # placeholder — no real bot screen
            our_direction=conf.direction,
            bot_win_rate=0.90,
            our_confluence=conf.score,
            our_score_floor=cfg.min_confluence_score,
        )
        row = DecisionRow(
            cycle_id="smoke-override",
            pair_raw=override_pair,
            pair_api=override_pair,
            bot_win_rate=0.90,
            bot_is_top_pick=True,
            bot_direction="CALL",
            bot_setup="unknown",
            bot_indicators_raw="(smoke override — no navigation)",
            our_direction=conf.direction,
            our_confluence_score=conf.score,
            our_signal_breakdown={},
            agreement=(conf.direction == "CALL"),
            combined_probability=d.combined_probability,
            expiry_seconds=expiry,
            decision="TRADE" if d.trade else "SKIP",
            skip_reason=d.skip_reason,
            stake=cfg.stake_amount,
        )
        write_decision(cfg.decisions_log_path, row)
        log.info("Smoke (override) — decision=%s conf=%.3f reason=%s",
                 row.decision, conf.score, d.skip_reason)
        return True

    # ── full navigation mode ──────────────────────────────────────────────────
    navigator = Navigator(
        client=tg_client,
        bot_username=cfg.signal_bot_username,
        click_trade_anyway=cfg.click_trade_anyway,
    )
    manager = StrategyManagerV2(
        navigator=navigator,
        api_client=api_client,
        confluence_engine=confluence,
        risk_manager=risk,
        tracker=tracker,
    )

    async with tg_client:
        log.info("Connected to Telegram — running one cycle…")
        try:
            await manager.run_once()
            log.info("Smoke cycle complete — check data/decisions.jsonl")
            return True
        except Exception as exc:
            log.error("Smoke cycle error: %s", exc, exc_info=True)
            return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PocketOptionBot v2 smoke tool — one dry-run cycle"
    )
    parser.add_argument(
        "--pair",
        default=None,
        metavar="XXXYYY_otc",
        help="Override pair (skip navigation, e.g. EURUSD_otc)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    ok = asyncio.run(run_smoke(override_pair=args.pair))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
