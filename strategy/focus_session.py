"""Focus-session manager: lock onto the best live pair, trade N flips, rotate.

Pair selection is dynamic — every rotation considers ALL active pairs above
`FOCUS_PAYOUT_FLOOR` (default 92%), not just a static allowlist.  Two runtime
filters cull unsuitable pairs:

  1. Payout floor (checked at selection AND monitored every ~30 bars mid-session).
     When a pair's payout drops below the floor the session aborts immediately
     and the rotation loop picks the next best pair.

  2. Tick-rate gate (checked after warmup).  Pairs with <FOCUS_MIN_TICK_RATE
     average ticks per 1s bar are too illiquid for reliable 1s OHLC; they are
     cooled off for 5 minutes before being re-considered.

The rotation loop mirrors how a manual trader works:
  1. Rank all active pairs by live payout.  Pick the highest above the floor.
  2. Subscribe to raw tick stream via TickAccumulator (~0-500ms lag).
  3. Evaluate evaluate_flip() on every closed 1s bar.
  4. Place trades through _place_flip_trade (same gate stack as poll/streamer).
  5. After FOCUS_SESSION_TRADES placements (or SESSION_TIMEOUT seconds), rotate.

The current focus pair is exposed on self.current_pair so the poll loop can
exclude it from its own scan (avoids double-evaluation on the same symbol).
"""
from __future__ import annotations

import asyncio
from typing import Any

from broker.tick_stream import TickAccumulator
from config.settings import settings
from data.candles import candles_to_df
from strategy.flip_levers import load_levers
from strategy.flip_strategy import FlipParams, evaluate_flip
from utils.logger import log

_WARMUP_BARS = 40        # min completed bars before evaluate_flip is called
_SESSION_TIMEOUT = 300   # seconds before forced rotation if trade quota not reached
_PAYOUT_CHECK_BARS = 30  # re-check live payout every N bar-closes (~30 seconds)
_ILLIQUID_COOLDOWN = 300  # seconds to skip an illiquid pair before re-trying
_TICK_CHECK_BARS = 20    # live bars to accumulate before checking tick rate
                         # (must be ≥ 20 so the check uses live data, not seeded history)


def _params(levers: dict) -> FlipParams:
    return FlipParams(
        st_period=levers["st_period"],
        st_multiplier=levers["st_multiplier"],
        adx_flip_min=levers["adx_flip_min"],
        adx_trend_min=levers["adx_trend_min"],
        adx_max=levers["adx_max"],
        require_adx_rising=levers["require_adx_rising"],
        atr_distance_min=levers["atr_distance_min"],
        cont_macd_gap_min=levers["cont_macd_gap_min"],
        flip_window_bars=levers["flip_window_bars"],
    )


class FocusSessionManager:
    """Lock onto the best payout pair, trade N flips, rotate."""

    def __init__(self, api_client: Any, manager: Any) -> None:
        self._api = api_client
        self._mgr = manager
        self._task: asyncio.Task | None = None
        self._running = False
        # pair → loop.time() when it was flagged illiquid; cleared after cooldown
        self._illiquid: dict[str, float] = {}
        # Current focus pair — read by manager to exclude from poll scan
        self.current_pair: str | None = None
        self.session_trades: int = 0   # trades placed in the current pair session
        self.total_trades: int = 0     # lifetime total

    async def start(self) -> None:
        await self.stop()
        self._running = True
        self._task = asyncio.create_task(self._run(), name="focus-session")
        log.info(
            "FocusSessionManager started — {} trades/pair, payout floor={}%",
            settings.focus_session_trades, settings.focus_payout_floor,
        )

    async def stop(self) -> None:
        self._running = False
        self.current_pair = None
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    # ── main rotation loop ────────────────────────────────────────────────────

    async def _run(self) -> None:
        while self._running:
            pair = await self._pick_pair()
            if pair is None:
                log.info(
                    "FocusSession: no pair ≥{}% payout — waiting 20s",
                    settings.focus_payout_floor,
                )
                await asyncio.sleep(20)
                continue

            self.current_pair = pair
            self.session_trades = 0
            log.info(
                "FocusSession ▶ {} — targeting {} trades (timeout {}s)",
                pair, settings.focus_session_trades, _SESSION_TIMEOUT,
            )
            try:
                await asyncio.wait_for(
                    self._run_pair_session(pair),
                    timeout=float(_SESSION_TIMEOUT),
                )
            except asyncio.TimeoutError:
                log.info(
                    "FocusSession: {} timed out after {}s ({} trades) — rotating",
                    pair, _SESSION_TIMEOUT, self.session_trades,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("FocusSession: {} session error: {} — rotating", pair, exc)
            finally:
                try:
                    await self._api.unsubscribe(pair)
                except Exception:  # noqa: BLE001
                    pass
                self.current_pair = None

            log.info(
                "FocusSession ■ {} — {} trades placed (total: {})",
                pair, self.session_trades, self.total_trades,
            )

    # ── pair selection ────────────────────────────────────────────────────────

    async def _pick_pair(self) -> str | None:
        """Highest-payout active pair above FOCUS_PAYOUT_FLOOR.

        Considers ALL active pairs (not restricted to ALLOWED_PAIRS) so the
        session can discover any high-payout opportunity dynamically.
        Pairs in blocked_pairs or in the illiquid cooldown set are skipped.
        """
        try:
            active = await self._api.get_active_pairs()
        except Exception as exc:  # noqa: BLE001
            log.debug("FocusSession._pick_pair error: {}", exc)
            return None

        floor = settings.focus_payout_floor
        blocked = set(settings.blocked_pairs)
        now = asyncio.get_event_loop().time()
        cooling = {p for p, t in self._illiquid.items() if now - t < _ILLIQUID_COOLDOWN}

        candidates = [
            p for p in active
            if (p.get("payout") or 0) >= floor
            and p.get("symbol") not in blocked
            and p.get("symbol") not in cooling
        ]
        if not candidates:
            if cooling:
                log.debug(
                    "FocusSession: {} pair(s) in illiquid cooldown: {}",
                    len(cooling), ", ".join(sorted(cooling)),
                )
            return None

        best = max(candidates, key=lambda p: p.get("payout", 0))
        log.debug(
            "FocusSession: {} candidates ≥{}% | picking {} at {}%",
            len(candidates), floor, best["symbol"], best.get("payout"),
        )
        return best["symbol"]

    # ── pair session ──────────────────────────────────────────────────────────

    async def _run_pair_session(self, pair: str) -> None:
        """Subscribe to raw ticks, evaluate flips, place until quota filled."""
        acc = TickAccumulator(pair)

        # Seed the rolling bar buffer so SuperTrend/MACD/ADX are warm immediately.
        try:
            seed = await asyncio.wait_for(
                self._api.get_real_candles(pair, period=1), timeout=12.0
            )
            if seed:
                seed_df = candles_to_df(list(seed)[-200:])
                if not seed_df.empty:
                    acc.seed_df(seed_df)
                    log.debug("FocusSession: {} seeded {} bars", pair, len(seed_df))
        except Exception as exc:  # noqa: BLE001
            log.debug("FocusSession: {} seed error (continuing cold): {}", pair, exc)

        handler = await self._api.create_raw_handler()
        await self._api.send_raw_message(
            f'42["changeSymbol",{{"asset":"{pair}","period":1}}]'
        )
        log.debug("FocusSession: raw tick stream subscribed for {}", pair)

        done = asyncio.Event()
        bars_since_payout_check = 0
        tick_rate_checked = False
        live_bars = 0  # bar-closes from live ticks (not seeded history)

        while not done.is_set() and self._running:
            try:
                raw = await asyncio.wait_for(handler.wait_next(), timeout=10.0)
            except asyncio.TimeoutError:
                log.debug("FocusSession: {} tick timeout — still waiting", pair)
                continue

            df = acc.process(raw)
            if df is None:
                continue

            n_bars = len(df)
            live_bars += 1

            # ── tick-rate liquidity gate ──────────────────────────────────────
            # After _TICK_CHECK_BARS live bar-closes, measure avg ticks using ONLY
            # the live bars (df.iloc[-live_bars:]).  Cannot use df["v"].tail(N):
            # seeded history bars may have v=0 from the OHLC API, giving a false
            # illiquid result even on active pairs.
            if not tick_rate_checked and live_bars >= _TICK_CHECK_BARS:
                tick_rate_checked = True
                avg_ticks = df.iloc[-live_bars:]["v"].mean()
                min_rate = settings.focus_min_tick_rate
                if avg_ticks < min_rate:
                    log.info(
                        "FocusSession: {} illiquid (avg {:.1f} ticks/bar < {}) "
                        "— cooling off {}s",
                        pair, avg_ticks, min_rate, _ILLIQUID_COOLDOWN,
                    )
                    self._illiquid[pair] = asyncio.get_event_loop().time()
                    return

            if n_bars < _WARMUP_BARS:
                continue

            # ── mid-session payout monitoring ─────────────────────────────────
            # If the broker drops payout below our floor, abandon this pair so
            # the rotation loop can find a better opportunity.
            bars_since_payout_check += 1
            if bars_since_payout_check >= _PAYOUT_CHECK_BARS:
                bars_since_payout_check = 0
                live_payout = await self._api.get_payout(pair)
                if live_payout is None or live_payout < settings.focus_payout_floor:
                    log.info(
                        "FocusSession: {} payout dropped to {}% (floor {}%) — rotating",
                        pair, live_payout, settings.focus_payout_floor,
                    )
                    return

            # ── flip evaluation ───────────────────────────────────────────────
            levers = load_levers()
            fd = evaluate_flip(df, _params(levers))
            if not fd.direction:
                continue

            payout = await self._api.get_payout(pair)
            placed = await self._mgr._place_flip_trade(
                pair, fd.direction,
                conf_score=1.0,
                flip_metrics=fd.metrics,
                flip_levers=levers,
                payout_pct=payout,
            )
            if placed:
                self.session_trades += 1
                self.total_trades += 1
                remaining = settings.focus_session_trades - self.session_trades
                log.info(
                    "FocusSession: {} trade {}/{} — {} {} | {} more to rotate",
                    pair, self.session_trades, settings.focus_session_trades,
                    fd.direction, fd.reason, remaining,
                )
                if self.session_trades >= settings.focus_session_trades:
                    done.set()
