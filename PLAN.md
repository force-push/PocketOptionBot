# PLAN — Telegram-sourced, win-rate-filtered PocketOption bot

Status: approved design. Implementation follows the phases at the bottom.

## The core shift

Today the bot is **time-driven**: a DOM price scraper feeds candles, and every
`candle_interval` the strategy scores TA and maybe clicks a CALL/PUT button via
CDP. The new design is **event-driven**: a signal from the Telegram bot
`po_broker_bot` arrives, is filtered through three quality gates, and — if it
passes — is placed via the unofficial PocketOption WebSocket API, whose
`check_win` result feeds back into the win-rate tracker and the risk manager.

Side effect: today the executor only ever records `PENDING` (DOM clicking can't
observe outcomes), so the RiskManager cooldown / daily-loss limits never fire.
With `check_win` returning real `win`/`loss`, **those safety limits become
functional for the first time**, and the win-rate tracker becomes possible.

## Decisions (locked)

- **Execution:** unofficial PocketOption WS API via `binaryoptionstoolsv2`
  (`PocketOptionAsync`), authenticated with an **SSID** session string.
- **Signal gating ("find high win rate trades"):** all three of —
  1. channel's **stated win%** ≥ threshold,
  2. our **tracked real win rate** for the pair ≥ threshold (once enough samples),
  3. **TA confluence** (existing engine) agrees with the signal direction.
- **Telegram read:** **Telethon user session** (MTProto), the only way to read a
  bot's DMs to you.

## Target flow

```
Telethon user session  ── listens to po_broker_bot DMs
        │
        ▼
  parse_signal(text) ─────────────► TelegramSignal(pair, direction, expiry, stated_win%, ts)
        │
        ▼  SignalGate (all must pass)
   ┌─────────────────────────────────────────────────────────┐
   │ 1. stated_win% ≥ MIN_CHANNEL_WIN_RATE                    │
   │ 2. WinRateTracker[pair].rate ≥ MIN_TRACKED_WIN_RATE      │
   │    (only enforced once n ≥ MIN_TRACKED_SAMPLES)          │
   │ 3. TA: api.get_candles(pair) → ConfluenceEngine.score()  │
   │       direction agrees with the signal                   │
   └─────────────────────────────────────────────────────────┘
        │ pass
        ▼
   RiskManager.is_allowed(balance)  (min balance, trades/hr, daily loss, cooldown)
        │ allowed
        ▼
   PocketOptionAPIClient.buy/sell(pair, amount, expiry)  ──► trade_id
        │   (DRY_RUN short-circuits here; demo/live guard before any real buy)
        ▼  (per-trade asyncio task)
   await check_win(trade_id) ──► 'win'|'loss'|'draw'
        ▼
   WinRateTracker.record(pair, outcome)  +  RiskManager.record_trade(...)
```

TA candle data now comes from `api.get_candles(pair, period, count)` on demand,
so the DOM scraper, `PriceFeed`, and `CDPConnector` leave the live path. Those
files are kept but unwired (legacy), candidates for later removal.

## PocketOption WS API surface (binaryoptionstoolsv2)

```python
from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync
client = PocketOptionAsync(ssid)                       # demo/live encoded in ssid
trade_id, deal = await client.buy("EURUSD_otc", 1.0, 60)   # asset, amount, expiry(s)
trade_id, deal = await client.sell("EURUSD_otc", 1.0, 60)
result = await client.check_win(trade_id)             # 'win' | 'loss' | 'draw' (blocks until expiry)
bal    = await client.balance()
candles = await client.get_candles(asset, period, offset)
```

## Modules

| Module | Status | Purpose |
|---|---|---|
| `telegram_feed/client.py` | new | `TelegramSignalFeed` — Telethon client; `events.NewMessage(from_users=SIGNAL_BOT_USERNAME)`; pushes raw text onto an `asyncio.Queue`. |
| `telegram_feed/parser.py` | new | `parse_signal(text) -> TelegramSignal \| None`; regex table, fail-soft; pair-name normalization → API symbols (`EUR/USD OTC` → `EURUSD_otc`). |
| `broker/po_api.py` | new | `PocketOptionAPIClient` wrapping `PocketOptionAsync`: `buy/sell`, `check_win`, `balance`, `get_candles`. Translates demo guard + `DRY_RUN`. |
| `data/candles.py` | new | Adapter: API candle dicts → `o/h/l/c/v` time-indexed DataFrame the signals expect. |
| `strategy/win_rate.py` | new | `WinRateTracker` — per-(pair,direction,expiry-bucket) counts; persisted to `data/win_rates.json`; `record()`, `rate(key)->(rate,n)`, `passes(key)`; cold-start handling. |
| `strategy/signal_gate.py` | new | Runs the 3 gates; returns pass/fail + reason. |
| `strategy/manager.py` | rewritten | Event-driven: consume queue → gate → risk → execute → per-trade outcome task. |
| `config/settings.py` | changed | Add Telegram + SSID + threshold settings. |
| `main.py` | rewired | Wire Telethon feed + API client + confluence (kept) + risk (kept) + tracker (new) + new manager. |
| `signals/*`, `signals/confluence.py` | kept | Reused as the TA confirmation gate. |
| `strategy/risk.py` | kept | Reused; now fed real WIN/LOSS. |
| `utils/logger.py` | extended | Log each signal, gate decision, resolved outcome. |
| `broker/connector.py`, `broker/scraper.py`, `data/feed.py`, `broker/executor.py` | legacy | Kept, unwired; later removal. |

> Note: the Telegram package is named `telegram_feed/` (not `telegram/`) to avoid
> shadowing any installed `telegram` package.

## New settings (`.env` / `.env.example`)

```env
# Telegram (Telethon user session)
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_PHONE=+1...
TELEGRAM_SESSION=po_session
SIGNAL_BOT_USERNAME=po_broker_bot

# PocketOption WS API
PO_SSID=                             # full 42["auth",{...}] string from browser
# TRADE_MODE (DEMO/LIVE) preserved; validated against the SSID's isDemo flag

# Gating thresholds (defaults — tune)
MIN_CHANNEL_WIN_RATE=0.80
MIN_TRACKED_WIN_RATE=0.55
MIN_TRACKED_SAMPLES=20
# MIN_CONFLUENCE_SCORE=0.75          # reuses existing TA threshold
```

## Safety reconciliation (must preserve)

- **DEMO default** stays in settings.
- **Demo-mode guard** moves from page-scrape to: decode `isDemo` from the SSID
  (and/or account info) and **abort** if it doesn't match `TRADE_MODE` — same
  fail-closed behavior, still in `broker/po_api.py` before any real buy.
- **`DRY_RUN`** honored in `po_api.py`: log the would-be buy, skip `client.buy`.
- **Risk limits** unchanged, now actually effective.
- Add `*.session` to `.gitignore` (Telethon session == account credential).

## Cold-start behavior (gate 2)

When a pair has fewer than `MIN_TRACKED_SAMPLES` resolved trades, **skip** the
tracked-win-rate gate (rely on gates 1 + 3) so the tracker can warm up. Once the
sample count is reached, enforce `MIN_TRACKED_WIN_RATE`.

## Concurrency

`check_win` blocks until expiry, so each placed trade runs as its own asyncio
task: place → await `check_win` → record outcome → update tracker + risk.
`MAX_OPEN_TRADES` caps concurrency.

## Testing (all offline — no network, no SSID, no Telegram creds)

- `tests/test_parser.py` — synthetic representative messages → assert
  `TelegramSignal` fields and normalization. (Refine once real samples arrive.)
- `tests/test_win_rate.py` — thresholds, persistence, min-sample gating.
- `tests/test_signal_gate.py` — gate logic with mocked tracker/confluence/api.
- Reuse existing `tests/test_signals.py`, `tests/test_risk.py`.
- `demo_signal_test.py` — synthetic messages through the full gate pipeline with
  a mocked API, mirroring the existing `demo_test.py`.

## Phasing

1. Deps + scaffolding — add `telethon`, `binaryoptionstoolsv2` to
   `requirements.txt`/`pyproject.toml`; new settings + dataclasses + `.env.example`.
2. Telegram feed + parser (+ tests). Parser is best-effort/fail-soft until real
   `po_broker_bot` samples are supplied.
3. PO API client + demo guard + DRY_RUN + offline mock test.
4. WinRateTracker + persistence (+ tests).
5. SignalGate (3 gates) + candle adapter for TA (+ tests).
6. Rewire StrategyManager + main.py to event-driven; per-trade `check_win`
   feedback loop into tracker + risk.
7. Docs (CLAUDE.md, README) + optional dashboard refresh.

## Open items / needed from user

1. **3–5 real `po_broker_bot` messages** (verbatim) to finalize the parser and
   the pair→symbol mapping. Until then the parser handles common formats and is
   easy to update.
2. Confirm/tune threshold defaults above.
3. Credentials (`PO_SSID`, `TELEGRAM_API_ID/HASH/PHONE`) go in `.env` at run time.

## Risks / caveats

- The unofficial API and the Telethon user session both violate platform ToS and
  can break or get accounts flagged.
- `binaryoptionstoolsv2` is a Rust-backed wheel (Python 3.8–3.13); verify install.
- Parser robustness depends on channel format consistency; keep it fail-soft.
