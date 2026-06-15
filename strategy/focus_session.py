"""Focus-session manager: lock onto the best live pair, trade N flips, rotate.

Pair selection is dynamic — every rotation considers ALL active pairs above
`FOCUS_PAYOUT_FLOOR` (default 90%), not just a static allowlist.  Two runtime
filters cull unsuitable pairs:

  1. Payout floor (checked at selection AND monitored every ~30 bars mid-session).
     When a pair's payout drops below the floor the session aborts immediately
     and the rotation loop picks the next best pair.

  2. Illiquid detection: if no candle bar arrives within 15s for 60s straight,
     the pair is cooled off for 5 minutes before being re-considered.

The rotation loop mirrors how a manual trader works:
  1. Rank all active pairs by live payout.  Pick the highest above the floor.
  2. Subscribe to 1s candle stream via create_timed_stream (same as FlipStreamer).
  3. Evaluate evaluate_flip() on every closed 1s bar.
  4. Place trades through _place_flip_trade (same gate stack as poll/streamer).
  5. After FOCUS_SESSION_TRADES placements (or SESSION_TIMEOUT seconds), rotate.

The current focus pair is exposed on self.current_pair so the poll loop can
exclude it from its own scan (avoids double-evaluation on the same symbol).
"""
from __future__ import annotations

import asyncio
from typing import Any

from config.settings import settings
from data.candles import candles_to_df
from strategy.flip_levers import load_levers
from strategy.flip_strategy import FlipParams, evaluate_flip
from utils.logger import log

_WARMUP_BARS = 40        # min completed bars before evaluate_flip is called
_SESSION_TIMEOUT = 300   # seconds before forced rotation if trade quota not reached
_PAYOUT_CHECK_BARS = 30  # re-check live payout every N bar-closes (~30 seconds)
_ILLIQUID_COOLDOWN = 300  # seconds to skip an illiquid pair before re-trying
_TICK_CHECK_BARS = 10    # live bars threshold for illiquid detection
_BAR_TIMEOUT = 15        # seconds between bars before considering pair illiquid
_ILLIQUID_ELAPSED = 60   # seconds elapsed + <_TICK_CHECK_BARS bars → flag illiquid

# Crypto base-currency prefixes that appear as 6-char OTC symbols (e.g. BTCUSD).
_CRYPTO_PREFIXES = {"BTC", "ETH", "BNB", "SOL", "ADA", "XRP", "LTC", "TRX",
                    "XLM", "DOT", "MAT", "UNI", "LNK", "AVA", "DFX", "BIT"}


def _is_fx_pair(symbol: str) -> bool:
    """Return True if the PocketOption OTC symbol looks like a forex pair.

    Accepts: EURUSD_otc, AUDCAD_otc, NGNUSD_otc, JODCNY_otc (6-char alpha + _otc)
    Rejects: #MSFT_otc (stock), CITI_otc (4-char stock), BNB-USD_otc (dash=crypto),
             BTCUSD_otc (crypto prefix), DOGE_otc (4-char crypto), VIX_otc (index).
    """
    base = symbol.removesuffix("_otc")
    if base.startswith("#"):        # stock (PocketOption prefixes stocks with #)
        return False
    if "-" in base:                 # crypto like BNB-USD, TRX-USD
        return False
    if len(base) != 6 or not base.isalpha():  # forex pairs are always 6 alpha chars
        return False
    if base[:3].upper() in _CRYPTO_PREFIXES:  # crypto disguised as forex-length
        return False
    return True


def _params(levers: dict) -> FlipParams:
    from strategy.flip_levers import build_flip_params
    return build_flip_params(levers)


async def _anext(aiter: Any) -> Any:
    """Await the next item from an async iterator (Python 3.9 compatible)."""
    return await aiter.__anext__()


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
        Pairs in blocked_pairs, in the illiquid cooldown set, or already being
        streamed by FlipStreamer are skipped.
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
        fx_only = settings.focus_fx_only
        # Skip pairs already covered by FlipStreamer to avoid subscription conflicts
        already_streamed = set(settings.streaming_pairs) if settings.streaming_enabled else set()

        candidates = [
            p for p in active
            if (p.get("payout") or 0) >= floor
            and p.get("symbol") not in blocked
            and p.get("symbol") not in cooling
            and p.get("symbol") not in already_streamed
            and (not fx_only or _is_fx_pair(p.get("symbol", "")))
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
        """Subscribe to 1s candle stream, evaluate flips, place until quota filled."""
        # Seed the rolling bar buffer so SuperTrend/MACD/ADX are warm immediately.
        buf: list = []
        try:
            seed = await asyncio.wait_for(
                self._api.get_real_candles(pair, period=1), timeout=12.0
            )
            if seed:
                buf = list(seed)[-200:]
                log.debug("FocusSession: {} seeded {} bars", pair, len(buf))
        except Exception as exc:  # noqa: BLE001
            log.debug("FocusSession: {} seed error (continuing cold): {}", pair, exc)

        try:
            stream = await self._api.create_timed_stream(pair, 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("FocusSession: {} stream setup failed: {} — rotating", pair, exc)
            return

        done = asyncio.Event()
        bars_since_payout_check = 0
        last_bar_ts = None
        total_bars = 0
        session_start = asyncio.get_event_loop().time()
        stream_iter = stream.__aiter__()

        while not done.is_set() and self._running:
            # Per-bar timeout — detect illiquid pairs without waiting the full 300s
            try:
                candle = await asyncio.wait_for(
                    _anext(stream_iter), timeout=_BAR_TIMEOUT,
                )
            except asyncio.TimeoutError:
                elapsed = asyncio.get_event_loop().time() - session_start
                if elapsed > _ILLIQUID_ELAPSED and total_bars < _TICK_CHECK_BARS:
                    log.info(
                        "FocusSession: {} illiquid ({} bars in {:.0f}s) — cooling off {}s",
                        pair, total_bars, elapsed, _ILLIQUID_COOLDOWN,
                    )
                    self._illiquid[pair] = asyncio.get_event_loop().time()
                    return
                continue
            except StopAsyncIteration:
                log.debug("FocusSession: {} stream ended — rotating", pair)
                return

            # Maintain rolling candle buffer (mirrors FlipStreamer pattern)
            ts = candle.get("timestamp") if isinstance(candle, dict) else None
            if ts is not None and ts == last_bar_ts:
                if buf:
                    buf[-1] = candle   # same bar updating intra-second
            else:
                buf.append(candle)
                last_bar_ts = ts
                total_bars += 1
            buf = buf[-200:]

            df = candles_to_df(buf)
            if df.empty or len(df) < _WARMUP_BARS:
                continue

            # ── mid-session payout monitoring ─────────────────────────────────
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
