"""PocketOption WebSocket API client wrapping binaryoptionstoolsv2.

This is the CRITICAL SAFETY FUNCTION — it enforces the demo guard and
DRY_RUN gate before any real trade is placed.

Imports the underlying library lazily so this module can be imported (and
tested) even without the Rust-backed wheel installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from config.settings import settings, TradeMode
from utils.logger import log, log_trade

# Lazy import guard — the Rust wheel may not be available in all environments
try:
    from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync  # type: ignore[import]
    _API_AVAILABLE = True
except ImportError:
    _API_AVAILABLE = False
    PocketOptionAsync = None  # type: ignore[assignment,misc]


# ──────────────────────────────────────────────────────────────────────────────
# Result dataclass (mirrors TradeResult from broker/executor.py)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class TradeResult:
    """Result of a buy/sell attempt."""

    id: str
    direction: str          # "CALL" or "PUT"
    pair: str
    amount: float
    expiry: int             # seconds
    timestamp: datetime
    status: str             # "PENDING" | "WIN" | "LOSS" | "ERROR" | "DRY_RUN"
    error: str = ""
    trade_id: Optional[str] = None  # raw trade_id from the API


# ──────────────────────────────────────────────────────────────────────────────
# SSID helper
# ──────────────────────────────────────────────────────────────────────────────


def _parse_ssid_is_demo(ssid: str) -> Optional[bool]:
    """Decode the isDemo flag from an SSID string.

    The SSID looks like: 42["auth",{"session":"...","isDemo":1,...}]

    Returns True if isDemo is truthy, False if falsy, None if unparseable.
    """
    if not ssid:
        return None
    try:
        # Extract the JSON object part from the message
        m = re.search(r'\[.*?,\s*(\{.*\})\s*\]', ssid, re.DOTALL)
        if not m:
            return None
        obj = json.loads(m.group(1))
        is_demo = obj.get("isDemo")
        if is_demo is None:
            return None
        return bool(is_demo)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# API client
# ──────────────────────────────────────────────────────────────────────────────


class PocketOptionAPIClient:
    """Wraps PocketOptionAsync with demo guard and DRY_RUN support.

    Constructor args:
        ssid:     Full auth string (overrides settings.po_ssid if given).
        dry_run:  Override DRY_RUN; defaults to settings.dry_run.

    Safety:
        - Before any real buy/sell, checks SSID isDemo vs TRADE_MODE.
          If they disagree the trade is ABORTED (fail-closed).
        - If dry_run is True, logs the trade and returns without calling API.
    """

    _counter = 0

    def __init__(
        self,
        ssid: Optional[str] = None,
        dry_run: Optional[bool] = None,
    ) -> None:
        self._ssid = ssid if ssid is not None else settings.po_ssid
        self._dry_run = dry_run if dry_run is not None else settings.dry_run
        self._client: Optional[Any] = None

    # ── connection ───────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Instantiate and connect the underlying API client."""
        if not _API_AVAILABLE:
            raise RuntimeError(
                "binaryoptionstoolsv2 is not installed. "
                "Install it with: pip install binaryoptionstoolsv2"
            )
        if not self._ssid:
            raise RuntimeError(
                "PO_SSID must be set in .env before connecting to the API."
            )
        self._client = PocketOptionAsync(self._ssid)
        # wait_for_assets() blocks until the WebSocket handshake is complete and
        # the server has sent the asset list. Without this, get_candles() hangs
        # indefinitely because the Rust backend waits for initialization internally.
        log.info("Waiting for PocketOption WebSocket assets (up to 60s)…")
        await self._client.wait_for_assets(timeout=60.0)
        # Validate SSID using API-native methods immediately after construction
        try:
            if not self._client.is_ssid_valid():
                raise RuntimeError(
                    "PocketOption API reports SSID is invalid or expired. "
                    "Refresh PO_SSID in .env and restart."
                )
            demo_flag = self._client.is_demo()
            log.info(
                "PocketOptionAPIClient connected — is_demo={} dry_run={}",
                demo_flag, self._dry_run,
            )
        except AttributeError:
            # Library version does not expose these methods — fall back to SSID parsing
            log.info("PocketOptionAPIClient connected (dry_run={})", self._dry_run)

    # ── demo guard ───────────────────────────────────────────────────────────

    def _resolve_is_demo(self) -> Optional[bool]:
        """Determine whether the active session is a demo account.

        Priority:
        1. API-native ``is_ssid_valid()`` + ``is_demo()`` — authoritative when
           the client is connected and the library exposes these sync methods.
        2. SSID string decode (``_parse_ssid_is_demo``) — fallback for
           pre-connection guard checks, when methods are absent, or when the
           client is a test mock (AsyncMock returns coroutines, not bools).
        """
        import inspect

        if self._client is not None:
            try:
                valid = self._client.is_ssid_valid()
                # Guard against AsyncMock returning a coroutine instead of bool
                if inspect.iscoroutine(valid):
                    valid.close()  # prevent ResourceWarning
                    raise AttributeError("is_ssid_valid appears to be async")
                if not valid:
                    log.warning("is_ssid_valid() returned False — SSID may be expired")
                    return None  # treat invalid SSID as indeterminate → fail closed
                demo = self._client.is_demo()
                if inspect.iscoroutine(demo):
                    demo.close()
                    raise AttributeError("is_demo appears to be async")
                return bool(demo)
            except Exception as exc:
                log.debug("API-native is_demo() unavailable ({}); using SSID fallback", exc)
        # Fallback: decode from the raw SSID string
        return _parse_ssid_is_demo(self._ssid)

    def _check_demo_guard(self, direction: str, pair: str, amount: float, expiry: int) -> Optional[TradeResult]:
        """Enforce demo/live mode consistency.

        Returns an ERROR TradeResult if the guard fires, otherwise None.
        This is fail-closed: any ambiguity defaults to ABORT.
        """
        PocketOptionAPIClient._counter += 1
        trade_id_prefix = f"guard_{PocketOptionAPIClient._counter}"

        ssid_is_demo = self._resolve_is_demo()

        if settings.trade_mode == TradeMode.DEMO:
            # If we cannot determine the SSID mode, fail closed
            if ssid_is_demo is False:
                msg = (
                    "ABORT: TRADE_MODE=DEMO but SSID has isDemo=0 (live account). "
                    "Set TRADE_MODE=LIVE in .env if you intend live trading, "
                    "or use a demo SSID."
                )
                log.critical(msg)
                return TradeResult(
                    id=trade_id_prefix,
                    direction=direction,
                    pair=pair,
                    amount=amount,
                    expiry=expiry,
                    timestamp=datetime.now(),
                    status="ERROR",
                    error=msg,
                )
            if ssid_is_demo is None:
                # Cannot parse — fail closed
                msg = (
                    "ABORT: TRADE_MODE=DEMO but could not decode isDemo from SSID. "
                    "Refusing to place trade for safety."
                )
                log.critical(msg)
                return TradeResult(
                    id=trade_id_prefix,
                    direction=direction,
                    pair=pair,
                    amount=amount,
                    expiry=expiry,
                    timestamp=datetime.now(),
                    status="ERROR",
                    error=msg,
                )

        elif settings.trade_mode == TradeMode.LIVE:
            if ssid_is_demo is True:
                # Allow but warn — user may be intentionally paper-trading
                log.warning(
                    "WARNING: TRADE_MODE=LIVE but SSID has isDemo=1 (demo account)."
                )
            else:
                log.critical(
                    "LIVE TRADING ACTIVE — direction=%s pair=%s amount=%.2f",
                    direction, pair, amount,
                )

        return None  # guard passed

    # ── trade methods ────────────────────────────────────────────────────────

    async def _place(
        self,
        direction: str,
        pair: str,
        amount: float,
        expiry: int,
    ) -> TradeResult:
        """Internal: apply guards then call buy/sell on the underlying API."""
        PocketOptionAPIClient._counter += 1
        ctr = PocketOptionAPIClient._counter

        # Demo guard
        guard_result = self._check_demo_guard(direction, pair, amount, expiry)
        if guard_result is not None:
            return guard_result

        # DRY RUN
        if self._dry_run:
            result = TradeResult(
                id=f"dry_run_{ctr}",
                direction=direction,
                pair=pair,
                amount=amount,
                expiry=expiry,
                timestamp=datetime.now(),
                status="DRY_RUN",
                trade_id=None,
            )
            log.info(
                "[DRY RUN] Would place %s on %s: amount=%.2f expiry=%ds",
                direction, pair, amount, expiry,
            )
            log_trade({
                "id": result.id,
                "direction": direction,
                "pair": pair,
                "amount": amount,
                "expiry": expiry,
                "timestamp": result.timestamp,
                "status": "DRY_RUN",
            })
            return result

        # Real trade
        if self._client is None:
            raise RuntimeError(
                "API client not connected. Call await client.connect() first."
            )

        try:
            api_method = self._client.buy if direction == "CALL" else self._client.sell
            trade_id, _deal = await api_method(pair, amount, expiry)
            result = TradeResult(
                id=f"trade_{ctr}",
                direction=direction,
                pair=pair,
                amount=amount,
                expiry=expiry,
                timestamp=datetime.now(),
                status="PENDING",
                trade_id=str(trade_id),
            )
            log.info(
                "Trade placed: %s %s amount=%.2f expiry=%ds trade_id=%s",
                direction, pair, amount, expiry, trade_id,
            )
            log_trade({
                "id": result.id,
                "direction": direction,
                "pair": pair,
                "amount": amount,
                "expiry": expiry,
                "timestamp": result.timestamp,
                "status": "PENDING",
                "trade_id": str(trade_id),
            })
            return result
        except Exception as exc:
            msg = f"API call failed: {exc}"
            log.error(msg)
            return TradeResult(
                id=f"failed_{ctr}",
                direction=direction,
                pair=pair,
                amount=amount,
                expiry=expiry,
                timestamp=datetime.now(),
                status="ERROR",
                error=msg,
            )

    async def buy(self, pair: str, amount: float, expiry: int) -> TradeResult:
        """Place a CALL trade."""
        return await self._place("CALL", pair, amount, expiry)

    async def sell(self, pair: str, amount: float, expiry: int) -> TradeResult:
        """Place a PUT trade."""
        return await self._place("PUT", pair, amount, expiry)

    # ── outcome / data ───────────────────────────────────────────────────────

    async def check_win(self, trade_id: str) -> str:
        """Wait for trade resolution and return 'win', 'loss', or 'draw'.

        Blocks until the trade expires.
        """
        if self._client is None:
            raise RuntimeError("API client not connected.")
        result = await self._client.check_win(trade_id)
        # The library returns a dict with trade details; extract the 'result' field
        if isinstance(result, dict):
            result_str = result.get("result", str(result)).lower()
        else:
            result_str = str(result).lower()
        # Normalize to 'win'/'loss'/'draw'
        if "loss" in result_str or "lose" in result_str:
            return "loss"
        elif "win" in result_str:
            return "win"
        elif "draw" in result_str or "tie" in result_str:
            return "draw"
        else:
            return result_str

    async def balance(self) -> Optional[float]:
        """Return the current account balance, or None on error."""
        if self._client is None:
            return None
        try:
            return float(await self._client.balance())
        except Exception as exc:
            log.error("balance() failed: {}", exc)
            return None

    async def get_candles(
        self,
        pair: str,
        period: int = 60,
        count: int = 100,
    ) -> list[dict]:
        """Fetch OHLCV candles as a list of dicts.

        Args:
            pair:   Asset symbol, e.g. "EURUSD_otc".
            period: Candle timeframe in seconds (1, 5, 15, 30, 60, 300).
            count:  Number of candles to fetch. Converted to ``offset`` (seconds
                    of history = count * period) for the library call.

        Returns list of candle dicts as returned by the library.
        Empty list on error.
        """
        if self._client is None:
            raise RuntimeError("API client not connected.")
        # The library's get_candles(asset, period, offset) takes 'offset' as
        # the historical window in seconds, not a candle count.
        offset_seconds = count * period
        try:
            candles = await self._client.get_candles(pair, period, offset_seconds)
            return list(candles)
        except Exception as exc:
            log.error("get_candles({}) failed: {}", pair, exc)
            return []
