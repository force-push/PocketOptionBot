# strategy/manager_v2.py
"""Telebot-evolution orchestrator: navigate → parse → TA → decide → API → record."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from config.settings import settings
from data.candles import candles_to_df
from strategy.decision import decide
from strategy.expiry import select_expiry
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

    def _next_cycle_id(self) -> str:
        global _cycle_counter
        _cycle_counter += 1
        return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{_cycle_counter:04d}"

    async def run_once(self) -> None:
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
        pair_api = normalize_pair(top.pair_raw)
        if pair_api is None:
            log.info("[{}] could not normalize pair {!r}", cid, top.pair_raw)
            return

        if top.win_rate < settings.pair_select_min_win_rate:
            log.info("[{}] {} win% {:.0f} below gate {:.0f} — skip",
                     cid, pair_api, top.win_rate * 100, settings.pair_select_min_win_rate * 100)
            return

        if not await self._nav.select_pair(pair_api):
            log.info("[{}] pair select failed for {}", cid, pair_api)
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

        if not d.trade:
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

        if not self._risk.is_allowed(balance_before):
            row.decision = "SKIP"; row.skip_reason = "risk_blocked"
            write_decision(log_path, row)
            if self._bridge:
                self._bridge.on_decision(asdict(row))
            log.warning("[{}] risk blocked: {}", cid, getattr(self._risk, "block_reason", ""))
            await self._nav.back_to_menu()
            return

        api_call = self._api.buy if dscreen.direction == "CALL" else self._api.sell
        trade = await api_call(pair_api, settings.stake_amount, expiry)
        row.trade_id = getattr(trade, "trade_id", None)
        row.status = getattr(trade, "status", "PENDING")
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
            "[{}] TRADE {}  {}  @{:.2f}  exp={}s  prob={:.2f}  id={}",
            cid, dscreen.direction, pair_api, settings.stake_amount,
            expiry, d.combined_probability, row.trade_id,
        )

        await self._nav.back_to_menu()

        if row.trade_id:
            outcome = await self._api.check_win(row.trade_id)
            balance_after = await self._api.balance()
            pnl = (balance_after - balance_before) if (balance_after is not None and balance_before is not None) else None
            backfill_outcome(log_path, trade_id=row.trade_id, outcome=outcome,
                             pnl=pnl if pnl is not None else 0.0,
                             balance_before=balance_before, balance_after=balance_after,
                             pnl_currency="USD")
            self._tracker.record(pair_api, dscreen.direction, expiry, outcome)
            risk_result = {"win": "WIN", "loss": "LOSS", "draw": "PENDING"}.get(outcome.lower(), "PENDING")
            self._risk.record_trade(dscreen.direction, settings.stake_amount, risk_result)
            if self._bridge:
                row.outcome = outcome
                row.pnl = pnl if pnl is not None else 0.0
                row.balance_after = balance_after
                self._bridge.trade_resolved({
                    **asdict(row),
                    "result": outcome.lower() if isinstance(outcome, str) else outcome,
                    "balance_after": balance_after,
                })
            pnl_str = f"{pnl:+.2f}" if pnl is not None else "?"
            log.info("[{}] OUTCOME {}  pnl={}  balance={}", cid, outcome.upper(), pnl_str, balance_after)
