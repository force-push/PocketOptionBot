"""PocketOptionBot v2 — signals-driven, API-executed entrypoint.

Usage
-----
    python3 main_v2.py               # run indefinitely (Ctrl-C to stop)
    python3 main_v2.py --cycles 1    # one cycle then exit (smoke test)

The bot (payout-first signals loop — Telegram integration removed 2026-06-11):
1. Connects to the PocketOption WebSocket API (PO_SSID).
2. Each cycle: fetch all active pairs ≥ MIN_PAYOUT_PCT, sorted by payout.
3. For each pair: fetch candles → run the 11-signal confluence engine →
   decide → risk gates → place a CALL/PUT trade via the API.
4. Resolves outcomes in background tasks and logs everything to
   data/decisions.jsonl (plus research shadow trades — see
   SHADOW_TRADE_ANALYSIS.md).

Safety:
- TRADE_MODE=DEMO is the default; LIVE requires an explicit env var override.
- DRY_RUN=true logs trades without calling the API.
"""
from __future__ import annotations

import argparse
import asyncio
import resource
import sys
import time
from pathlib import Path

from config.settings import settings, reload_settings, TradeMode
from utils.logger import log, setup_logger

# Liveness heartbeat: the main loop rewrites this at the end of every cycle, so
# the supervisor can detect a genuine hang (cycles stop) even when background
# tasks keep logging. See tools/run_supervised.sh.
_HEARTBEAT_PATH = Path("data/heartbeat")


def _touch_heartbeat() -> None:
    try:
        _HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _HEARTBEAT_PATH.write_text(str(time.time()))
    except Exception:  # never let heartbeat I/O disrupt trading
        pass


_ENV_PATH = Path(".env")
_env_mtime: float = 0.0


async def _watch_env(interval: float = 10.0) -> None:
    """Background task: reload settings when .env changes on disk.

    Runs forever alongside the main bot loop. Detects dashboard edits and
    applies them in-place without a restart. Interval default is 10s —
    low enough to feel responsive, high enough to be invisible overhead.
    """
    global _env_mtime
    try:
        _env_mtime = _ENV_PATH.stat().st_mtime
    except FileNotFoundError:
        pass
    while True:
        await asyncio.sleep(interval)
        try:
            mtime = _ENV_PATH.stat().st_mtime
            if mtime != _env_mtime:
                _env_mtime = mtime
                reload_settings()
                log.info("⚙  .env changed — settings reloaded (martingale: enabled={} "
                         "multiplier={} max_level={})",
                         settings.martingale_enabled,
                         settings.martingale_multiplier,
                         settings.martingale_max_level)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("env watcher error (ignored): {}", exc)

# ── setup_logger must be called once before any use of `log` ─────────────────
import pathlib
setup_logger(pathlib.Path(__file__).parent)

# Memory instrumentation: log peak RSS every N cycles so memory growth is visible
# in the logs (confirms the Tier 1-3 fixes hold). Peak RSS only climbs, so a
# plateau across hours means no ongoing leak.
_RSS_LOG_EVERY = 50


def _peak_rss_mb() -> float:
    """Peak resident set size in MB (cross-platform: darwin=bytes, linux=KB)."""
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return ru / (1024 * 1024) if sys.platform == "darwin" else ru / 1024


def _log_rss(cycle: int) -> None:
    if cycle <= 0 or cycle % _RSS_LOG_EVERY != 0:
        return
    try:
        log.info("MEM: peak RSS {:.0f} MB  (cycle {})", _peak_rss_mb(), cycle)
    except Exception:  # instrumentation must never disrupt trading
        pass


def _build_components():
    """Instantiate and wire all components. Returns (api_client, manager)."""
    from broker.po_api import PocketOptionAPIClient
    from signals.adx_dmi import ADXDMISignal
    from signals.atr import ATRSignal
    from signals.confluence import ConfluenceEngine
    from signals.ema_cross import EMASignal
    from signals.heikin_ashi import HeikinAshiSignal
    from signals.macd import MACDSignal
    from signals.parabolic_sar import ParabolicSARSignal
    from signals.roc import RoCSignal
    from signals.rsi import RSISignal
    from signals.stoch_rsi import StochRSISignal
    from signals.stochastic import StochasticSignal
    from signals.supertrend import SupertrendSignal
    from strategy.risk import RiskManager
    from strategy.win_rate import WinRateTracker
    from strategy.manager_v2 import StrategyManagerV2

    # ── PocketOption API client ───────────────────────────────────────────────
    # demo mode is encoded in the SSID and enforced inside the client via the
    # demo guard — no separate flag needed here.
    api_client = PocketOptionAPIClient(
        ssid=settings.po_ssid,
        dry_run=settings.dry_run,
    )

    # ── TA confluence engine ──────────────────────────────────────────────────
    # Signal tiers (2026-06-09, ~440 resolved trades):
    #   Gate (decision_signals): MACD + EMA_Cross only — confirmed positive edge
    #   Tier 0 (weight > 0, no gate): RSI — noise but harmless, kept for research
    #   Tier 2 (weight > 0, no gate): Supertrend, Stochastic, Parabolic SAR
    #   Tier 3 (weight > 0, no gate): HeikinAshi, RoC, StochRSI — new, observation-only
    #   Tier 1 (weight = 0): ADX_DMI, ATR — pure research counters
    #   REMOVED: Bollinger (inverted), CandlePattern (0/291 direction, dead)
    signals = [
        # ── Gate-eligible (Tier 0) ─────────────────────────────────────────
        RSISignal(
            period=settings.rsi_period,
            oversold=settings.rsi_oversold,
            overbought=settings.rsi_overbought,
        ),
        MACDSignal(
            fast=settings.macd_fast,
            slow=settings.macd_slow,
            signal=settings.macd_signal_period,
        ),
        EMASignal(
            fast=settings.ema_fast,
            slow=settings.ema_slow,
        ),
        # ── Tier 2: Trend confirmers ───────────────────────────────────────
        SupertrendSignal(period=10, multiplier=3.0),
        StochasticSignal(period=14, smooth_k=3, smooth_d=3),
        ParabolicSARSignal(initial_af=0.02, max_af=0.2, af_step=0.02),
        # ── Tier 3: Momentum/exhaustion (observation-only) ────────────────
        HeikinAshiSignal(min_consecutive=3),
        RoCSignal(period=5, threshold=0.05),
        StochRSISignal(rsi_period=14, stoch_period=14, smooth_k=3, smooth_d=3),
        # ── Tier 1: Research counters (weight=0) ──────────────────────────
        ADXDMISignal(period=14),
        ATRSignal(period=14),
    ]
    # All directional signals now contribute to BOTH direction and probability.
    # decision_signals=None means every signal participates in the confluence
    # vote, agreement count, and weighted score (ATR is non-directional so it
    # never votes; ADX_DMI carries a small weight — see signals/adx_dmi.py).
    # Rationale: gather richer direction/probability data across the full signal
    # set, especially for the shadow expiry experiment. Analysis (2026-06-10,
    # n=855) showed MACD+EMA-only gating had no robust out-of-sample edge, so
    # restricting the vote bought us nothing — widen it and let the data decide.
    confluence = ConfluenceEngine(
        signals,
        min_agreement=settings.min_signal_agreement,
        decision_signals=None,  # all signals decide direction + probability
    )

    # ── Risk + win-rate tracker ───────────────────────────────────────────────
    risk = RiskManager(
        trade_amount=settings.stake_amount,
        max_trades_per_hour=settings.max_trades_per_hour,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        cooldown_after_loss_seconds=settings.cooldown_after_loss_seconds,
        min_balance_multiplier=settings.min_balance_multiplier,
    )
    tracker = WinRateTracker()

    # ── Dashboard StateBridge (optional, fail-closed, no-op when disabled) ────
    bridge = None
    if settings.dashboard_enabled:
        from dashboard.state_bridge import StateBridge
        bridge = StateBridge(
            state_path=settings.live_state_path,
            events_path=settings.events_log_path,
            enabled=True,
        )
        log.info("Dashboard bridge enabled → {} / {}",
                 settings.live_state_path, settings.events_log_path)

    # ── Orchestrator ─────────────────────────────────────────────────────────
    manager = StrategyManagerV2(
        api_client=api_client,
        confluence_engine=confluence,
        risk_manager=risk,
        tracker=tracker,
        bridge=bridge,
    )

    return api_client, manager


async def main(cycles: int = 0) -> None:
    """Run the bot.

    Parameters
    ----------
    cycles:
        Number of trade cycles to attempt. 0 means run indefinitely.
    """
    log.info("PocketOptionBot v2 starting — mode={} dry_run={} cycles={}",
             settings.trade_mode, settings.dry_run, cycles or "∞")
    log.info("Loop driver: signals  (payout_floor={}%  max_pairs_per_cycle={})",
             settings.min_payout_pct, settings.max_pairs_per_cycle or "all")
    log.info("Signal gates: min_agreement={}/5  min_confluence_score={}",
             settings.min_signal_agreement, settings.min_confluence_score)
    log.info("TA config: candle_interval={}s  history_length={}  expiry={}s",
             settings.candle_interval_seconds, settings.history_length,
             settings.default_expiry_seconds)
    log.info("Trade config: stake=${:.2f}  min_payout={}%  max_trades_hr={}",
             settings.stake_amount, settings.min_payout_pct, settings.max_trades_per_hour)

    if settings.trade_mode == TradeMode.LIVE and not settings.dry_run:
        log.warning("⚠  LIVE mode active — real money at stake!")

    api_client, manager = _build_components()

    if settings.po_ssid:
        log.info("Connecting PocketOption API…")
        await api_client.connect()

        # Log top active pairs by payout (informational)
        active = await api_client.get_active_pairs()
        if active:
            top = active[:8]
            log.info("Top pairs by payout: {}",
                     "  ".join(f"{a['symbol']}={a['payout']}%" for a in top))

        # Seed WinRateTracker from PO closed-deals history (background, non-blocking)
        async def _seed_win_rates():
            deals = await api_client.get_po_trade_history()
            n = manager.tracker.seed_from_po_history(
                deals, default_expiry_seconds=settings.default_expiry_seconds)
            if n:
                log.info("WinRateTracker seeded {} records from PO history", n)

        asyncio.ensure_future(_seed_win_rates())

        # Restore martingale streaks from recent DB history so a restart after a
        # crash/reconnect doesn't silently reset all loss streaks to zero.
        db_path = str(settings.decisions_db_path)
        manager._martingale.seed_from_db(
            db_path,
            max_level=settings.martingale_max_level,
            lookback_hours=6.0,
        )
    else:
        log.warning("No PO_SSID — candle fetching will fail; set PO_SSID in .env")

    # Settings hot-reload: watch .env for changes (dashboard edits) every 10s
    asyncio.ensure_future(_watch_env())

    count = 0
    consecutive_timeouts = 0
    while True:
        try:
            # Hard cycle timeout: the WS layer can hang an await forever on a
            # dropped connection (hangs observed 2026-06-11 at 09:15 + 15:45
            # UTC+9:30 with the process alive but the loop dead). A scan of
            # ~30 pairs takes 60-90s; 300s means genuinely stuck.
            await asyncio.wait_for(manager.run_once(), timeout=300.0)
            consecutive_timeouts = 0
        except asyncio.TimeoutError:
            consecutive_timeouts += 1
            log.error("run_once exceeded 300s — cycle aborted (WS hang?) [{}/2]",
                      consecutive_timeouts)
            if consecutive_timeouts >= 2:
                # WS is persistently dead — exit so the supervisor restarts us
                # with a fresh connection. In-process reconnect is not reliable
                # with the Rust client's lazy internals.
                log.critical("2 consecutive cycle timeouts — exiting for supervisor restart")
                sys.exit(1)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log.opt(exception=True).error("run_once error (will retry): {}", exc)

        # FlipStreamer signals a clean exit when the broker connection is dead.
        if manager._restart_requested:
            log.critical("Exiting for supervisor restart — {}", manager._restart_requested)
            sys.exit(1)

        # Heartbeat: mark the main loop alive at the end of every cycle so the
        # supervisor's hang watchdog measures real cycle progress, not log churn.
        _touch_heartbeat()

        count += 1
        _log_rss(count)
        if cycles and count >= cycles:
            log.info("Completed {} cycle(s) — exiting.", count)
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
