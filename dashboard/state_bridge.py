"""StateBridge — the bot's fail-closed bridge to the dashboard.

The trading loop calls these methods to emit live state. EVERY public method is
wrapped in try/except that logs at debug and NEVER raises into the trading loop
(see docs/dashboard-plan.md §5 and CLAUDE.md "swallow per-iteration exceptions").
When ``enabled`` is False every method is a cheap no-op.

Writes:
- ``live_state.json`` — atomic (temp file + os.replace) snapshot.
- ``events.jsonl``    — append-only typed event stream for the WS broadcaster.

Dependency-free: stdlib only (json, os, tempfile, datetime, pathlib). Logging
uses loguru if available, else the stdlib logging module — failure to import a
logger must never break the bridge.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:  # pragma: no cover - loguru is the project default
    from loguru import logger as _log
except Exception:  # pragma: no cover - fallback so the bridge never hard-fails
    import logging

    _log = logging.getLogger("dashboard.state_bridge")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# events.jsonl is an append-only dashboard feed; the dashboard only ever reads
# lines appended after it started (byte-offset tail). Left unbounded it grew to
# 200MB+. Cap it: when it exceeds the size limit, keep only the last N lines.
# The dashboard's drain handles truncation (size < offset → resets to 0).
_EVENTS_MAX_BYTES = 10 * 1024 * 1024   # 10 MB
_EVENTS_KEEP_LINES = 5000
_EVENTS_CHECK_EVERY = 200              # check size every N appends (cheap)


class StateBridge:
    """Writes live_state.json + events.jsonl for the dashboard.

    Parameters
    ----------
    state_path:  path to live_state.json
    events_path: path to events.jsonl
    enabled:     when False, all methods are no-ops (the default for the bot).
    """

    def __init__(
        self,
        state_path: str | Path = "data/live_state.json",
        events_path: str | Path = "data/events.jsonl",
        enabled: bool = False,
    ) -> None:
        self.enabled = bool(enabled)
        self._state_path = Path(state_path)
        self._events_path = Path(events_path)
        self._append_count = 0

    # ── public API (all fail-closed) ─────────────────────────────────────────

    def heartbeat(
        self,
        *,
        mode: str,
        dry_run: bool,
        connected: bool,
        balance: Optional[float],
        currency: str,
        active: Optional[list] = None,
        last_cycle: Optional[dict] = None,
        risk_block_reason: Optional[str] = None,
        skip_countdown: Optional[dict] = None,
    ) -> None:
        """Atomically rewrite live_state.json with the current snapshot."""
        if not self.enabled:
            return
        try:
            snapshot = {
                "mode": mode,
                "dry_run": bool(dry_run),
                "connected": bool(connected),
                "balance": balance,
                "currency": currency,
                "active": list(active or []),
                "last_cycle": last_cycle,
                "risk_block_reason": risk_block_reason,
                "skip_countdown": skip_countdown,
                "ts": _now_iso(),
            }
            self._atomic_write_json(self._state_path, snapshot)
        except Exception as exc:  # never raise into the trading loop
            self._debug("heartbeat failed: {}", exc)

    def trade_opened(self, active_trade: dict) -> None:
        """Append a ``trade_opened`` event for a freshly placed trade."""
        if not self.enabled:
            return
        try:
            self._append_event("trade_opened", dict(active_trade))
        except Exception as exc:
            self._debug("trade_opened failed: {}", exc)

    def trade_resolved(self, row: dict) -> None:
        """Append a ``trade_resolved`` event (result, pnl, balance_after)."""
        if not self.enabled:
            return
        try:
            self._append_event("trade_resolved", dict(row))
        except Exception as exc:
            self._debug("trade_resolved failed: {}", exc)

    def on_decision(self, row: dict) -> None:
        """Append a ``history`` event for a SKIP or TRADE decision row."""
        if not self.enabled:
            return
        try:
            self._append_event("history", dict(row))
        except Exception as exc:
            self._debug("on_decision failed: {}", exc)

    # ── internals ────────────────────────────────────────────────────────────

    def _append_event(self, type_: str, data: dict) -> None:
        event = {"type": type_, "data": data, "ts": _now_iso()}
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        with self._events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")
        self._append_count += 1
        if self._append_count % _EVENTS_CHECK_EVERY == 0:
            self._cap_events_file()

    def _cap_events_file(self) -> None:
        """Truncate events.jsonl to the last _EVENTS_KEEP_LINES when over the cap.

        Append-only growth is unbounded otherwise. The dashboard reads only the
        post-startup tail and handles truncation (resets its offset), so dropping
        old lines is safe. Fail-soft: any error leaves the file untouched.
        """
        try:
            if self._events_path.stat().st_size <= _EVENTS_MAX_BYTES:
                return
            with self._events_path.open("r", encoding="utf-8") as fh:
                tail = fh.readlines()[-_EVENTS_KEEP_LINES:]
            tmp = self._events_path.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                fh.writelines(tail)
            tmp.replace(self._events_path)
        except Exception as exc:  # never raise into the trading loop
            self._debug("events cap failed: {}", exc)

    @staticmethod
    def _atomic_write_json(path: Path, obj: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(obj, default=str, ensure_ascii=False, indent=2)
        # temp file in the same dir so os.replace is atomic (same filesystem)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".live_state.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)  # atomic on POSIX & Windows
        except Exception:
            # best-effort cleanup; swallow so callers' try/except can log once
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            raise

    def _debug(self, msg: str, *args) -> None:
        try:
            # loguru uses {} formatting; stdlib logging uses %s — normalise.
            if hasattr(_log, "opt"):
                _log.debug(msg, *args)
            else:  # stdlib logging
                _log.debug(msg.replace("{}", "%s"), *args)
        except Exception:
            pass


__all__ = ["StateBridge"]
