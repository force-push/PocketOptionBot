# strategy/manager_v2.py
"""Telebot-evolution orchestrator: navigate → parse → TA → decide → API → record."""
from __future__ import annotations

from datetime import datetime, timezone

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
    def __init__(self, navigator, api_client, confluence_engine, risk_manager, tracker):
        self._nav = navigator
        self._api = api_client
        self._conf = confluence_engine
        self._risk = risk_manager
        self._tracker = tracker

    def _next_cycle_id(self) -> str:
        global _cycle_counter
        _cycle_counter += 1
        return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{_cycle_counter:04d}"

    async def run_once(self) -> None:
        cid = self._next_cycle_id()
        log_path = settings.decisions_log_path

        await self._nav.start_autotrade()
        pred_text, pred_btns = await self._nav.read_latest_text()
        pred = parse_prediction(pred_text)
        if not pred or not pred.top_pick():
            log.info("[%s] no prediction parsed; skipping", cid)
            return

        top = pred.top_pick()
        pair_api = normalize_pair(top.pair_raw)
        if pair_api is None:
            log.info("[%s] could not normalize pair %r", cid, top.pair_raw)
            return

        if top.win_rate < settings.pair_select_min_win_rate:
            log.info("[%s] %s win%% %.0f below gate %.0f — skip",
                     cid, pair_api, top.win_rate * 100, settings.pair_select_min_win_rate * 100)
            return

        if not await self._nav.select_pair(pair_api):
            log.info("[%s] pair select failed for %s", cid, pair_api)
            return

        dir_text, _ = await self._nav.read_latest_text()
        dscreen = parse_direction_screen(dir_text)
        if dscreen is None:
            log.info("[%s] no direction screen for %s", cid, pair_api)
            return

        expiry = select_expiry(settings.default_expiry_seconds, settings.allowed_expiries)
        candle_list = await self._api.get_candles(pair_api, period=expiry, count=settings.history_length)
        df = candles_to_df(candle_list)
        conf = await self._conf.score(df)

        d = decide(bot_direction=dscreen.direction, our_direction=conf.direction,
                   bot_win_rate=top.win_rate, our_confluence=conf.score,
                   our_score_floor=settings.min_confluence_score)

        balance_before = await self._api.balance()
        row = DecisionRow(
            cycle_id=cid, pair_raw=top.pair_raw, pair_api=pair_api,
            bot_win_rate=top.win_rate, bot_is_top_pick=top.is_top,
            bot_direction=dscreen.direction, bot_setup=dscreen.setup,
            bot_indicators_raw=dscreen.indicators_raw,
            our_direction=conf.direction, our_confluence_score=conf.score,
            our_signal_breakdown={k: list(v) for k, v in (conf.breakdown or {}).items()},
            agreement=(conf.direction == dscreen.direction),
            combined_probability=d.combined_probability, expiry_seconds=expiry,
            decision="TRADE" if d.trade else "SKIP", skip_reason=d.skip_reason,
            stake=settings.stake_amount, balance_before=balance_before,
        )

        if not d.trade:
            write_decision(log_path, row)
            log.info("[%s] SKIP %s: %s", cid, pair_api, d.skip_reason)
            await self._nav.back_to_menu()
            return

        if not self._risk.is_allowed(balance_before):
            row.decision = "SKIP"; row.skip_reason = "risk_blocked"
            write_decision(log_path, row)
            log.warning("[%s] risk blocked: %s", cid, getattr(self._risk, "block_reason", ""))
            await self._nav.back_to_menu()
            return

        api_call = self._api.buy if dscreen.direction == "CALL" else self._api.sell
        trade = await api_call(pair_api, settings.stake_amount, expiry)
        row.trade_id = getattr(trade, "trade_id", None)
        row.status = getattr(trade, "status", "PENDING")
        write_decision(log_path, row)
        log.info("[%s] TRADE %s %s @%.2f exp=%ds id=%s",
                 cid, dscreen.direction, pair_api, settings.stake_amount, expiry, row.trade_id)

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
            log.info("[%s] OUTCOME %s pnl=%s", cid, outcome, pnl)
