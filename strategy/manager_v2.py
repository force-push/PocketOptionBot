# strategy/manager_v2.py
"""Telebot-evolution orchestrator: navigate → parse → TA → decide → API → record."""
from __future__ import annotations

import asyncio
import json
import statistics
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.settings import settings, TradeMode, PredictionSource
from data.candles import candles_to_df
from strategy.decision import decide, decide_signals
from strategy.expiry import select_expiry
from strategy.probability_calibrator import ProbabilityCalibrator
from strategy.trade_logger import DecisionRow, write_decision, backfill_outcome
from telegram_feed.direction_parser import parse_direction_screen
from telegram_feed.pair_norm import normalize_pair
from telegram_feed.prediction_parser import parse_prediction
from utils.logger import log

_cycle_counter = 0


class StrategyManagerV2:
    def __init__(self, navigator, api_client, confluence_engine, risk_manager, tracker,
                 bridge=None):
        self._nav = navigator
        self._api = api_client
        self._conf = confluence_engine
        self._risk = risk_manager
        self._tracker = tracker
        # Optional dashboard StateBridge. All call sites are guarded by
        # `if self._bridge:` and the bridge itself never raises (fail-closed),
        # so trading behaviour is unchanged when the dashboard is disabled.
        self._bridge = bridge
        # Background trade resolver: maps trade_id → (log_path, row, expires_at)
        self._open_trades: dict = {}
        # Concurrent trade cap: never hold more than 6 unresolved trades at once.
        # Each slot is claimed at placement and released in _resolve_trade_background.
        self._open_trade_count: int = 0
        self._max_concurrent_trades: int = 6
        # Calibrated win-probability model. Loads the saved model if present;
        # otherwise predict() falls back to the heuristic mean (never raises).
        self._calibrator = ProbabilityCalibrator.load()

    @property
    def tracker(self):
        """The WinRateTracker instance (owned here; exposed for startup seeding)."""
        return self._tracker

    def _next_cycle_id(self) -> str:
        global _cycle_counter
        _cycle_counter += 1
        return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{_cycle_counter:04d}"

    async def run_once(self) -> None:
        """Dispatch to the configured loop driver (signals or broker_bot)."""
        if settings.prediction_source == PredictionSource.SIGNALS:
            await self._run_once_signals()
        else:
            await self._run_once_broker_bot()

    async def _run_once_broker_bot(self) -> None:
        cid = self._next_cycle_id()
        log_path = settings.decisions_log_path

        await self._nav.start_autotrade()
        # The prediction screen arrives several seconds after launch (AI analysis);
        # poll for it rather than reading the interim status message.
        pred_text, pred_btns = await self._nav.wait_for_prediction()
        pred = parse_prediction(pred_text)
        if not pred or not pred.top_pick():
            log.info("[{}] no prediction parsed; skipping", cid)
            return

        top = pred.top_pick()
        
        # Cycle through available pairs in the prediction screen to find one that's not blocked.
        # Extract pair buttons (exclude Main Menu) and try each in order.
        valid_pair_api = None
        selected_pair_button = None  # Track which button we selected
        for btn_text in pred_btns:
            if "main menu" in btn_text.lower():
                continue
            candidate = normalize_pair(btn_text)
            if candidate is None:
                continue
            # Skip blocked pairs; use the first valid one.
            if candidate not in settings.blocked_pairs:
                valid_pair_api = candidate
                selected_pair_button = btn_text  # Remember the button text for later
                break
        
        if valid_pair_api is None:
            # All available pairs are blocked; log and skip.
            log.info("[{}] all proposed pairs are in blocked_pairs list; skipping", cid)
            return
        
        pair_api = valid_pair_api
        
        # If we selected a different pair than the top pick, find its metadata from pred.pairs
        pair_raw = top.pair_raw  # Default to top's display name
        if pair_api != normalize_pair(top.pair_raw):
            # We cycled to a different pair; find its raw name and metadata
            for p in pred.pairs:
                if normalize_pair(p.pair_raw) == pair_api:
                    pair_raw = p.pair_raw
                    top = p  # Use this pair's metadata instead
                    break
        
        if top.win_rate < settings.pair_select_min_win_rate:
            log.info("[{}] {} win% {:.0f} below gate {:.0f} — skip",
                     cid, pair_api, top.win_rate * 100, settings.pair_select_min_win_rate * 100)
            return

        if not await self._nav.select_pair(pair_api):
            log.info("[{}] pair select failed for {}", cid, pair_api)
            return

        # Fetch payout early so we skip low-payout pairs before doing any TA
        payout_pct = await self._api.get_payout(pair_api)
        if settings.min_payout_pct > 0 and (payout_pct is None or payout_pct < settings.min_payout_pct):
            log.info("[{}] SKIP {}  reason=low_payout  payout={}% < gate={}%",
                     cid, pair_api, payout_pct, settings.min_payout_pct)
            await self._nav.back_to_menu()
            return

        dir_text, _ = await self._nav.read_latest_text()
        dscreen = parse_direction_screen(dir_text)
        if dscreen is None:
            log.info("[{}] no direction screen for {} — text received: {!r}", cid, pair_api, dir_text[:300])
            return

        # ── BOT signal summary ────────────────────────────────────────────────
        log.info(
            "[{}] ── {} ── BOT: {}  win={:.1f}%  setup={}",
            cid, pair_api, dscreen.direction, top.win_rate * 100, dscreen.setup,
        )
        if dscreen.indicators_raw:
            log.info("[{}]   BOT indicators: {}", cid, dscreen.indicators_raw)

        expiry = select_expiry(settings.default_expiry_seconds, settings.allowed_expiries)
        # Candle resolution is deliberately decoupled from the trade expiry.
        # Using period=expiry (e.g. 30 s) meant one candle per trade window —
        # too coarse for MACD/EMA which need 26+ candles of meaningful price
        # action.  CANDLE_INTERVAL_SECONDS (default 5 s) gives fine-grained
        # momentum data; 100 × 5 s = 8+ minutes of context for any expiry.
        candle_period = settings.candle_interval_seconds
        candle_list = await self._api.get_candles(pair_api, period=candle_period, count=settings.history_length)
        df = candles_to_df(candle_list)
        log.info("[{}]   candles={}  period={}s  expiry={}s", cid, len(df), candle_period, expiry)
        conf = await self._conf.score(df)

        # ── Per-signal table ─────────────────────────────────────────────────
        for name, vals in (conf.breakdown or {}).items():
            sig_dir, sig_conf, sig_reason = (vals + (None,) * 3)[:3]
            dir_str = sig_dir if sig_dir else "----"
            log.info("[{}]   TA  {:14s} {}  conf={:.3f}  {}",
                     cid, name, f"{dir_str:<4}", sig_conf or 0.0, sig_reason or "")

        # ── Confluence result ─────────────────────────────────────────────────
        agreeing = sum(1 for v in (conf.breakdown or {}).values() if v[0] == conf.direction)
        total_signals = len(conf.breakdown or {})
        gate = "✓ PASS" if conf.direction is not None else "✗ FAIL"
        log.info(
            "[{}]   CONF {}  score={:.3f}  agreed={}/{}  {}  ({})",
            cid, conf.direction or "----", conf.score, agreeing, total_signals,
            gate, conf.reason,
        )

        d = decide(bot_direction=dscreen.direction, our_direction=conf.direction,
                   bot_win_rate=top.win_rate, our_confluence=conf.score)

        balance_before = await self._api.balance()
        if self._bridge:
            self._bridge.heartbeat(
                mode=settings.trade_mode.value, dry_run=settings.dry_run,
                connected=True, balance=balance_before, currency="USD",
                active=[], last_cycle={"cycle_id": cid, "status": "trading", "skip_reason": None},
                risk_block_reason=None,
            )
        row = DecisionRow(
            cycle_id=cid, pair_raw=top.pair_raw, pair_api=pair_api,
            bot_win_rate=top.win_rate, bot_is_top_pick=top.is_top,
            bot_direction=dscreen.direction, bot_setup=dscreen.setup,
            bot_indicators_raw=dscreen.indicators_raw,
            our_direction=conf.direction, our_confluence_score=conf.score,
            our_signal_breakdown={k: list(v[:3]) for k, v in (conf.breakdown or {}).items()},
            agreement=(conf.direction == dscreen.direction),
            combined_probability=d.combined_probability, expiry_seconds=expiry,
            decision="TRADE" if d.trade else "SKIP", skip_reason=d.skip_reason,
            stake=settings.stake_amount, balance_before=balance_before,
        )
        # Calibrated P(win), recorded ALONGSIDE the heuristic confidence for
        # observation only. This value is intentionally NOT used by decide(), the
        # EV gate, or risk sizing — it is display/diagnostic data while the model
        # matures (current AUC ~0.53). Falls back to the heuristic mean when no
        # trained model is loaded; left None for non-trades.
        if d.trade:
            row.calibrated_probability = self._calibrator.predict({
                "bot_win_rate": top.win_rate,
                "our_confluence": conf.score,
                "agreement": conf.direction == dscreen.direction,
                "agreeing_signals": agreeing,
                "payout_pct": payout_pct,
                "bot_is_top_pick": top.is_top,
            })

        # Research/data-collection mode (DEMO only): instead of blocking at the
        # TA-agreement / EV / risk gates, place the bot-direction trade and record
        # the outcome. Hard-guarded to DEMO and to a real bot direction so it can
        # never widen LIVE trading. Each overridden gate tags would_skip_reason.
        shadow_active = (
            settings.shadow_record_mode
            and settings.trade_mode == TradeMode.DEMO
            and dscreen.direction in ("CALL", "PUT")
        )

        def _shadow_override(reason: str) -> None:
            """Convert a skip into a recorded shadow trade (first reason wins)."""
            row.shadow = True
            if row.would_skip_reason is None:
                row.would_skip_reason = reason
            row.decision = "TRADE"
            row.skip_reason = None

        if not d.trade:
            if shadow_active:
                _shadow_override(d.skip_reason or "no_direction")
                log.info("[{}] SHADOW {}  would_skip={}  (bot={} our={})",
                         cid, pair_api, row.would_skip_reason,
                         dscreen.direction, conf.direction or "None")
            else:
                write_decision(log_path, row)
                if self._bridge:
                    self._bridge.on_decision(asdict(row))
                log.info(
                    "[{}] SKIP {}  reason={}  (bot={} our={} prob={:.2f})",
                    cid, pair_api, d.skip_reason,
                    dscreen.direction, conf.direction or "None", d.combined_probability,
                )
                await self._nav.back_to_menu()
                return

        # payout already checked early in cycle

        # EV gate: skip if our tracked win rate produces negative expected value
        # EV = win_rate * (payout/100 + 1) - 1   →   break-even at 52.1% for 92% payout
        tracked_rate, n_tracked = self._tracker.rate(pair_api, dscreen.direction, expiry)
        if payout_pct is not None and n_tracked >= settings.min_ev_samples:
            ev = tracked_rate * (payout_pct / 100 + 1) - 1
            if ev < settings.min_expected_value:
                if shadow_active:
                    _shadow_override("negative_ev")
                    log.info("[{}] SHADOW {}  would_skip=negative_ev  ev={:.3f}",
                             cid, pair_api, ev)
                else:
                    row.decision = "SKIP"; row.skip_reason = "negative_ev"
                    write_decision(log_path, row)
                    if self._bridge:
                        self._bridge.on_decision(asdict(row))
                    log.info(
                        "[{}] SKIP {}  reason=negative_ev  ev={:.3f}  wr={:.1%}  n={}  payout={}%",
                        cid, pair_api, ev, tracked_rate, n_tracked, payout_pct,
                    )
                    await self._nav.back_to_menu()
                    return

        if not self._risk.is_allowed(balance_before):
            if shadow_active:
                _shadow_override("risk_blocked")
                log.warning("[{}] SHADOW {}  would_skip=risk_blocked: {}",
                            cid, pair_api, getattr(self._risk, "block_reason", ""))
            else:
                row.decision = "SKIP"; row.skip_reason = "risk_blocked"
                write_decision(log_path, row)
                if self._bridge:
                    self._bridge.on_decision(asdict(row))
                log.warning("[{}] risk blocked: {}", cid, getattr(self._risk, "block_reason", ""))
                await self._nav.back_to_menu()
                return

        # Concurrent trade cap: skip rather than queue if we're at max capacity.
        if self._open_trade_count >= self._max_concurrent_trades:
            row.decision = "SKIP"; row.skip_reason = "max_concurrent_trades"
            write_decision(log_path, row)
            log.info("[{}] SKIP {}  reason=max_concurrent_trades  open={}/{}",
                     cid, pair_api, self._open_trade_count, self._max_concurrent_trades)
            await self._nav.back_to_menu()
            return
        self._open_trade_count += 1

        api_call = self._api.buy if dscreen.direction == "CALL" else self._api.sell
        trade = await api_call(pair_api, settings.stake_amount, expiry)
        row.trade_id = getattr(trade, "trade_id", None)
        row.status = getattr(trade, "status", "PENDING")

        # If the API call failed to place the trade, release the slot immediately.
        if row.status in ("ERROR", "DRY_RUN") or not row.trade_id:
            self._open_trade_count = max(0, self._open_trade_count - 1)

        write_decision(log_path, row)
        if self._bridge:
            _now = datetime.now(timezone.utc)
            # Count how many signals actually agree on conf.direction (not total signals)
            agreeing_signals = sum(
                1 for sig_vals in (conf.breakdown or {}).values()
                if sig_vals[0] == conf.direction  # sig_vals = (direction, confidence, reason)
            )
            self._bridge.trade_opened({
                "trade_id": row.trade_id, "pair_raw": top.pair_raw, "pair_api": pair_api,
                "dir": dscreen.direction, "stake": settings.stake_amount,
                "entry": getattr(trade, "entry", None),
                "opened_at": _now.isoformat(),
                "expiry_at": (_now + timedelta(seconds=expiry)).isoformat(),
                "expiry_seconds": expiry,
                "confluence_n": agreeing_signals,
                "confluence_score": conf.score,
            })
        log.info(
            "[{}] TRADE {}  {}  @{:.2f}  exp={}s  payout={}%  prob={:.2f}  id={}",
            cid, dscreen.direction, pair_api, settings.stake_amount,
            expiry, payout_pct, d.combined_probability, row.trade_id,
        )

        # Schedule menu navigation in background (don't block main loop)
        asyncio.create_task(self._nav.back_to_menu())

        # Schedule background resolution instead of blocking
        if row.trade_id:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiry)
            self._open_trades[row.trade_id] = {
                "log_path": log_path,
                "row": row,
                "balance_before": balance_before,
                "expires_at": expires_at,
            }
            # Start background resolver (non-blocking)
            asyncio.create_task(self._resolve_trade_background(row.trade_id))

    async def _run_once_signals(self) -> None:
        """Option A: payout-first, signals-driven loop.

        Each cycle:
          1. Fetch all active pairs ≥ MIN_PAYOUT_PCT, sorted payout desc.
          2. For each pair (up to concurrency cap / MAX_PAIRS_PER_CYCLE):
             fetch candles → run confluence → decide_signals → risk gates → execute.
          3. Shadow signals are recorded for every evaluated pair (FR-5).
        Telegram navigator is NOT called in this path.
        """
        cid = self._next_cycle_id()
        log_path = settings.decisions_log_path

        all_pairs = await self._api.get_active_pairs()  # is_active filtered, sorted payout desc
        candidates = [
            p for p in all_pairs
            if p.get("symbol") not in settings.blocked_pairs
            and (settings.min_payout_pct == 0 or (p.get("payout") or 0) >= settings.min_payout_pct)
        ]
        if settings.max_pairs_per_cycle > 0:
            candidates = candidates[:settings.max_pairs_per_cycle]

        log.info("[{}] signals scan: {}/{} pairs ≥{}% payout  blocked={} max_per_cycle={}",
                 cid, len(candidates), len(all_pairs), settings.min_payout_pct,
                 len(settings.blocked_pairs), settings.max_pairs_per_cycle or "all")

        if not candidates:
            log.info("[{}] no pairs above payout floor — skipping cycle", cid)
            return

        balance_before = await self._api.balance()
        if self._bridge:
            self._bridge.heartbeat(
                mode=settings.trade_mode.value, dry_run=settings.dry_run,
                connected=True, balance=balance_before, currency="USD",
                active=[], last_cycle={"cycle_id": cid, "status": "scanning", "skip_reason": None},
                risk_block_reason=None,
            )

        expiry = select_expiry(settings.default_expiry_seconds, settings.allowed_expiries)
        candle_period = settings.candle_interval_seconds
        trades_placed = 0

        for pair_info in candidates:
            pair_api = pair_info["symbol"]
            payout_pct = pair_info.get("payout") or 0

            # Stop scanning if concurrency cap already full
            if self._open_trade_count >= self._max_concurrent_trades:
                log.info("[{}] concurrency cap reached ({}/{}) — stopping scan",
                         cid, self._open_trade_count, self._max_concurrent_trades)
                break

            candle_list = await self._api.get_candles(
                pair_api, period=candle_period, count=settings.history_length
            )
            df = candles_to_df(candle_list)
            if df.empty or len(df) < 30:
                log.debug("[{}] {} — insufficient candle data ({}) — skip", cid, pair_api, len(df))
                continue

            conf = await self._conf.score(df)

            # Per-signal table (same format as broker_bot path)
            for name, vals in (conf.breakdown or {}).items():
                sig_dir, sig_conf, sig_reason = (list(vals) + [None, None, None])[:3]
                log.info("[{}]   TA  {:14s} {}  conf={:.3f}  {}",
                         cid, name, f"{sig_dir or '----':<4}", sig_conf or 0.0, sig_reason or "")

            agreeing = sum(1 for v in (conf.breakdown or {}).values() if v[0] == conf.direction)
            total_signals = len(conf.breakdown or {})
            gate = "✓ PASS" if conf.direction is not None else "✗ FAIL"
            log.info(
                "[{}]   CONF {}  score={:.3f}  agreed={}/{}  {}  ({})  payout={}%",
                cid, conf.direction or "----", conf.score, agreeing, total_signals,
                gate, conf.reason, payout_pct,
            )

            # Get tracked win rate for P(win) and EV gate
            tracked_rate, n_tracked = self._tracker.rate(pair_api, conf.direction or "", expiry)

            d = decide_signals(
                our_direction=conf.direction,
                our_confluence=conf.score,
                tracked_win_rate=tracked_rate,
            )

            # In signals mode, bot_direction = conf.direction (the direction we trade).
            # _resolve_trade_background records tracker + risk entries using bot_direction,
            # so this must match the actual traded direction.
            row = DecisionRow(
                cycle_id=cid, pair_raw=pair_api, pair_api=pair_api,
                bot_win_rate=tracked_rate, bot_is_top_pick=False,
                bot_direction=conf.direction or "",
                bot_setup="signals",
                bot_indicators_raw="",
                our_direction=conf.direction, our_confluence_score=conf.score,
                our_signal_breakdown={k: list(v[:3]) for k, v in (conf.breakdown or {}).items()},
                agreement=True,
                combined_probability=d.combined_probability, expiry_seconds=expiry,
                decision="TRADE" if d.trade else "SKIP", skip_reason=d.skip_reason,
                stake=settings.stake_amount, balance_before=balance_before,
                payout_pct=payout_pct,
            )
            if d.trade:
                row.calibrated_probability = self._calibrator.predict({
                    "bot_win_rate": tracked_rate,
                    "our_confluence": conf.score,
                    "agreement": True,
                    "agreeing_signals": agreeing,
                    "payout_pct": payout_pct,
                    "bot_is_top_pick": False,
                })

            if not d.trade:
                write_decision(log_path, row)
                if self._bridge:
                    self._bridge.on_decision(asdict(row))
                log.info(
                    "[{}] SKIP {}  reason={}  (conf={}  score={:.2f}  payout={}%)",
                    cid, pair_api, d.skip_reason,
                    conf.direction or "None", conf.score, payout_pct,
                )
                continue

            # EV gate
            if payout_pct and n_tracked >= settings.min_ev_samples:
                ev = tracked_rate * (payout_pct / 100 + 1) - 1
                if ev < settings.min_expected_value:
                    row.decision = "SKIP"; row.skip_reason = "negative_ev"
                    write_decision(log_path, row)
                    if self._bridge:
                        self._bridge.on_decision(asdict(row))
                    log.info(
                        "[{}] SKIP {}  reason=negative_ev  ev={:.3f}  wr={:.1%}  n={}  payout={}%",
                        cid, pair_api, ev, tracked_rate, n_tracked, payout_pct,
                    )
                    continue

            # Risk gate — session-wide block, stop scanning all pairs
            if not self._risk.is_allowed(balance_before):
                row.decision = "SKIP"; row.skip_reason = "risk_blocked"
                write_decision(log_path, row)
                if self._bridge:
                    self._bridge.on_decision(asdict(row))
                log.warning("[{}] risk blocked: {}", cid, getattr(self._risk, "block_reason", ""))
                break

            # Concurrency cap (re-check; may have filled from a prior pair this cycle)
            if self._open_trade_count >= self._max_concurrent_trades:
                row.decision = "SKIP"; row.skip_reason = "max_concurrent_trades"
                write_decision(log_path, row)
                log.info("[{}] SKIP {}  reason=max_concurrent_trades  open={}/{}",
                         cid, pair_api, self._open_trade_count, self._max_concurrent_trades)
                break
            self._open_trade_count += 1

            api_call = self._api.buy if conf.direction == "CALL" else self._api.sell
            trade = await api_call(pair_api, settings.stake_amount, expiry)
            row.trade_id = getattr(trade, "trade_id", None)
            row.status = getattr(trade, "status", "PENDING")

            if row.status in ("ERROR", "DRY_RUN") or not row.trade_id:
                self._open_trade_count = max(0, self._open_trade_count - 1)

            write_decision(log_path, row)
            if self._bridge:
                _now = datetime.now(timezone.utc)
                self._bridge.trade_opened({
                    "trade_id": row.trade_id, "pair_raw": pair_api, "pair_api": pair_api,
                    "dir": conf.direction, "stake": settings.stake_amount,
                    "entry": getattr(trade, "entry", None),
                    "opened_at": _now.isoformat(),
                    "expiry_at": (_now + timedelta(seconds=expiry)).isoformat(),
                    "expiry_seconds": expiry,
                    "confluence_n": agreeing,
                    "confluence_score": conf.score,
                })
            log.info(
                "[{}] TRADE {}  {}  @{:.2f}  exp={}s  payout={}%  prob={:.2f}  id={}",
                cid, conf.direction, pair_api, settings.stake_amount,
                expiry, payout_pct, d.combined_probability, row.trade_id,
            )
            trades_placed += 1

            if row.trade_id:
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiry)
                self._open_trades[row.trade_id] = {
                    "log_path": log_path,
                    "row": row,
                    "balance_before": balance_before,
                    "expires_at": expires_at,
                }
                asyncio.create_task(self._resolve_trade_background(row.trade_id))

        log.info("[{}] signals cycle complete — {} trade(s) placed of {} evaluated",
                 cid, trades_placed, len(candidates))
        self._resolved_count = getattr(self, "_resolved_count", 0)
        if self._resolved_count > 0 and self._resolved_count % 10 == 0:
            self._log_ev_summary()

    async def _resolve_trade_background(self, trade_id: str) -> None:
        """Background task: wait for trade expiry, check outcome, update decisions.jsonl."""
        if trade_id not in self._open_trades:
            return
        try:
            trade_info = self._open_trades[trade_id]
            expires_at = trade_info["expires_at"]
            row = trade_info["row"]
            log_path = trade_info["log_path"]
            balance_before = trade_info["balance_before"]

            # Wait until trade expires
            now = datetime.now(timezone.utc)
            sleep_secs = max(0, (expires_at - now).total_seconds())
            if sleep_secs > 0:
                await asyncio.sleep(sleep_secs + 2)  # +2s buffer for API

            # Poll closed_deals instead of check_win: polling does not hold a
            # WebSocket subscription, so concurrent buy() calls are not blocked.
            outcome = await self._api.poll_trade_outcome(trade_id, max_polls=6, poll_interval=4.0)
            if outcome == "unknown":
                # Fallback to check_win only after polling exhausted — by this
                # point there are no in-flight buy() calls this trade can block.
                log.warning("[{}] poll exhausted for {} — falling back to check_win", row.cycle_id, trade_id)
                try:
                    outcome = await self._api.check_win(trade_id)
                except Exception as cw_exc:
                    log.error("check_win fallback failed for {}: {}", trade_id, cw_exc)
                    outcome = "unknown"
            balance_after = await self._api.balance()
            pnl = (balance_after - balance_before) if (balance_after is not None and balance_before is not None) else None

            backfill_outcome(log_path, trade_id=trade_id, outcome=outcome,
                             pnl=pnl if pnl is not None else 0.0,
                             balance_before=balance_before, balance_after=balance_after,
                             pnl_currency="USD")
            # Shadow trades are data-collection only: record their outcome to
            # decisions.jsonl (done above) but do NOT feed the production win-rate
            # tracker or risk stats, or they would contaminate live EV gating.
            if not getattr(row, "shadow", False):
                self._tracker.record(row.pair_api, row.bot_direction, row.expiry_seconds, outcome)
                risk_result = {"win": "WIN", "loss": "LOSS", "draw": "PENDING"}.get(outcome.lower(), "PENDING")
                self._risk.record_trade(row.bot_direction, row.stake, risk_result)

            # Notify dashboard with complete resolved data
            if self._bridge:
                self._bridge.trade_resolved({
                    **asdict(row),
                    "outcome": outcome.lower() if isinstance(outcome, str) else outcome,
                    "pnl": pnl if pnl is not None else 0.0,
                    "balance_after": balance_after,
                    "pnl_currency": "USD",
                })

            pnl_str = f"{pnl:+.2f}" if pnl is not None else "?"
            log.info("[{}] RESOLVED {}  pnl={}  balance={}", row.cycle_id, outcome.upper(), pnl_str, balance_after)

            self._resolved_count = getattr(self, "_resolved_count", 0) + 1
            if self._resolved_count % 10 == 0:
                self._log_ev_summary()

        except Exception as e:
            log.error(f"Background resolution failed for {trade_id}: {e}")
        finally:
            self._open_trades.pop(trade_id, None)
            self._open_trade_count = max(0, self._open_trade_count - 1)

    def _log_ev_summary(self) -> None:
        """Log a compact broker-calibration + EV table from decisions.jsonl."""
        try:
            path = Path(settings.decisions_log_path)
            if not path.exists():
                return
            rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
            trades = [r for r in rows if r.get("decision") == "TRADE" and r.get("outcome") in ("win", "loss")]
            if len(trades) < 5:
                return

            pair_stats: dict[str, dict] = defaultdict(lambda: {"w": 0, "l": 0, "bot_wrs": [], "payouts": []})
            for r in trades:
                p = r["pair_api"]
                pair_stats[p]["w" if r["outcome"] == "win" else "l"] += 1
                pair_stats[p]["bot_wrs"].append(r["bot_win_rate"])
                # Back-calc payout from win pnl if payout_pct not stored
                pp = r.get("payout_pct")
                if pp is None and r["outcome"] == "win" and r.get("pnl") and r.get("stake"):
                    pp = r["pnl"] / r["stake"] * 100
                if pp is not None:
                    pair_stats[p]["payouts"].append(float(pp))

            total = len(trades)
            wins = sum(1 for r in trades if r["outcome"] == "win")
            overall_wr = wins / total
            all_payouts = [p for d in pair_stats.values() for p in d["payouts"]]
            median_po = statistics.median(all_payouts) if all_payouts else 92.0
            overall_ev = overall_wr * (median_po / 100) - (1 - overall_wr)
            avg_pred = statistics.mean(r["bot_win_rate"] for r in trades)

            log.info(
                "── EV SUMMARY ({} trades) ──  actual={:.1%}  predicted={:.1%}  "
                "delta={:+.1%}  median_payout={:.0f}%  EV={:+.4f}",
                total, overall_wr, avg_pred, overall_wr - avg_pred, median_po, overall_ev,
            )
            for pair in sorted(pair_stats, key=lambda p: -(pair_stats[p]["w"] + pair_stats[p]["l"])):
                d = pair_stats[pair]
                n = d["w"] + d["l"]
                wr = d["w"] / n
                pout = statistics.median(d["payouts"]) if d["payouts"] else median_po
                ev = wr * (pout / 100) - (1 - wr)
                bot_wr = statistics.mean(d["bot_wrs"])
                flag = "✓" if ev >= 0 else "✗"
                log.info(
                    "  {:18s}  n={:3d}  act={:.1%}  bot={:.1%}  payout={:.0f}%  EV={:+.4f} {}",
                    pair, n, wr, bot_wr, pout, ev, flag,
                )
        except Exception as exc:
            log.debug("EV summary failed: {}", exc)
