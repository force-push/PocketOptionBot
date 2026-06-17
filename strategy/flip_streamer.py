"""Event-driven flip catcher — raw-tick edition.

The poll loop re-scans each pair only every ~5-7s, so it misses most 1s
SuperTrend flips and enters survivors ~1-4s late — fatal for a 5s expiry.

Previously this streamer used ``subscribe_symbol_timed`` (1s bar-close callback,
~1-2s entry lag).  It now uses ``RawTickStream``, which accumulates raw price
ticks from the shared WS handler into 1s OHLC bars and emits each bar the
instant the second boundary crosses — cutting entry lag to ~0-500ms.

Constraints / safety:
  • Concurrent subscriptions cap at ~4 → STREAMING_PAIRS ≤ 4 (unchanged).
  • Placement goes through manager._place_flip_trade (atomic concurrency slot +
    payout/in-flight/risk/EV gates), so the streamer can't double-trade a pair
    or breach the cap.
  • The poll loop excludes streamed pairs (manager) to avoid double evaluation.
  • Fail-soft: a stream error pauses that pair 5s and retries; never raises.
"""
from __future__ import annotations

import asyncio
from typing import Any

from broker.tick_stream import RawTickStream
from data.candles import candles_to_df
from strategy.flip_strategy import evaluate_flip, FlipParams
from strategy.flip_levers import load_levers
from utils.logger import log

_SUBSCRIPTION_CAP = 4
_BUFFER = 200  # rolling bars kept per pair (warmup for MACD/ADX/SuperTrend)
_MIN_BARS = 40  # minimum completed bars before evaluate_flip is called


class FlipStreamer:
    def __init__(self, api_client: Any, manager: Any) -> None:
        self._api = api_client
        self._mgr = manager
        self._tasks: dict[str, asyncio.Task] = {}   # pair → task
        self._running = False

    @property
    def pairs(self) -> list[str]:
        return list(self._tasks)

    async def start(self, pairs: list[str]) -> None:
        """Initial start — delegates to rotate()."""
        await self.rotate(pairs)

    async def rotate(self, new_pairs: list[str]) -> None:
        """Swap active streams to match new_pairs (diff-based, no unnecessary restarts).

        Stops streams for pairs no longer wanted (dropped below payout floor or
        entered cooldown), starts streams for newly eligible pairs. Pairs already
        streaming and still in new_pairs are left untouched — no disruption to
        an ongoing winning run.
        """
        self._running = True
        wanted = set(list(new_pairs)[:_SUBSCRIPTION_CAP])
        current = set(self._tasks)

        to_stop = current - wanted
        to_start = wanted - current

        for pair in to_stop:
            await self._stop_pair(pair)

        for pair in to_start:
            self._start_pair(pair)

        if to_stop or to_start:
            log.info(
                "FlipStreamer rotated — added: {} removed: {} active: {}",
                sorted(to_start), sorted(to_stop), sorted(self._tasks),
            )

    async def stop(self) -> None:
        self._running = False
        for pair in list(self._tasks):
            await self._stop_pair(pair)

    def _start_pair(self, pair: str) -> None:
        task = asyncio.create_task(self._consume(pair), name=f"flipstream-{pair}")
        self._tasks[pair] = task

    async def _stop_pair(self, pair: str) -> None:
        task = self._tasks.pop(pair, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    @staticmethod
    def _params(levers: dict) -> FlipParams:
        from strategy.flip_levers import build_flip_params
        return build_flip_params(levers)

    async def _consume(self, pair: str) -> None:
        while self._running:
            stream: RawTickStream | None = None
            try:
                # Pre-warm the accumulator from real OHLC history so indicators
                # are ready immediately (no cold-start period waiting for bars).
                seed_candles = await self._api.get_real_candles(pair, period=1)
                seed_df = candles_to_df(list(seed_candles)[-_BUFFER:])

                stream = RawTickStream(self._api, pair, history_bars=_BUFFER)
                if not seed_df.empty:
                    stream.seed(seed_df)
                await stream.start()

                async for df in stream:
                    if not self._running:
                        break
                    if df.empty or len(df) < _MIN_BARS:
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
                if stream is not None:
                    await stream.stop()
