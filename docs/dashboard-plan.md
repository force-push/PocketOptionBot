# Trading Dashboard — Implementation Plan

Status: **approved design milestone** (Carbon theme locked). This document is the
single source of truth for the build. The two implementation work-packages
(backend + frontend) are built against the **contracts** defined here.

Mockup reference: `mockups/variant-a-carbon.html` (Carbon theme, 3-column landscape
monitoring + separate Settings tab). The production UI ports this look 1:1.

---

## 1. Goals & constraints

- **Monitoring view** (landscape, 3 columns): **Performance ½** (equity/P&L curve +
  win/loss distribution) · **Active Trades ¼** (live countdown cards) · **Trade
  History ¼** (Time · Pair · Result with symbol/colour encoding + hover tooltip).
- **Settings view** in a separate tab — **fully editable**, writes back to `.env`,
  with hard guards around the DEMO/LIVE + SSID safety rules.
- **Live updates** via WebSocket (the user-approved data layer): FastAPI + WS.
- **Must never destabilise trading.** All bot-side hooks are optional and
  fail-closed/no-op — they follow the existing "swallow per-iteration exceptions,
  never crash the bot" rule.
- **Offline-friendly.** A demo seeder lets the whole UI be reviewed with no SSID,
  no Telegram, no network. Core data/aggregation logic is dependency-free so it is
  unit-testable offline (matching the repo's "all tests run offline" ethos).
- **Lean.** Frontend is **no-build vanilla ES modules + modern CSS** (no npm/Vite
  toolchain) so it runs anywhere the bot runs. Backend adds only FastAPI/uvicorn.

### Security (important — the Settings tab can flip LIVE)
- Server binds **`127.0.0.1` by default**. Never bind `0.0.0.0` without a token.
- Optional `DASHBOARD_TOKEN`; when set it is **required** for `POST /api/settings`.
- DEMO→LIVE flip requires explicit `confirm_live: true` **and** server-side SSID
  re-validation; mismatches are rejected (fail-closed), never silently applied.

---

## 2. Architecture

Decoupled, snapshot + event-stream. The bot writes state; the dashboard serves it.

```
 main_v2.py (bot, asyncio)                      dashboard.server (FastAPI/uvicorn)
   manager_v2.run_once()                          ├─ serves dashboard/web/ (static)
        │ calls (optional, no-op safe)            ├─ REST  /api/state|history|performance|settings
        ▼                                         └─ WS    /ws  (broadcasts deltas)
   dashboard.state_bridge.StateBridge                     ▲
        ├─ atomically writes data/live_state.json ────────┤ watchfiles → broadcast
        ├─ appends data/events.jsonl ─────────────────────┤
        └─ (decisions.jsonl already written by manager) ──┘
```

- The dashboard process **watches** `live_state.json`, `decisions.jsonl`,
  `events.jsonl` (via `watchfiles`) and pushes typed deltas over `/ws`.
- **Countdowns** are computed **client-side** from `expiry_at` epochs — no
  per-second server spam.
- Bot and dashboard are **separate processes**; the dashboard is read-mostly. The
  only write path is Settings → `.env` (guarded). Applying most settings needs a
  bot restart; responses flag `requires_restart` and the UI shows a banner.

---

## 3. File layout

```
dashboard/
  __init__.py
  server.py          # FastAPI app + `python -m dashboard.server` entry
  models.py          # pydantic response/event models (shared shapes)
  analytics.py       # DEP-FREE: parse decisions.jsonl → history rows, equity curve,
                     #   win/loss, KPIs. stdlib only → unit-testable offline.
  settings_io.py     # DEP-FREE (pydantic only): read masked settings, validate +
                     #   write .env (python-dotenv set_key), LIVE/SSID guard.
  state_bridge.py    # StateBridge: atomic live_state.json + events.jsonl; no-op safe.
  web/
    index.html
    styles.css       # Carbon tokens + components, extracted from the mockup
    js/
      main.js        # bootstrap + tab routing (hash router)
      api.js         # REST client (token-aware)
      ws.js          # reconnecting WebSocket client
      store.js       # in-memory state + pub/sub
      format.js      # pure formatters (pnl/pct/time) — vitest-free, plain unit fns
      components/
        kpis.js  history.js  active.js  performance.js  settings.js
    sample/          # bundled sample payloads → offline "demo mode" when API absent
tools/
  dashboard_demo.py  # seed data/decisions.jsonl + live_state.json with synthetic data
docs/
  dashboard-plan.md  # this file
tests/
  test_dashboard_analytics.py   # offline, dep-free
  test_dashboard_settings_io.py # offline, dep-free (incl. LIVE guard + masking)
  test_dashboard_api.py         # FastAPI TestClient (runs once fastapi installed)
```

---

## 4. Data contracts

### 4.1 `live_state.json` (written by StateBridge, atomic temp+rename)
```json
{
  "mode": "DEMO", "dry_run": true, "connected": true,
  "balance": 1184.50, "currency": "USD",
  "active": [
    {"trade_id":"abc","pair_raw":"EUR/USD OTC","pair_api":"EURUSD_otc",
     "dir":"CALL","stake":1.50,"entry":1.07432,
     "opened_at":"2026-06-05T14:38:00Z","expiry_at":"2026-06-05T14:38:30Z",
     "expiry_seconds":30,"confluence_n":4,"confluence_score":0.84}
  ],
  "last_cycle":{"cycle_id":"...","status":"trading|skipped|idle","skip_reason":null},
  "risk_block_reason": null,
  "ts":"2026-06-05T14:38:01Z"
}
```

### 4.2 REST
- `GET /api/state` → KPI/active snapshot:
  ```json
  {"mode","dry_run","connected","balance","currency",
   "kpis":{"today_pnl","today_pnl_pct","win_rate","wins","losses","draws",
           "active_count","at_risk","trades_today","traded","skipped","avg_confluence"},
   "active":[...], "ts"}
  ```
- `GET /api/history?limit=100&before=<iso>` → newest-first, paginated. Includes
  SKIPs (`decision:"SKIP"`, `skip_reason`). Row:
  ```json
  {"ts","time","pair_raw","pair_api","otc","dir","decision","result","pnl",
   "stake","expiry_seconds","our_confluence","bot_win_rate","entry","skip_reason",
   "trade_id"}
  ```
  `result` ∈ `win|loss|draw|null` (null while pending / for skips).
- `GET /api/performance?range=1H|1D|1W|ALL` →
  ```json
  {"range","equity":[{"t","cum_pnl"}],"winloss":{"wins","losses","draws"},
   "by_pair":[{"pair","pnl","wins","losses"}]}
  ```
- `GET /api/settings` → grouped, **secrets masked** (`"••••"`), plus per-field
  `requires_restart`. Groups mirror the mockup: Safety/Mode, Telegram,
  PocketOption WS, Signal Gate, Risk.
- `POST /api/settings` → partial update. Body `{fields:{...}, confirm_live?:bool}`.
  Returns `{ok, applied:{...}, errors:{field:msg}, requires_restart:[...]}`.
  - Validates every field through `BotSettings` before writing.
  - Secret fields only updated when a non-mask value is supplied.
  - **LIVE guard:** flipping `TRADE_MODE` to LIVE requires `confirm_live:true` AND
    the configured SSID must parse as live; otherwise `400` with a clear error.

### 4.3 WebSocket `/ws` (server → client JSON)
```
{"type":"hello","data":{"server_time","mode"}}
{"type":"state","data":{ ...same as GET /api/state }}      # sent on connect + on change
{"type":"trade_opened","data":{ ...active trade obj }}
{"type":"trade_resolved","data":{ ...history row incl. result,pnl,balance_after }}
{"type":"history","data":{ ...history row }}               # SKIPs and TRADES
{"type":"settings_changed","data":{"requires_restart":bool,"fields":[...]}}
```
Client → server: `{"type":"ping"}` (heartbeat; server replies `pong`). On connect
the server sends `hello` then a full `state` snapshot, then deltas. Client derives
countdowns locally from `expiry_at`.

---

## 5. Bot integration (`StateBridge`) — minimal, fail-closed

`dashboard/state_bridge.py` exposes a class with no hard deps:
```python
class StateBridge:
    def __init__(self, state_path, events_path, enabled): ...
    def heartbeat(self, *, mode, dry_run, connected, balance, currency, active, last_cycle, risk_block_reason): ...
    def trade_opened(self, active_trade: dict): ...
    def trade_resolved(self, row: dict): ...
    def on_decision(self, row: dict): ...     # SKIP or TRADE row from DecisionRow
```
Every public method wraps its body in `try/except` and logs at debug on failure —
**never raises into the trading loop.** When `enabled` is False every method is a
cheap no-op.

`manager_v2.StrategyManagerV2.__init__` gains an optional `bridge=None` param.
Call sites (all guarded by `if self._bridge:`):
- after `balance_before = await self._api.balance()` → `heartbeat(...)`
- on SKIP write → `on_decision(asdict(row))`
- immediately after `trade = await api_call(...)` and `row.trade_id` set →
  `trade_opened({...expiry_at = now + expiry...})`
- after `backfill_outcome(...)` → `trade_resolved({...result, pnl, balance_after})`

`main_v2._build_components()` constructs the bridge when `settings.dashboard_enabled`
and passes it to the manager. No behavioural change when disabled (default).

---

## 6. New settings (added to `BotSettings` + `.env.example`)
| field | env | default | note |
|---|---|---|---|
| `dashboard_enabled` | `DASHBOARD_ENABLED` | `False` | bot emits state when true |
| `dashboard_host` | `DASHBOARD_HOST` | `127.0.0.1` | bind addr (keep localhost) |
| `dashboard_port` | `DASHBOARD_PORT` | `8787` | server port |
| `dashboard_token` | `DASHBOARD_TOKEN` | `None` | required for settings writes when set |
| `live_state_path` | `LIVE_STATE_PATH` | `data/live_state.json` | snapshot path |
| `events_log_path` | `EVENTS_LOG_PATH` | `data/events.jsonl` | event stream path |

---

## 7. Frontend (port the Carbon mockup, make it live)

- Extract the mockup's CSS tokens/components into `web/styles.css` unchanged in look.
- **Monitoring**: Performance ½ left (equity SVG chart w/ range toggle + crosshair
  tooltip, win/loss bar), Active ¼ (cards with locally-ticking countdown bars,
  flash + auto-remove on resolve), History ¼ (Time·Pair·Result, ▲/▼ + ✓/✗/– colour
  encoding, cursor-following detail tooltip — already prototyped in the mockup).
- **KPI strip**: balance, today P&L (roll/flash on change), win rate, active count,
  trades today, avg confluence — all live.
- **Settings**: form mapped to `/api/settings`; DEMO/LIVE switch shows a confirm
  modal and posts `confirm_live`; masked secret fields only send when edited;
  `requires_restart` shows a banner.
- **Robustness**: reconnecting WS w/ status chip, skeleton + empty states,
  `prefers-reduced-motion`, keyboard tab switching, responsive ≥1280px.
- **Demo mode**: if `/api/state` is unreachable, fall back to `web/sample/*.json`
  so the UI renders standalone for review.

## 8. Run / test
```bash
# deps (user env, has network)
pip3 install -r requirements.txt        # adds fastapi, uvicorn[standard], watchfiles

# seed synthetic data (no SSID/Telegram/network needed)
python3 tools/dashboard_demo.py

# serve dashboard (separate process from the bot)
python3 -m dashboard.server             # http://127.0.0.1:8787

# bot emits live state when enabled
DASHBOARD_ENABLED=true python3 main_v2.py

# tests (offline)
pytest tests/test_dashboard_analytics.py tests/test_dashboard_settings_io.py
pytest tests/test_dashboard_api.py      # needs fastapi installed
```

## 9. Dependencies (added to `requirements.txt`)
`fastapi>=0.110`, `uvicorn[standard]>=0.29`, `watchfiles>=0.21`
(`python-dotenv` already present). No frontend build deps.

## 10. Work packages (farmed out)
- **WP-A Backend**: `dashboard/{server,models,analytics,settings_io,state_bridge}.py`,
  manager_v2/main_v2 hooks, settings additions, `tools/dashboard_demo.py`,
  requirements, the three test modules.
- **WP-B Frontend**: `dashboard/web/**` — ported Carbon UI wired to §4 contracts,
  with demo-mode fallback.

File scopes are disjoint so the packages integrate cleanly.
