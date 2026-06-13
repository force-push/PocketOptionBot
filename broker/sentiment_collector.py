"""Sentiment collector — live crowd-positioning stream from PocketOption WS.

Attaches a raw message handler to the shared API connection and caches the
latest per-pair sentiment integer (0-100) as it arrives.  The value matches
the platform's "traders' choice" widget: 60 means 60% of traders are buying.

Usage (inside the bot loop):
    collector = SentimentCollector()
    await collector.attach(api_client)           # once, after connect()
    await collector.subscribe_pair(api_client, "EURUSD_otc")  # before each scan
    sentiment = collector.get("EURUSD_otc")      # None until first message
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from utils.logger import log

# Matches  42["<SYMBOL>",<int>]  or  [["<SYMBOL>",<int>]]
_SENTIMENT_RE = re.compile(
    r'\[\s*\[\s*"([^"]+)"\s*,\s*(\d+)\s*\]\s*\]'
    r'|42\[\s*"([^"]+)"\s*,\s*(\d+)\s*\]'
)

_LOG_PATH = Path("data/sentiment.jsonl")


class SentimentCollector:
    """Subscribe to PO's trader-sentiment stream; cache + log every reading."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, int]] = {}  # pair → (epoch_ts, value)
        self._handler: Any = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._captured = 0                 # total sentiment frames matched (for logging)

    # ── public API ───────────────────────────────────────────────────────────

    async def attach(self, api_client: Any) -> None:
        """Create a raw WS handler on the connected client and start listening.

        Safe to call multiple times — stops the previous task first.
        """
        await self.stop()
        self._handler = await api_client.create_raw_handler()
        self._running = True
        self._task = asyncio.create_task(self._listen_loop(), name="sentiment-listener")
        log.info("SentimentCollector attached — listener task started")

    async def subscribe_pair(self, api_client: Any, pair: str, period: int = 1) -> None:
        """Explicitly send changeSymbol so the server starts pushing sentiment for *pair*.

        Called by the scan loop right before each pair's candle fetch — the fetch
        + signal processing already holds this symbol for ~4-5s (≈ the push
        latency), so the traders'-choice push lands in cache during that window
        ("harvest during the pair's own fetch"). A separate dweller was tried and
        was worse — it shared the single WS session and got clobbered by the scan's
        own symbol switches. See memory: debug_sentiment_out_of_band.
        ``period=1`` matches tools/po_sentiment_probe.py, the proven-working probe.
        """
        try:
            msg = f'42["changeSymbol",{{"asset":"{pair}","period":{period}}}]'
            await api_client.send_raw_message(msg)
        except Exception as exc:
            log.debug("SentimentCollector.subscribe_pair({}): {}", pair, exc)

    def get(self, pair: str) -> int | None:
        """Return the latest cached sentiment for *pair*, or None if not seen yet.

        Values older than 120 s are discarded (stale between scans).
        """
        entry = self._cache.get(pair)
        if entry is None:
            return None
        ts, val = entry
        if time.time() - ts > 120:
            return None
        return val

    def cache_snapshot(self) -> dict[str, int]:
        """Return a copy of the current (non-stale) cache."""
        now = time.time()
        return {p: v for p, (ts, v) in self._cache.items() if now - ts <= 120}

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    # ── internal ─────────────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """Background task: drain handler messages; update cache + log file."""
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        consecutive_errors = 0
        total_frames = 0

        while self._running:
            try:
                raw = await asyncio.wait_for(self._handler.wait_next(), timeout=10.0)
                consecutive_errors = 0
                total_frames += 1
                # Log first 10 frames at INFO to confirm the actual message format.
                if total_frames <= 10:
                    log.info(
                        "SentimentCollector frame #{}: type={} repr={}",
                        total_frames, type(raw).__name__, repr(raw)[:200],
                    )
                if total_frames % 200 == 1:
                    log.info(
                        "SentimentCollector: {} raw frames seen, {} sentiment matched",
                        total_frames, self._captured,
                    )
                self._process_any(raw)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                consecutive_errors += 1
                log.debug("SentimentCollector listener error ({}): {}", consecutive_errors, exc)
                if consecutive_errors >= 10:
                    log.warning("SentimentCollector: 10 consecutive errors — pausing 30s")
                    await asyncio.sleep(30)
                    consecutive_errors = 0
                else:
                    await asyncio.sleep(1)

    def _process_any(self, raw: Any) -> None:
        """Dispatch raw WS frames from either Python-object or string form.

        PO's raw handler returns Python list objects, not raw JSON strings.
        Sentiment frames arrive as [["SYMBOL", int]] — a list containing one
        2-element list.  Tick frames are [["SYMBOL", float_ts, float_price]]
        (3 elements) and are skipped by the len==2 check.  String fallback
        handles any message the library does return as a raw string.
        """
        if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list):
            inner = raw[0]
            if len(inner) == 2 and isinstance(inner[0], str) and isinstance(inner[1], (int, float)):
                val_f = float(inner[1])
                ival = int(val_f)
                if val_f == ival and 0 <= ival <= 100:
                    self._store(inner[0], ival)
                    return
        # Fallback: regex on string representation (handles plain-string frames)
        self._process(str(raw))

    def _store(self, pair: str, val: int) -> None:
        """Update the cache with a confirmed sentiment value and log it."""
        ts = time.time()
        old = self._cache.get(pair)
        self._cache[pair] = (ts, val)
        self._captured += 1
        if self._captured % 50 == 1:
            log.info(
                "SentimentCollector: {} frames captured, {} pairs warm in cache",
                self._captured, len(self.cache_snapshot()),
            )
        # Only log when the value changes (suppress chatty identical repeats)
        if old is None or old[1] != val:
            try:
                with _LOG_PATH.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"ts": ts, "pair": pair, "sentiment": val}) + "\n")
            except Exception as exc:
                log.debug("SentimentCollector log write failed: {}", exc)
            log.debug("sentiment  {}  →  {}", pair, val)

    def _process(self, raw: str) -> None:
        """Parse a raw string WS message and update cache if it matches the sentiment pattern."""
        m = _SENTIMENT_RE.search(raw)
        if not m:
            return
        # Two capture groups: bracketed form vs 42-prefixed form
        if m.group(1) is not None:
            pair, val = m.group(1), int(m.group(2))
        else:
            pair, val = m.group(3), int(m.group(4))
        if not (0 <= val <= 100):
            return
        self._store(pair, val)
