"""Event-driven flip catcher.

The poll loop re-scans each pair only every ~5-7s, so it misses most 1s
SuperTrend flips and enters survivors ~1-4s late — fatal for a 5s expiry. This
streamer subscribes to a live 1-second candle stream per focus pair
(``subscribe_symbol_timed``), evaluates the flip rule on each closed bar, and
places at the turn (~1s latency). It only acts on FRESH flips (the ~65% edge);
continuation stays with the poll loop.

Constraints / safety:
  • Concurrent symbol subscriptions cap at ~4 (tick probe) → STREAMING_PAIRS ≤ 4.
  • Placement goes through manager._place_flip_trade, which reserves the
    concurrency slot atomically and applies payout/in-flight/risk/EV gates, so
    the streamer can't double-trade a pair or breach the cap.
  • The poll loop excludes streamed pairs (manager) to avoid double evaluation.
  • Fail-soft: a stream error pauses that pair and retries; never raises.
"""
from __future__ import annotations

import asyncio
from typing import Any

from data.candles import candles_to_df
from strategy.flip_strategy import evaluate_flip, FlipParams
from strategy.flip_levers import load_levers
from utils.logger import log

_SUBSCRIPTION_CAP = 4
_BUFFER = 200  # rolling candles kept per pair (warmup for MACD/ADX/SuperTrend)


class FlipStreamer:
    def __init__(self, api_client: Any, manager: Any) -> None:
        self._api = api_client
        self._mgr = manager
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self.pairs: list[str] = []

    async def start(self, pairs: list[str]) -> None:
        await self.stop()
        self.pairs = list(pairs)[:_SUBSCRIPTION_CAP]
        if not self.pairs:
            return
        self._running = True
        for p in self.pairs:
            self._tasks.append(asyncio.create_task(self._consume(p), name=f"flipstream-{p}"))
        log.info("FlipStreamer started on {} pair(s): {}", len(self.pairs), self.pairs)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            if not t.done():
                t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []

    @staticmethod
    def _params(levers: dict) -> FlipParams:
        return FlipParams(
            st_period=levers["st_period"], st_multiplier=levers["st_multiplier"],
            adx_flip_min=levers["adx_flip_min"], adx_trend_min=levers["adx_trend_min"],
            adx_max=levers["adx_max"], require_adx_rising=levers["require_adx_rising"],
            atr_distance_min=levers["atr_distance_min"],
            cont_macd_gap_min=levers["cont_macd_gap_min"],
            flip_window_bars=levers["flip_window_bars"],
        )

    async def _consume(self, pair: str) -> None:
        last_bar_ts = None
        while self._running:
            try:
                # Seed the rolling buffer with real history so indicators are warm
                # the moment streaming starts.
                seed = await self._api.get_real_candles(pair, period=1)
                buf = list(seed)[-_BUFFER:]
                stream = await self._api.create_timed_stream(pair, 1)
                async for candle in stream:
                    if not self._running:
                        break
                    ts = candle.get("timestamp") if isinstance(candle, dict) else None
                    if ts is not None and ts == last_bar_ts:
                        # same bar updating; replace rather than append duplicates
                        buf[-1] = candle
                    else:
                        buf.append(candle)
                        last_bar_ts = ts
                    buf = buf[-_BUFFER:]
                    df = candles_to_df(buf)
                    if df.empty or len(df) < 40:
                        continue
                    levers = load_levers()
                    fd = evaluate_flip(df, self._params(levers))
                    # Streamer's job is catching the turn — act only on fresh flips.
                    if fd.direction and fd.entry_kind == "flip":
                        payout = await self._api.get_payout(pair)
                        await self._mgr._place_flip_trade(
                            pair, fd.direction, conf_score=1.0,
                            flip_metrics=fd.metrics, flip_levers=levers, payout_pct=payout,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("FlipStreamer {} error: {} — retry in 5s", pair, exc)
                await asyncio.sleep(5)
            finally:
                try:
                    await self._api.unsubscribe(pair)
                except Exception:  # noqa: BLE001
                    pass
