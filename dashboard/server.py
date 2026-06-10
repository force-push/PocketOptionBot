"""FastAPI dashboard server (docs §4.2/§4.3).

Run with::

    python3 -m dashboard.server          # http://127.0.0.1:8787

Serves ``dashboard/web/`` as static files at ``/`` (guarded — the dir may not
exist yet; a placeholder is served instead). REST endpoints read the bot's
output files through the dependency-free ``analytics``/``settings_io`` modules.
A ``watchfiles`` watcher tails ``live_state.json``/``decisions.jsonl``/
``events.jsonl`` and broadcasts typed deltas over ``/ws``.

Token auth: when ``settings.dashboard_token`` is set it is required for
``POST /api/settings`` (header ``X-Dashboard-Token`` or ``?token=``).
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from dashboard import analytics, settings_io
from dashboard.models import (
    PerformanceResponse,
    SettingsUpdateRequest,
    SettingsUpdateResponse,
    StateResponse,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WEB_DIR = Path(__file__).resolve().parent / "web"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── live_state.json helper ───────────────────────────────────────────────────

def _read_live_state() -> dict:
    p = Path(settings.live_state_path)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {}


def _decisions_path() -> Path:
    p = Path(settings.decisions_log_path)
    return p if p.is_absolute() else _PROJECT_ROOT / p


def _events_path() -> Path:
    p = Path(settings.events_log_path)
    return p if p.is_absolute() else _PROJECT_ROOT / p


def _live_state_path() -> Path:
    p = Path(settings.live_state_path)
    return p if p.is_absolute() else _PROJECT_ROOT / p


# ── snapshot builders (shared by REST + WS) ──────────────────────────────────

def build_state_snapshot() -> dict:
    state = _read_live_state()
    records = analytics.load_records(_decisions_path())
    balance = state.get("balance")
    active = state.get("active", [])
    kpis = analytics.kpis(records, balance=balance, active=active)
    return {
        "mode": state.get("mode", settings.trade_mode.value),
        "dry_run": state.get("dry_run", settings.dry_run),
        "connected": state.get("connected", False),
        "balance": balance,
        "currency": state.get("currency", "USD"),
        "kpis": kpis,
        "active": active,
        "skip_countdown": state.get("skip_countdown"),
        "ts": state.get("ts") or _now_iso(),
    }


# ── WebSocket broadcaster ────────────────────────────────────────────────────

class Broadcaster:
    """Tracks connected WS clients and fans out JSON frames."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def register(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception:
                await self.unregister(ws)


def create_app() -> FastAPI:
    broadcaster = Broadcaster()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: start the file watcher
        app.state._watch_task = asyncio.create_task(_watch_loop(app, broadcaster))
        yield
        # Shutdown: cancel the watcher task
        task = getattr(app.state, "_watch_task", None)
        if task:
            task.cancel()

    app = FastAPI(
        title="PocketOption Bot Dashboard",
        version="2.0",
        lifespan=lifespan,
    )
    app.state.broadcaster = broadcaster

    # ── auth helper ──────────────────────────────────────────────────────────
    def _require_token(request: Request, token: Optional[str]) -> None:
        configured = settings.dashboard_token
        if not configured:
            return  # auth disabled
        # Accept any of: X-Dashboard-Token header, Authorization: Bearer <tok>
        # (what the web client sends), or a ?token= query param.
        supplied = request.headers.get("X-Dashboard-Token")
        if not supplied:
            auth = request.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()
        if not supplied:
            supplied = token
        if supplied != configured:
            raise HTTPException(status_code=401, detail="invalid or missing dashboard token")

    # ── REST ──────────────────────────────────────────────────────────────────
    @app.get("/api/state", response_model=StateResponse)
    def get_state() -> Any:
        return build_state_snapshot()

    @app.get("/api/history")
    def get_history(limit: int = Query(100, ge=0, le=2000),
                    before: Optional[str] = Query(None)) -> Any:
        records = analytics.load_records(_decisions_path())
        rows = analytics.history(records, limit=limit, before=before)
        next_before = rows[-1]["ts"] if rows and len(rows) >= limit and limit > 0 else None
        return {"rows": rows, "next_before": next_before}

    @app.get("/api/trade/{trade_id}")
    def get_trade_detail(trade_id: str) -> Any:
        records = analytics.load_records(_decisions_path())
        # Look up by trade_id first (unique per trade); fall back to cycle_id for
        # legacy rows and SKIPs that have no trade_id.
        rec = analytics.find_by_trade_id(records, trade_id)
        if rec is None:
            rec = analytics.find_by_cycle_id(records, trade_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="trade not found")
        return analytics.full_detail_row(rec)

    @app.get("/api/performance", response_model=PerformanceResponse)
    def get_performance(range: str = Query("ALL")) -> Any:
        records = analytics.load_records(_decisions_path())
        return analytics.performance(records, rng=range)

    @app.get("/api/settings")
    def get_settings() -> Any:
        return settings_io.read_settings(settings)

    @app.post("/api/settings", response_model=SettingsUpdateResponse)
    async def post_settings(
        body: SettingsUpdateRequest,
        request: Request,
        token: Optional[str] = Query(None),
    ) -> Any:
        _require_token(request, token)
        env_path = _PROJECT_ROOT / ".env"
        result = settings_io.apply_update(
            body.fields,
            settings_obj=settings,
            env_path=env_path,
            confirm_live=body.confirm_live,
        )
        if not result.get("ok"):
            return JSONResponse(status_code=400, content={
                "ok": False,
                "applied": result.get("applied", {}),
                "errors": result.get("errors", {}),
                "requires_restart": result.get("requires_restart", []),
            })
        # notify connected clients
        await broadcaster.broadcast({
            "type": "settings_changed",
            "data": {
                "requires_restart": bool(result.get("requires_restart")),
                "fields": list(result.get("applied", {}).keys()),
            },
        })
        return {
            "ok": True,
            "applied": result.get("applied", {}),
            "errors": {},
            "requires_restart": result.get("requires_restart", []),
        }

    # ── WebSocket ─────────────────────────────────────────────────────────────
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # optional token check for WS too (query param only)
        configured = settings.dashboard_token
        if configured:
            supplied = ws.query_params.get("token") or ws.headers.get("X-Dashboard-Token")
            if supplied != configured:
                await ws.close(code=1008)
                return
        await ws.accept()
        await broadcaster.register(ws)
        try:
            await ws.send_json({"type": "hello", "data": {
                "server_time": _now_iso(), "mode": settings.trade_mode.value,
            }})
            await ws.send_json({"type": "state", "data": build_state_snapshot()})
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await ws.send_json({"type": "pong", "data": {"server_time": _now_iso()}})
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            await broadcaster.unregister(ws)

    # ── static files ──────────────────────────────────────────────────────────
    _mount_web(app)

    return app


async def _watch_loop(app: FastAPI, broadcaster: Broadcaster) -> None:
    """Watch the three data files; push deltas on change.

    - live_state.json change → fresh ``state`` snapshot.
    - events.jsonl append    → forward each new event frame verbatim
      (``trade_opened`` / ``trade_resolved`` / ``history``).
    - decisions.jsonl change → fresh ``state`` snapshot (KPIs/history derive from it).
    """
    try:
        from watchfiles import awatch
    except Exception:
        return  # watchfiles unavailable — server still serves static REST

    live = _live_state_path()
    decisions = _decisions_path()
    events = _events_path()
    for p in (live, decisions, events):
        p.parent.mkdir(parents=True, exist_ok=True)

    events_offset = events.stat().st_size if events.exists() else 0

    watch_dirs = {str(p.parent) for p in (live, decisions, events)}
    try:
        async for changes in awatch(*watch_dirs):
            changed = {Path(path) for _ct, path in changes}
            if live in changed or decisions in changed:
                try:
                    await broadcaster.broadcast({"type": "state", "data": build_state_snapshot()})
                except Exception:
                    pass
            if events in changed:
                events_offset = await _drain_events(events, events_offset, broadcaster)
    except asyncio.CancelledError:
        raise
    except Exception:
        return


async def _drain_events(events: Path, offset: int, broadcaster: Broadcaster) -> int:
    """Emit any event lines appended past ``offset``; return the new offset."""
    try:
        size = events.stat().st_size
        if size < offset:  # file truncated/rotated
            offset = 0
        if size == offset:
            return offset
        with events.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            chunk = fh.read()
            new_offset = fh.tell()
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(evt, dict) and "type" in evt:
                etype = evt["type"]
                data = evt.get("data", {})
                # Normalise row-bearing events through the same projection REST
                # uses, so live-appended rows match GET /api/history exactly
                # (raw DecisionRow uses our_direction/our_confluence_score/etc).
                if etype in ("history", "trade_resolved") and isinstance(data, dict):
                    norm = analytics.history_row(data)
                    if etype == "trade_resolved":
                        # preserve resolution extras the UI needs (balance chip,
                        # active-card flash) that history_row doesn't carry
                        if "balance_after" in data:
                            norm["balance_after"] = data.get("balance_after")
                        if data.get("trade_id") is not None:
                            norm["trade_id"] = data.get("trade_id")
                    data = norm
                await broadcaster.broadcast({"type": etype, "data": data})
        return new_offset
    except Exception:
        return offset


_PLACEHOLDER_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>PocketOption Bot Dashboard</title>
<style>body{font-family:system-ui;background:#0a0e14;color:#e6edf3;margin:0;
display:grid;place-items:center;height:100vh}main{max-width:520px;padding:24px}
code{color:#2dd4bf}</style></head><body><main>
<h1>PocketOption Bot Dashboard</h1>
<p>The frontend (<code>dashboard/web/</code>) is not built yet, but the API is live.</p>
<ul>
<li><code>GET /api/state</code></li>
<li><code>GET /api/history</code></li>
<li><code>GET /api/performance</code></li>
<li><code>GET /api/settings</code></li>
<li><code>WS  /ws</code></li>
</ul></main></body></html>"""


def _mount_web(app: FastAPI) -> None:
    """Mount dashboard/web at / if it exists; else serve a placeholder."""
    index = _WEB_DIR / "index.html"
    if _WEB_DIR.is_dir() and index.exists():
        app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
    else:
        @app.get("/", response_class=HTMLResponse)
        def _placeholder() -> str:  # pragma: no cover - trivial
            return _PLACEHOLDER_HTML


# module-level app for `uvicorn dashboard.server:app`
app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
