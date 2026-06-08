"""v2 smoke tool — run ONE dry-run cycle against the live po_broker_bot.

Validates the pipeline WITHOUT placing any real trades (DRY_RUN forced True).
Runs in one of two modes depending on whether PO_SSID is configured:

FULL mode (PO_SSID set):
  1. Connect to po_broker_bot via the existing Telethon session.
  2. Navigate menus (Start Autotrade → wait for prediction → pair → direction).
  3. Connect the PocketOption API, fetch candles, run the 5-signal TA engine.
  4. Evaluate the decision (TRADE / SKIP) and log to data/decisions.jsonl.
  5. No trade is placed (DRY_RUN).

NAVIGATION-ONLY mode (no PO_SSID):
  Steps 1–2 only — proves the Telegram navigation + parsing works. The TA
  stage is skipped because it needs live PocketOption market data (candles),
  which requires a connected API session.

Usage
-----
    python3 tools/v2_smoke.py [--pair XXXYYY_otc] [--verbose]

Options
-------
    --pair      Override the pair (skip navigation, test TA for one asset).
                Requires PO_SSID.
    --verbose   Show DEBUG logs.

Pre-conditions
--------------
- .env must have TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION set.
- The Telethon session file must already be authenticated (run
  tools/gen_telegram_session.py once if it isn't).
- The legacy pocket_robot_trader.py must NOT be running (session is
  single-writer).
- PO_SSID enables FULL mode; without it the tool runs NAVIGATION-ONLY.
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
    log.info("Smoke tool — forced dry_run=True; trade_mode={}", cfg.trade_mode)

    from telethon import TelegramClient

    from broker.po_api import PocketOptionAPIClient
    from signals.adx_dmi import ADXDMISignal
    from signals.atr import ATRSignal
    from signals.bollinger import BollingerSignal
    from signals.candle_pattern import CandlePatternSignal
    from signals.confluence import ConfluenceEngine
    from signals.ema_cross import EMASignal
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
        EMASignal(fast=9, slow=21),
        CandlePatternSignal(),
        ADXDMISignal(period=14),  # Observation only
        ATRSignal(period=14),      # Observation only
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
        log.info("Pair override: {} — skipping navigation", override_pair)
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
        log.info("Smoke (override) — decision={} conf={:.3f} reason={}",
                 row.decision, conf.score, d.skip_reason)
        return True

    # ── full navigation mode ──────────────────────────────────────────────────
    navigator = Navigator(
        client=tg_client,
        bot_username=cfg.signal_bot_username,
        click_trade_anyway=cfg.click_trade_anyway,
    )

    async with tg_client:
        # The TA step needs live PocketOption market data (candles), which requires
        # a connected API session. DRY_RUN only short-circuits buy/sell, not candles.
        if cfg.po_ssid:
            log.info("PO_SSID present — connecting API for full pipeline…")
            try:
                await api_client.connect()
            except Exception as exc:
                log.opt(exception=True).error("PO API connect failed: {}", exc)
                return False
            manager = StrategyManagerV2(
                navigator=navigator, api_client=api_client,
                confluence_engine=confluence, risk_manager=risk, tracker=tracker,
            )
            log.info("Running one full cycle (DRY_RUN — no trade placed)…")
            try:
                await manager.run_once()
                log.info("Smoke cycle complete — check data/decisions.jsonl")
                return True
            except Exception as exc:
                log.opt(exception=True).error("Smoke cycle error: {}", exc)
                return False

        # No SSID → validate the Telegram half only (navigation + parsing).
        log.warning("No PO_SSID set — running NAVIGATION-ONLY smoke (TA/trade skipped).")
        return await _navigation_only_smoke(navigator, cfg)


async def _navigation_only_smoke(navigator, cfg) -> bool:
    """Drive the bot and parse the prediction + direction screens, no TA/trade.

    Proves the risky Telegram-navigation half works without needing a PO session.
    """
    from telegram_feed.direction_parser import parse_direction_screen
    from telegram_feed.pair_norm import normalize_pair
    from telegram_feed.prediction_parser import parse_prediction

    log.info("Connected to Telegram — start_autotrade…")
    await navigator.start_autotrade()

    pred_text, _ = await navigator.wait_for_prediction()
    pred = parse_prediction(pred_text)
    if not pred or not pred.top_pick():
        log.error("Navigation FAILED — no prediction screen parsed.")
        return False
    top = pred.top_pick()
    pair_api = normalize_pair(top.pair_raw)
    log.info("✅ Prediction OK — top pair {} ({}) → {} @ win%={:.0f}",
             top.pair_raw, "🏆" if top.is_top else "", pair_api, top.win_rate * 100)

    if not await navigator.select_pair(pair_api):
        log.error("Navigation FAILED — could not select pair {}", pair_api)
        return False

    dir_text, _ = await navigator.read_latest_text()
    dscreen = parse_direction_screen(dir_text)
    if dscreen is None:
        log.error("Navigation FAILED — no direction screen parsed.")
        await navigator.back_to_menu()
        return False
    log.info("✅ Direction OK — {} (setup={})", dscreen.direction, dscreen.setup)

    await navigator.back_to_menu()
    log.info("✅ NAVIGATION-ONLY smoke PASSED — Telegram pipeline works end-to-end. "
             "Add PO_SSID to test the TA + decision stage.")
    return True


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
