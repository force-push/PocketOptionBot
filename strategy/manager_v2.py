# strategy/manager_v2.py
"""Signals-loop orchestrator: scan pairs → TA → decide → API → record.

Telegram integration removed 2026-06-12 — the signals loop is the only driver.
"""
from __future__ import annotations

import asyncio
import json
import statistics
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from broker.sentiment_collector import SentimentCollector
from config.settings import settings, TradeMode
from data.candles import candles_to_df
from strategy.decision import decide_signals, Decision
from strategy.flip_strategy import evaluate_flip
from strategy.flip_levers import load_levers, load_levers_5s, build_flip_params
from signals.confluence import ConfluenceResult
from strategy.expiry import select_expiry
from strategy.market_filters import TimeOfDayFilter
from strategy.probability_calibrator import ProbabilityCalibrator
from strategy.trade_logger import DecisionRow, write_decision, backfill_outcome
from utils.logger import log

_cycle_counter = 0


class StrategyManagerV2:
    def __init__(self, api_client, confluence_engine, risk_manager, tracker,
                 bridge=None):
        self._api = api_client
        self._conf = confluence_engine
        self._risk = risk_manager
        self._tracker = tracker
        # Optional dashboard StateBridge. All call sites are guarded by
        # `if self._bridge:` and the bridge itself never raises (fail-closed),
        # so trading behaviour is unchanged when the dashboard is disabled.
        self._bridge = bridge
        # Per-pair post-loss cooldown: a pair that just lost is skipped for
        # settings.post_loss_pair_cooldown_seconds (poll loop + FocusSession both
        # honour it and trade other pairs meanwhile). Shared via self so the
        # resolver, the poll scan, and FocusSession all see the same state.
        from strategy.pair_cooldown import PairCooldown
        self._pair_cooldown = PairCooldown()
        # Background trade resolver: maps trade_id → (log_path, row, expires_at)
        self._open_trades: dict = {}
        # Concurrent trade cap: never hold more than 6 unresolved trades at once.
        # Each slot is claimed at placement and released in _resolve_trade_background.
        self._open_trade_count: int = 0
        self._max_concurrent_trades: int = settings.max_open_trades
        # Calibrated win-probability model. Loads the saved model if present;
        # otherwise predict() falls back to the heuristic mean (never raises).
        self._calibrator = ProbabilityCalibrator.load()
        # Sentiment collector — live crowd-positioning (0-100) per pair.
        # Attached to the WS connection after connect(); stamps every DecisionRow.
        self._sentiment = SentimentCollector()
        # Skip hour rate-limiting: only log every 10 minutes during skip hours
        self._last_skip_log_time: datetime | None = None
        self._skip_log_interval_seconds = 600  # 10 minutes
        # Ensure the SQLite decision store exists before the first write.
        try:
            from data.decisions_store import init_db
            init_db(settings.decisions_db_path)
        except Exception as exc:  # never block startup on store init
            log.error("decision store init failed: {}", exc)
        # Event-driven flip streamer (started lazily in run_once when enabled).
        self._streamer = None
        # Focus-session manager (started lazily in run_once when enabled).
        self._focus: Any = None

    @property
    def tracker(self):
        """The WinRateTracker instance (owned here; exposed for startup seeding)."""
        return self._tracker

    def _next_cycle_id(self) -> str:
        global _cycle_counter
        _cycle_counter += 1
        return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{_cycle_counter:04d}"

    def _next_profitable_hour(self) -> tuple[int, int, float]:
        """Calculate next profitable trading hour, minutes until it arrives, and its WR.

        Returns:
            (next_hour_utc, minutes_until_next, win_rate_pct)
        """
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        current_minute = now.minute

        # Check all 24 hours starting from next hour
        profitable_hours = TimeOfDayFilter.PROFITABLE_HOURS

        for offset in range(1, 25):
            check_hour = (current_hour + offset) % 24
            if check_hour in profitable_hours:
                # Calculate minutes until this hour
                if offset == 1:
                    # Next hour in sequence
                    minutes = 60 - current_minute
                else:
                    # Multiple hours away: (hours × 60) - current_minute
                    minutes = (offset * 60) - current_minute
                return check_hour, minutes, profitable_hours[check_hour]

        # Fallback (shouldn't reach here if PROFITABLE_HOURS is non-empty)
        return current_hour, 0, 0.0

    @staticmethod
    def _format_countdown(minutes: int) -> str:
        """Format minutes as a human-readable countdown, e.g. '1h 23m' or '38m'."""
        h, m = divmod(max(0, minutes), 60)
        return f"{h}h {m}m" if h else f"{m}m"

    async def run_once(self) -> None:
        """Run one signals-loop cycle (the only driver since Telegram removal)."""
        # Attach sentiment collector on first run (API must be connected by now)
        if self._sentiment._handler is None:
            try:
                await self._sentiment.attach(self._api)
            except Exception as exc:
                log.warning("SentimentCollector attach failed (continuing without sentiment): {}", exc)
        # Start the event-driven flip streamer once, if enabled.
        if settings.streaming_enabled and self._streamer is None and settings.strategy_mode == "flip":
            try:
                from strategy.flip_streamer import FlipStreamer
                self._streamer = FlipStreamer(self._api, self)
                await self._streamer.start(settings.streaming_pairs)
            except Exception as exc:
                log.warning("FlipStreamer start failed (continuing with poll loop): {}", exc)
        # Start the focus-session manager once, if enabled.
        if settings.focus_session_enabled and self._focus is None and settings.strategy_mode == "flip":
            try:
                from strategy.focus_session import FocusSessionManager
                self._focus = FocusSessionManager(self._api, self)
                await self._focus.start()
            except Exception as exc:
                log.warning("FocusSessionManager start failed (continuing without): {}", exc)
        await self._run_once_signals()

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
        log_path = settings.decisions_db_path

        # Time-of-day filter: skip cycle if current hour is not profitable.
        # Disabled by default (TIME_OF_DAY_FILTER_ENABLED=false) — hour win
        # rates did not replicate across days (SHADOW_TRADE_ANALYSIS.md).
        # With SHADOW_TRADE_BLOCKED_HOURS=true (demo only), blocked hours still
        # run the full scan but place shadow trades instead of real ones —
        # collects 24h signal-outcome data without touching the real strategy.
        utc_hour = TimeOfDayFilter.current_hour()
        blocked_hour_shadow = False
        if settings.time_of_day_filter_enabled and not TimeOfDayFilter.is_allowed(utc_hour):
            skip_reason = TimeOfDayFilter.skip_reason(utc_hour)
            shadow_hours_enabled = (
                settings.shadow_trade_blocked_hours
                and settings.trade_mode != TradeMode.LIVE
            )

            # Rate-limit skip logs to once per 10 minutes
            now = datetime.now(timezone.utc)
            should_log = (
                self._last_skip_log_time is None or
                (now - self._last_skip_log_time).total_seconds() >= self._skip_log_interval_seconds
            )

            next_hour, minutes_until, next_wr = self._next_profitable_hour()
            countdown = self._format_countdown(minutes_until)

            if should_log:
                self._last_skip_log_time = now
                log.info(
                    "[{}] CYCLE {} — {}  (hour {utc_hour:02d}:00 UTC)  "
                    "Next trading: {next_hour:02d}:00 UTC in {countdown}  (WR {wr:.1f}%)",
                    cid, "SHADOW-ONLY" if shadow_hours_enabled else "SKIP",
                    skip_reason, utc_hour=utc_hour, next_hour=next_hour,
                    countdown=countdown, wr=next_wr,
                )

            # Update dashboard with countdown even if we don't log
            if self._bridge:
                self._bridge.heartbeat(
                    mode=settings.trade_mode.value, dry_run=settings.dry_run,
                    connected=True, balance=0, currency="USD",
                    active=[], last_cycle={"cycle_id": cid, "status": "skip", "skip_reason": skip_reason},
                    risk_block_reason=None,
                    skip_countdown={
                        "next_hour_utc": next_hour,
                        "minutes_until": minutes_until,
                        "countdown": countdown,
                        "win_rate_pct": next_wr,
                        "shadow_only": shadow_hours_enabled,
                    },
                )

            if not shadow_hours_enabled:
                return
            blocked_hour_shadow = True

        all_pairs = await self._api.get_active_pairs()  # is_active filtered, sorted payout desc
        # Pair eligibility (regex allowlist / exact allowlist / blocklist) is
        # centralised in pair_filter.is_pair_allowed so the poll loop and
        # FocusSession can never diverge. Each still honours the payout floor.
        from strategy.pair_filter import is_pair_allowed
        # Pairs handled by the event-driven streamer or focus-session are excluded
        # from the poll scan so they aren't evaluated/traded twice.
        streamed = set(settings.streaming_pairs) if (settings.streaming_enabled and self._streamer) else set()
        if self._focus and self._focus.current_pair:
            streamed = streamed | {self._focus.current_pair}
        # FX-only filter still applies alongside a regex allowlist (so a USD regex
        # doesn't pull in crypto/stock USD symbols). Only an EXACT allowed_pairs
        # list bypasses it — those are symbols the user picked deliberately.
        if settings.focus_fx_only and not settings.allowed_pairs:
            from strategy.focus_session import _is_fx_pair as _fx_check
        else:
            _fx_check = None
        candidates = [
            p for p in all_pairs
            if is_pair_allowed(p.get("symbol", ""))
            and p.get("symbol") not in streamed
            and not self._pair_cooldown.is_cooling(p.get("symbol", ""))
            and (settings.min_payout_pct == 0 or (p.get("payout") or 0) >= settings.min_payout_pct)
            and (_fx_check is None or _fx_check(p.get("symbol", "")))
        ]
        if settings.max_pairs_per_cycle > 0:
            candidates = candidates[:settings.max_pairs_per_cycle]

        if settings.allowed_pair_regex:
            filt_label, filt_val = "regex", settings.allowed_pair_regex
        elif settings.allowed_pairs:
            filt_label, filt_val = "allow", len(settings.allowed_pairs)
        else:
            filt_label, filt_val = "blocked", len(settings.blocked_pairs)
        log.info("[{}] {} scan: {}/{} pairs ≥{}% payout  {}={} max_per_cycle={}",
                 cid, settings.strategy_mode, len(candidates), len(all_pairs),
                 settings.min_payout_pct, filt_label, filt_val,
                 settings.max_pairs_per_cycle or "all")

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

        # Parallel candle prefetch (capped concurrency) — fetch all candidates'
        # history(1) up front so the per-pair decision loop runs fast and each pair
        # is evaluated more often (catches 1s flips the slow sequential fetch
        # missed). The cap avoids the WS-hang seen with unbounded concurrency.
        prefetched = await self._prefetch_candles(cid, candidates, candle_period)
        # 5s timeframe shadow track: second prefetch pass for 5s candles.
        # Sequential (not parallel) to avoid doubling WS pressure in one burst.
        prefetched_5s: dict = {}
        if settings.shadow_tf5s_enabled and settings.trade_mode != TradeMode.LIVE:
            prefetched_5s = await self._prefetch_candles(cid, candidates, 5)

        for pair_info in candidates:
            pair_api = pair_info["symbol"]
            payout_pct = pair_info.get("payout") or 0

            # Stop scanning if concurrency cap already full
            if self._open_trade_count >= self._max_concurrent_trades:
                log.info("[{}] concurrency cap reached ({}/{}) — stopping scan",
                         cid, self._open_trade_count, self._max_concurrent_trades)
                break

            # Per-pair pacing: don't open a new trade on a pair that still has an
            # unresolved trade — wait for it to expire (~5s) before re-deciding.
            if settings.one_open_trade_per_pair:
                inflight = {info["row"].pair_api for info in self._open_trades.values()}
                if pair_api in inflight:
                    log.debug("[{}] {} — trade in flight, skip until resolved", cid, pair_api)
                    continue

            df = prefetched.get(pair_api)
            if df is None or df.empty or len(df) < 30:
                log.debug("[{}] {} — insufficient candle data ({}) — skip",
                          cid, pair_api, 0 if df is None else len(df))
                continue

            # Feed-process probe: every 10th cycle, record this pair's return
            # autocorrelation/VR to data/feed_stats.jsonl (zero extra API load —
            # piggybacks the candles we already fetched). Builds the per-pair
            # repeated-measure dataset the one-off diagnostic can't provide.
            if _cycle_counter % 10 == 0:
                self._record_feed_stats(pair_api, df)

            if settings.strategy_mode == "flip":
                # SuperTrend flip / strong-trend continuation, confirmed by MACD + ADX.
                # Live-tunable levers (re-read each cycle from data/flip_levers.json
                # without restart; recorded per trade below for historical review).
                levers = load_levers()
                fd = evaluate_flip(df, build_flip_params(levers))
                conf = ConfluenceResult(
                    direction=fd.direction,
                    score=1.0 if fd.direction else 0.0,
                    breakdown={},
                    reason=fd.reason,
                )
                flip_metrics = fd.metrics
                flip_levers = levers
                agreeing = 3 if fd.direction else 0
                total_signals = 3
                tracked_rate, n_tracked = self._tracker.rate(pair_api, conf.direction or "", expiry)
                d = Decision(
                    trade=fd.direction is not None,
                    combined_probability=tracked_rate,
                    skip_reason=None if fd.direction else fd.reason,
                )
                if fd.direction is not None:
                    log.info("[{}]   FLIP {} [{}]  ({})  payout={}%",
                             cid, fd.direction, fd.entry_kind, fd.reason, payout_pct)
                else:
                    log.debug("[{}]   {} flip ✗  ({})  payout={}%",
                              cid, pair_api, fd.reason, payout_pct)
            else:
                conf = await self._conf.score(df)
                flip_metrics = None
                flip_levers = None

                agreeing = sum(1 for v in (conf.breakdown or {}).values() if v[0] == conf.direction)
                total_signals = len(conf.breakdown or {})
                gate = "✓ PASS" if conf.direction is not None else "✗ FAIL"

                # Only log the full per-signal table when the confluence gate passes (trade candidate).
                # On FAIL, emit a single compact summary line to keep logs readable across 64 pairs.
                if conf.direction is not None:
                    for name, vals in (conf.breakdown or {}).items():
                        sig_dir, sig_conf, sig_reason = (list(vals) + [None, None, None])[:3]
                        log.info("[{}]   TA  {:14s} {}  conf={:.3f}  {}",
                                 cid, name, f"{sig_dir or '----':<4}", sig_conf or 0.0, sig_reason or "")
                    log.info(
                        "[{}]   CONF {}  score={:.3f}  agreed={}/{}  {}  ({})  payout={}%",
                        cid, conf.direction, conf.score, agreeing, total_signals,
                        gate, conf.reason, payout_pct,
                    )
                else:
                    log.debug(
                        "[{}]   {} CONF ✗  agreed={}/{}  ({})  payout={}%",
                        cid, pair_api, agreeing, total_signals, conf.reason, payout_pct,
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
                sentiment=self._sentiment.get(pair_api),
                flip_metrics=flip_metrics,
                flip_levers=flip_levers,
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

            # ── Research shadow triggers (fire on every evaluated pair) ──────
            # FADE (Finding 4a): >=N signals agree on one direction → the move
            # is exhausted; shadow the OPPOSITE direction.
            if settings.shadow_fade_min_agree > 0:
                dir_counts = {"CALL": 0, "PUT": 0}
                for v in (conf.breakdown or {}).values():
                    sd = (list(v) + [None])[0]
                    if sd in dir_counts:
                        dir_counts[sd] += 1
                top_dir = max(dir_counts, key=dir_counts.get)
                if dir_counts[top_dir] >= settings.shadow_fade_min_agree:
                    fade_dir = "PUT" if top_dir == "CALL" else "CALL"
                    asyncio.create_task(self._place_single_shadow(
                        pair_api=pair_api, direction=fade_dir,
                        base_row=row, log_path=log_path,
                        shadow_kind="fade",
                        would_skip_reason=f"fade_{dir_counts[top_dir]}_agree_{top_dir}",
                    ))

            # ADX-REGIME (Finding 4b): strong trend (ADX conf >= threshold) →
            # shadow FOLLOWING the ADX direction.
            if settings.shadow_adx_regime_min_conf > 0:
                adx = (conf.breakdown or {}).get("ADX_DMI")
                if adx:
                    adx_dir, adx_conf = (list(adx) + [None, 0])[:2]
                    if adx_dir in ("CALL", "PUT") and (adx_conf or 0) >= settings.shadow_adx_regime_min_conf:
                        asyncio.create_task(self._place_single_shadow(
                            pair_api=pair_api, direction=adx_dir,
                            base_row=row, log_path=log_path,
                            shadow_kind="adx_regime",
                            would_skip_reason=f"adx_conf_{adx_conf:.2f}",
                        ))

            # 5s timeframe shadow: evaluate 5s candles independently of the 1s
            # decision. Fires for every pair (even 1s skips) to collect signal data.
            # Uses flip_levers_5s.json (5s-calibrated bb_width, confirm_bars, etc.).
            if prefetched_5s and settings.trade_mode != TradeMode.LIVE:
                df_5s = prefetched_5s.get(pair_api)
                if df_5s is not None and not df_5s.empty and len(df_5s) >= 40:
                    levers_5s = load_levers_5s()
                    fd_5s = evaluate_flip(df_5s, build_flip_params(levers_5s))
                    if fd_5s.direction is not None:
                        base_5s = replace(row, flip_metrics=fd_5s.metrics, flip_levers=levers_5s)
                        for exp in (settings.shadow_tf5s_expiry_seconds or [15, 30]):
                            asyncio.create_task(self._place_single_shadow(
                                pair_api=pair_api,
                                direction=fd_5s.direction,
                                base_row=base_5s,
                                log_path=log_path,
                                shadow_kind="tf5s",
                                would_skip_reason=f"tf5s_{fd_5s.entry_kind}_{exp}s",
                                expiry_override=exp,
                            ))
                        log.info("[{}] SHADOW-5S {} [{}] ({}) exp={}s",
                                 cid, fd_5s.direction, fd_5s.entry_kind,
                                 pair_api, settings.shadow_tf5s_expiry_seconds)

            if not d.trade:
                write_decision(log_path, row)
                if self._bridge:
                    self._bridge.on_decision(asdict(row))
                log.info(
                    "[{}] SKIP {}  reason={}  (conf={}  score={:.2f}  payout={}%)",
                    cid, pair_api, d.skip_reason,
                    conf.direction or "None", conf.score, payout_pct,
                )
                # Majority-blocked: place shadow trade at the score-winner direction
                # to collect outcome data. Over time this shows whether the majority
                # check is correctly blocking losing trades or incorrectly blocking winners.
                if d.skip_reason == "no_direction" and conf.majority_blocked_direction:
                    asyncio.create_task(self._place_single_shadow(
                        pair_api=pair_api,
                        direction=conf.majority_blocked_direction,
                        base_row=row,
                        log_path=log_path,
                        shadow_kind="majority_blocked",
                        would_skip_reason="majority_blocked",
                    ))
                continue

            # Blocked-hour shadow mode: the signal gates passed, but this hour is
            # blocked by the time-of-day filter. Place a shadow instead of a real
            # trade and skip the production EV/risk/concurrency gates entirely.
            if blocked_hour_shadow:
                asyncio.create_task(self._place_single_shadow(
                    pair_api=pair_api,
                    direction=conf.direction,
                    base_row=row,
                    log_path=log_path,
                    shadow_kind="time_of_day",
                    would_skip_reason=TimeOfDayFilter.skip_reason(utc_hour),
                ))
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

            # Capture balance at the moment this specific trade is placed.
            # All concurrent trades in a burst share the same cycle-start `balance_before`
            # above, which makes individual pnl = balance_after - balance_before meaningless
            # (wins show negative pnl because prior concurrent losses already reduced the
            # balance). Fetching fresh here gives an accurate per-trade baseline.
            balance_at_placement = await self._api.balance()
            row.balance_before = balance_at_placement

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

            # Stagger placements so PO doesn't receive a burst of simultaneous orders.
            # Sleep after every trade except the last slot; still fires concurrently
            # since resolution happens in background tasks started below.
            if settings.trade_stagger_seconds > 0 and self._open_trade_count < self._max_concurrent_trades:
                await asyncio.sleep(settings.trade_stagger_seconds)

            if row.trade_id:
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiry)
                self._open_trades[row.trade_id] = {
                    "log_path": log_path,
                    "row": row,
                    "balance_before": balance_at_placement,
                    "expires_at": expires_at,
                }
                asyncio.create_task(self._resolve_trade_background(row.trade_id))

                # Shadow expiry experiment: replicate this entry at other durations
                # (demo only, research). Fired as a background task so the 4 shadow
                # placements (60/120/216/300s) don't block the scan — each API call
                # carries its own 20s buy() timeout so they still resolve cleanly.
                asyncio.create_task(self._place_shadow_expiry_trades(
                    pair_api=pair_api, direction=conf.direction, base_row=row,
                    log_path=log_path,
                ))

        log.info("[{}] signals cycle complete — {} trade(s) placed of {} evaluated",
                 cid, trades_placed, len(candidates))
        self._resolved_count = getattr(self, "_resolved_count", 0)
        if self._resolved_count > 0 and self._resolved_count % 10 == 0:
            self._log_ev_summary()

    async def _place_shadow_expiry_trades(self, *, pair_api, direction, base_row, log_path) -> None:
        """Place demo shadow trades at each configured experiment expiry.

        For every real signals-loop trade we replicate the same pair + direction
        at the durations in SHADOW_EXPIRY_SECONDS (e.g. 50/80/130/210s). Each is
        flagged shadow=True, shadow_kind="expiry" so it:
          • never feeds the production win-rate tracker or risk stats
            (guarded in _resolve_trade_background by `if not row.shadow`),
          • never consumes the real concurrency budget (_open_trade_count),
          • is excluded from the UI history (decision=TRADE but shadow=True).
        HARD GUARD: research only — skipped entirely in LIVE.
        """
        expiries = settings.shadow_expiry_seconds or []
        if not expiries or settings.trade_mode == TradeMode.LIVE:
            return
        api_call = self._api.buy if direction == "CALL" else self._api.sell
        for exp in expiries:
            try:
                bal = await self._api.balance()
                trade = await api_call(pair_api, settings.stake_amount, exp)
                tid = getattr(trade, "trade_id", None)
                status = getattr(trade, "status", "PENDING")
                srow = replace(
                    base_row,
                    expiry_seconds=exp,
                    shadow=True,
                    shadow_kind="expiry",
                    would_skip_reason=None,
                    trade_id=tid,
                    status=status,
                    balance_before=bal,
                    outcome=None, pnl=None, balance_after=None,
                    ts=datetime.now(timezone.utc).isoformat(),
                )
                write_decision(log_path, srow)
                log.info("[{}] SHADOW-EXP {}  {}  exp={}s  id={}",
                         base_row.cycle_id, direction, pair_api, exp, tid)
                if tid and status not in ("ERROR", "DRY_RUN"):
                    self._open_trades[tid] = {
                        "log_path": log_path,
                        "row": srow,
                        "balance_before": bal,
                        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=exp),
                    }
                    asyncio.create_task(self._resolve_trade_background(tid))
            except Exception as exc:
                log.warning("[{}] shadow expiry {}s failed for {}: {}",
                            base_row.cycle_id, exp, pair_api, exc)

    async def _prefetch_candles(self, cid, candidates, candle_period) -> dict:
        """Fetch all candidates' candles concurrently (capped) → {symbol: df|None}.

        Bounded by CANDLE_FETCH_CONCURRENCY so we don't trip the WS hang seen with
        unbounded parallel history() calls (git history 2026-06-13). Per-call
        timeouts live in get_real_candles/get_candles; a failed fetch → None df.
        """
        sem = asyncio.Semaphore(settings.candle_fetch_concurrency)

        async def _one(sym):
            async with sem:
                try:
                    if settings.use_real_ohlc:
                        cl = await self._api.get_real_candles(sym, period=candle_period)
                    else:
                        cl = await self._api.get_candles(
                            sym, period=candle_period, count=settings.history_length
                        )
                    return sym, candles_to_df(cl)
                except Exception as exc:
                    log.debug("[{}] prefetch {} failed: {}", cid, sym, exc)
                    return sym, None

        results = await asyncio.gather(*[_one(p["symbol"]) for p in candidates])
        return dict(results)

    def _record_feed_stats(self, pair_api: str, df) -> None:
        """Append this pair's return-process stats to data/feed_stats.jsonl.

        Lag-1/2 autocorrelation + VR(2) of log-returns over the live candle
        window. Repeated measurements per pair let us separate real per-pair
        mean-reversion/momentum character from single-window sampling noise
        (the one-off diagnostic showed cross-pair spread ≈ noise at n=1
        window). Fail-silent: research instrumentation must never break the
        trading loop.
        """
        try:
            import numpy as np
            c = df["c"].to_numpy(dtype=float)
            r = np.diff(np.log(c))
            r = r[np.isfinite(r)]
            if len(r) < 80 or r.std() == 0:
                return

            def ac(k: int):
                a, b = r[:-k], r[k:]
                if a.std() == 0 or b.std() == 0:
                    return None
                return float(((a - a.mean()) * (b - b.mean())).mean() / (a.std() * b.std()))

            v1 = r.var(ddof=1)
            r2 = r[: len(r) // 2 * 2].reshape(-1, 2).sum(axis=1)
            vr2 = float(r2.var(ddof=1) / (2 * v1)) if v1 > 0 else None
            row = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "pair": pair_api,
                "n": int(len(r)),
                "ac1": ac(1), "ac2": ac(2), "vr2": vr2,
                "zero_pct": float((r == 0).mean()),
            }
            with Path("data/feed_stats.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except Exception:
            pass

    async def _place_flip_trade(self, pair_api, direction, *, conf_score, flip_metrics,
                                flip_levers, payout_pct) -> bool:
        """Place a flip trade from the event-driven streamer.

        Self-contained mirror of the scan loop's placement gates (payout, per-pair
        in-flight, concurrency, risk, EV) so the streamer never double-trades a
        pair or breaches the concurrency cap. The concurrency slot is reserved
        BEFORE any await (cheap checks → increment) so concurrent per-pair stream
        consumers can't race past the cap. Returns True if a trade was placed.
        """
        if direction not in ("CALL", "PUT"):
            return False
        if settings.min_payout_pct and (payout_pct or 0) < settings.min_payout_pct:
            return False
        # ── atomic reservation: no await between these checks and the increment ──
        if settings.one_open_trade_per_pair:
            inflight = {info["row"].pair_api for info in self._open_trades.values()}
            if pair_api in inflight:
                return False
        if self._open_trade_count >= self._max_concurrent_trades:
            return False
        self._open_trade_count += 1
        try:
            cid = self._next_cycle_id()
            expiry = select_expiry(settings.default_expiry_seconds, settings.allowed_expiries)
            log_path = settings.decisions_db_path
            tracked_rate, n_tracked = self._tracker.rate(pair_api, direction, expiry)
            balance = await self._api.balance()
            if not self._risk.is_allowed(balance or 0):
                self._open_trade_count = max(0, self._open_trade_count - 1)
                return False
            if payout_pct and n_tracked >= settings.min_ev_samples:
                ev = tracked_rate * (payout_pct / 100 + 1) - 1
                if ev < settings.min_expected_value:
                    self._open_trade_count = max(0, self._open_trade_count - 1)
                    return False
            row = DecisionRow(
                cycle_id=cid, pair_raw=pair_api, pair_api=pair_api,
                bot_win_rate=tracked_rate, bot_is_top_pick=False,
                bot_direction=direction, bot_setup="flip_stream", bot_indicators_raw="",
                our_direction=direction, our_confluence_score=conf_score,
                our_signal_breakdown={}, agreement=True,
                combined_probability=tracked_rate, expiry_seconds=expiry,
                decision="TRADE", skip_reason=None,
                stake=settings.stake_amount, balance_before=balance,
                payout_pct=payout_pct, sentiment=None,
                flip_metrics=flip_metrics, flip_levers=flip_levers,
            )
            api_call = self._api.buy if direction == "CALL" else self._api.sell
            trade = await api_call(pair_api, settings.stake_amount, expiry)
            row.trade_id = getattr(trade, "trade_id", None)
            row.status = getattr(trade, "status", "PENDING")
            if row.status in ("ERROR", "DRY_RUN") or not row.trade_id:
                self._open_trade_count = max(0, self._open_trade_count - 1)
            write_decision(log_path, row)
            log.info("[{}] STREAM-FLIP {}  {}  @{:.2f}  exp={}s  payout={}%  id={}",
                     cid, direction, pair_api, settings.stake_amount, expiry, payout_pct, row.trade_id)
            if row.trade_id and row.status not in ("ERROR", "DRY_RUN"):
                if self._bridge:
                    _now = datetime.now(timezone.utc)
                    self._bridge.trade_opened({
                        "trade_id": row.trade_id, "pair_raw": pair_api, "pair_api": pair_api,
                        "dir": direction, "stake": settings.stake_amount,
                        "opened_at": _now.isoformat(),
                        "expiry_at": (_now + timedelta(seconds=expiry)).isoformat(),
                        "expiry_seconds": expiry,
                    })
                self._open_trades[row.trade_id] = {
                    "log_path": log_path, "row": row,
                    "balance_before": balance,
                    "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expiry),
                }
                asyncio.create_task(self._resolve_trade_background(row.trade_id))
                return True
            return False
        except Exception as exc:
            self._open_trade_count = max(0, self._open_trade_count - 1)
            log.error("_place_flip_trade {} failed: {}", pair_api, exc)
            return False

    async def _place_single_shadow(
        self, *, pair_api, direction, base_row, log_path,
        shadow_kind, would_skip_reason, expiry_override=None,
    ) -> None:
        """Place one shadow trade flagged with the given shadow_kind.

        Used for research data collection on setups the real strategy doesn't
        trade — e.g. majority-blocked signal minorities ("majority_blocked"),
        blocked-hour scans ("time_of_day"), and 5s timeframe shadows ("tf5s").
        Shadows never feed the production tracker/risk stats and never consume
        the real concurrency budget. HARD GUARD: research only — skipped in LIVE.
        expiry_override: when set, bypasses select_expiry and uses this value
        directly (e.g. for tf5s shadows that need a specific expiry like 15s/30s).
        """
        if settings.trade_mode == TradeMode.LIVE:
            return
        try:
            bal = await self._api.balance()
            expiry = (expiry_override
                      if expiry_override is not None
                      else select_expiry(settings.default_expiry_seconds, settings.allowed_expiries))
            api_call = self._api.buy if direction == "CALL" else self._api.sell
            trade = await api_call(pair_api, settings.stake_amount, expiry)
            tid = getattr(trade, "trade_id", None)
            status = getattr(trade, "status", "PENDING")
            srow = replace(
                base_row,
                expiry_seconds=expiry,
                shadow=True,
                shadow_kind=shadow_kind,
                would_skip_reason=would_skip_reason,
                bot_direction=direction,
                our_direction=direction,
                decision="TRADE",
                skip_reason=None,
                trade_id=tid,
                status=status,
                balance_before=bal,
                outcome=None, pnl=None, balance_after=None,
                ts=datetime.now(timezone.utc).isoformat(),
            )
            write_decision(log_path, srow)
            log.info(
                "[{}] SHADOW[{}] {}  {}  exp={}s  id={}",
                base_row.cycle_id, shadow_kind, direction, pair_api, expiry, tid,
            )
            if tid and status not in ("ERROR", "DRY_RUN"):
                self._open_trades[tid] = {
                    "log_path": log_path,
                    "row": srow,
                    "balance_before": bal,
                    "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expiry),
                }
                asyncio.create_task(self._resolve_trade_background(tid))
        except Exception as exc:
            log.warning("[{}] {} shadow failed for {}: {}",
                        base_row.cycle_id, shadow_kind, pair_api, exc)

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
            # Wrap in timeout to prevent hang (issue: 2026-06-10 bot hung at 18:48)
            try:
                outcome = await asyncio.wait_for(
                    self._api.poll_trade_outcome(trade_id, max_polls=6, poll_interval=4.0),
                    timeout=30.0  # 30s timeout: 6 polls × 4s + buffer
                )
            except asyncio.TimeoutError:
                log.warning("[{}] poll_trade_outcome timeout for {} — falling back to check_win", row.cycle_id, trade_id)
                outcome = "unknown"
            except Exception as poll_exc:
                log.warning("[{}] poll_trade_outcome error for {}: {} — falling back to check_win", row.cycle_id, trade_id, poll_exc)
                outcome = "unknown"

            if outcome == "unknown":
                # Fallback to check_win only after polling exhausted — by this
                # point there are no in-flight buy() calls this trade can block.
                log.warning("[{}] poll exhausted for {} — falling back to check_win", row.cycle_id, trade_id)
                try:
                    outcome = await asyncio.wait_for(
                        self._api.check_win(trade_id),
                        timeout=10.0  # 10s timeout for check_win
                    )
                except asyncio.TimeoutError:
                    log.error("check_win timeout for {}", trade_id)
                    outcome = "unknown"
                except Exception as cw_exc:
                    log.error("check_win fallback failed for {}: {}", trade_id, cw_exc)
                    outcome = "unknown"
            balance_after = await self._api.balance()
            # Deterministic pnl: avoid concurrent balance noise by computing from
            # outcome + payout instead of measuring balance_after - balance_before.
            # With staggered concurrent trades, balance movements overlap and corrupt
            # the measurement. True P&L is always: win → +stake×(payout/100),
            # loss → -stake, draw → 0.
            payout_pct = row.payout_pct or 0.0
            if outcome.lower() == "win":
                pnl = row.stake * (payout_pct / 100.0)
            elif outcome.lower() == "loss":
                pnl = -row.stake
            else:
                pnl = 0.0

            backfill_outcome(log_path, trade_id=trade_id, outcome=outcome,
                             pnl=pnl,
                             balance_before=balance_before, balance_after=balance_after,
                             pnl_currency="USD")
            # Shadow trades are data-collection only: record their outcome to
            # decisions.jsonl (done above) but do NOT feed the production win-rate
            # tracker or risk stats, or they would contaminate live EV gating.
            if not getattr(row, "shadow", False):
                self._tracker.record(row.pair_api, row.bot_direction, row.expiry_seconds, outcome)
                risk_result = {"win": "WIN", "loss": "LOSS", "draw": "PENDING"}.get(outcome.lower(), "PENDING")
                self._risk.record_trade(row.bot_direction, row.stake, risk_result)
                # Start the per-pair post-loss cooldown so neither the poll loop
                # nor FocusSession re-enters this pair during its weak window.
                if outcome.lower() == "loss":
                    self._pair_cooldown.record_loss(row.pair_api)

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
        """Log a compact broker-calibration + EV table from the decision store.

        Uses a SQL ``GROUP BY`` aggregate (``pair_ev_aggregates``) rather than
        loading the full decision history into memory — this is a periodic,
        log-only diagnostic and must not bloat the trading process. (Payout is an
        average rather than a per-trade median; payouts cluster ~92% so the EV
        figures shown are unchanged in practice. No effect on trading behaviour.)
        """
        try:
            from data.decisions_store import pair_ev_aggregates
            aggs = [a for a in pair_ev_aggregates(settings.decisions_db_path)
                    if ((a.get("w") or 0) + (a.get("l") or 0)) > 0]
            total = sum((a["w"] or 0) + (a["l"] or 0) for a in aggs)
            if total < 5:
                return

            wins = sum(a["w"] or 0 for a in aggs)
            overall_wr = wins / total
            payouts = [a["payout"] for a in aggs if a["payout"] is not None]
            median_po = statistics.median(payouts) if payouts else 92.0
            overall_ev = overall_wr * (median_po / 100) - (1 - overall_wr)
            # Trade-count-weighted mean of per-pair bot_win_rate == mean over all
            # trades (matches the previous overall predicted figure).
            avg_pred = sum((a["bot_wr"] or 0) * ((a["w"] or 0) + (a["l"] or 0))
                           for a in aggs) / total

            log.info(
                "── EV SUMMARY ({} trades) ──  actual={:.1%}  predicted={:.1%}  "
                "delta={:+.1%}  median_payout={:.0f}%  EV={:+.4f}",
                total, overall_wr, avg_pred, overall_wr - avg_pred, median_po, overall_ev,
            )
            for a in sorted(aggs, key=lambda a: -((a["w"] or 0) + (a["l"] or 0))):
                n = (a["w"] or 0) + (a["l"] or 0)
                wr = (a["w"] or 0) / n
                pout = a["payout"] if a["payout"] is not None else median_po
                ev = wr * (pout / 100) - (1 - wr)
                bot_wr = a["bot_wr"] or 0.0
                flag = "✓" if ev >= 0 else "✗"
                log.info(
                    "  {:18s}  n={:3d}  act={:.1%}  bot={:.1%}  payout={:.0f}%  EV={:+.4f} {}",
                    a["pair"], n, wr, bot_wr, pout, ev, flag,
                )
        except Exception as exc:
            log.debug("EV summary failed: {}", exc)
