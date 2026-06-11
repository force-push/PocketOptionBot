# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**PocketOptionBot v2** — signals-driven binary options research bot.

> **Telegram integration removed 2026-06-12.** All Telethon/`po_broker_bot`
> navigation code (`telegram_feed/`, v1 `main.py` pipeline, navigator-driven
> loop) was deleted; the payout-first signals loop is the only driver. Setup
> no longer needs Telegram credentials. See PROJECT_STATUS.md for the log.

Each cycle it:
1. Fetches all active pairs ≥ `MIN_PAYOUT_PCT` from the PocketOption WS API
2. Fetches live candles per pair and runs the 11-signal confluence engine
3. Decides via `decide_signals` + risk gates → places CALL/PUT via the API
4. Resolves outcomes in background tasks and logs to `data/decisions.jsonl`
5. Places research shadow trades (expiry ladder, fade, adx_regime — see
   SHADOW_TRADE_ANALYSIS.md / TRADING_EDGE_MAP.md)

> ⚠️ The unofficial PocketOption API violates the platform's ToS and can break
> or get accounts flagged. This is for educational/research use. Keep DEMO the
> default.

## Commands

```bash
# Install
pip3 install -r requirements.txt

# Run the v2 bot (requires .env with PO_SSID configured)
python3 main_v2.py               # run indefinitely
python3 main_v2.py --cycles 5   # run exactly 5 cycles then exit
nohup tools/run_supervised.sh > /dev/null 2>&1 &   # preferred: watchdog supervisor (auto-restart + hang kill)

# Dashboard (separate process; reads decisions.jsonl + live_state.json)
python3 -m dashboard.server      # http://127.0.0.1:8787 (requires fastapi, uvicorn)

# Tests (all offline — no network, no SSID)
pytest                    # all 100 tests
pytest tests/ -v          # verbose
pytest tests/test_signals.py  # one module
```

There is no lint/format/typecheck config committed. Async tests use explicit
`@pytest.mark.asyncio` markers. Everything must be testable offline — mock the
PocketOption API; never hit the network in tests.

## Configuration

All runtime config comes from `.env` (copy `.env.example` → `.env`), loaded by
Pydantic into a single global `settings` singleton in `config/settings.py`.
Import it as `from config.settings import settings`. When adding a setting: add
the field to `BotSettings` with an `alias` matching the uppercase env var name,
and document it in `.env.example`.

Key settings groups:

- **PocketOption WS API:** `PO_SSID` (the full `42["auth",{...}]` string copied
  from the **trading terminal's** WebSocket — DevTools → Network → Socket →
  Messages, the outgoing `auth` frame). It must contain `session` and `uid`
  fields; `isDemo` (0/1) inside the payload selects demo vs live. The homepage
  socket emits a different `sessionToken` frame — that one is **not** accepted by
  `binaryoptionstoolsv2`.
- **v2 gate settings:** `DEFAULT_EXPIRY_SECONDS` (30), `STAKE_AMOUNT` (default
  `3.00`, live-editable in dashboard without restart),
  `MIN_PAYOUT_PCT` (default `92` — skip trade if PocketOption's live payout for
  the pair is below this %; set to `0` to disable), `MIN_EXPECTED_VALUE` (default
  `0.0` — EV gate; `EV = win_rate*(payout/100+1) - 1`, skip when EV is below this;
  `-0.05` allows 5% below break-even for warmup) and `MIN_EV_SAMPLES` (default
  `15` — tracked trades per (pair, direction, expiry) before the EV gate
  activates; cold-start pass-through below this).
- **TA thresholds:** `MIN_SIGNAL_AGREEMENT` (default `2` — how many of 5 signals must
  agree), `MIN_CONFLUENCE_SCORE` (default `0.40`, adaptive based on agreement count),
  `CANDLE_INTERVAL_SECONDS` (default `5` seconds — decoupled from expiry).
- **Safety:** `TRADE_MODE` (defaults to `DEMO`, hard-reset to DEMO if
  unset/empty; `LIVE` must be explicit), `DRY_RUN` (defaults `true` — log trades
  without calling the API; set to `false` for real execution), plus the RiskManager
  limits (`MAX_TRADES_PER_HOUR`, `MAX_DAILY_LOSS_USD`, etc.).

Secrets (`PO_SSID`) live in `.env` and are gitignored. Never commit them.

## Architecture (v2 live path)

```
main_v2.py loop (every ~2s, wrapped in 300s cycle timeout)
        │
        ▼  broker/po_api.py get_active_pairs()
  all active pairs ≥ MIN_PAYOUT_PCT, sorted by payout desc
        │  (BLOCKED_PAIRS excluded; MAX_PAIRS_PER_CYCLE cap)
        │
        ▼  per pair: get_candles() → data/candles.py → signals/confluence.py
  11-signal TA engine (RSI, MACD, EMA, Supertrend, Stochastic, PSAR,
  HeikinAshi, RoC, StochRSI, ADX_DMI, ATR)
        │  gates: ≥MIN_SIGNAL_AGREEMENT same direction + adaptive score floor
        │         + signal-majority check (minority score-winners blocked)
        │
        ▼  strategy/decision.py decide_signals()
        │
        ├─ SKIP → research shadows may fire (majority_blocked / fade / adx_regime)
        └─ TRADE → EV gate → strategy/risk.py → broker/po_api.py buy/sell()
                 ↓ (non-blocking)
                 background: trade resolution (poll_trade_outcome with timeouts)
                             → backfill_outcome() → tracker/risk record
                 + shadow expiry ladder replication (SHADOW_EXPIRY_SECONDS)
```

### Components

- **`broker/po_api.py`** — `PocketOptionAPIClient` wraps
  `binaryoptionstoolsv2.PocketOptionAsync(ssid)`. Exposes `buy/sell(pair, amount,
  expiry)`, `check_win(trade_id)`, `balance()`, `get_candles(pair, period, count)`,
  `get_payout(pair) -> int | None`, `get_active_pairs() -> list[dict]` (active
  assets sorted by payout, `[]` on error/not-connected), and
  `get_po_trade_history(max_deals=500) -> list[dict]` (closed-deal history via
  `closed_deals()`/`get_closed_deal()`, used to seed the win-rate tracker at
  startup). `connect()` **must** await `wait_for_assets()`
  after constructing the client — the Rust backend initialises the WebSocket lazily,
  so skipping this makes the first `get_candles()` hang indefinitely.
  `get_candles(pair, period, count)` takes a candle **count** for our callers but
  converts it to the library's `offset` arg (historical seconds = `count * period`).
  `get_payout(pair)` calls the library's synchronous `payout(asset)` method and
  returns the current payout percentage (e.g. `92`) from the live WebSocket asset
  data. **Critical safety function:** enforces the demo guard using the API-native
  `is_demo()`/`is_ssid_valid()` methods (with SSID-string fallback); if SSID is
  live but `TRADE_MODE=DEMO`, the trade is **aborted** (fail-closed). Honors
  `DRY_RUN` (log, skip API call).

- **`data/candles.py`** — adapter converting API candle dicts into the
  `o/h/l/c/v` time-indexed pandas DataFrame the signals consume.

- **`signals/`** — each signal subclasses `BaseSignal` (`signals/base.py`), sets
  class-level `name`/`weight`, implements `async def evaluate(df) ->
  SignalResult`. **DataFrame columns are short names `o, h, l, c, v`**, time
  indexed. Signals are self-contained and defensive: return a neutral
  `SignalResult(direction=None, confidence=0.0, reason="...")` on insufficient
  data or errors rather than raising. Indicators use **pure pandas/numpy** — do
  not use `pandas-ta` (incompatible with newer Python). Reason strings (e.g.,
  "RSI oversold: 28.4") provide explainability in logs and dashboard modals.

- **`signals/confluence.py`** — `ConfluenceEngine.score(df) -> ConfluenceResult`.
  Normalises weights, evaluates all signals, sums weighted confidence into
  `call_score`/`put_score`. **Two independent gates:**
  1. Agreement gate: ≥`MIN_SIGNAL_AGREEMENT` signals must agree on the SAME
     non-None direction (default 2/5, configurable).
  2. Score floor: weighted confidence sum must exceed an adaptive threshold based
     on how many signals agree (0.10–0.40). Tied scores return `direction=None`.

- **`strategy/decision.py`** — pure function `decide(bot_direction, our_direction,
  bot_win_rate, our_confluence, our_score_floor) -> Decision`. No side effects.

- **`strategy/expiry.py`** — `select_expiry(default, allowed, requested) -> int`.
  Snaps requested expiry to the nearest allowed value.

- **`strategy/trade_logger.py`** — `write_decision(path, row)` (append JSONL),
  `backfill_outcome(path, trade_id, ...)` (rewrite file to update resolved trade).

- **`strategy/win_rate.py`** — `WinRateTracker` keeps per-(pair, direction,
  expiry-bucket) win/loss counts, persisted to `data/win_rates.json`. Methods:
  `record(key, outcome)`, `rate(key) -> (rate, n)`, `passes(key, min_rate,
  min_samples)`, `seed_from_po_history(deals, default_expiry_seconds=30) -> int`
  (one-time bootstrap from PO closed-deal history — **only seeds when the tracker
  is empty** to avoid double-counting; maps buy→CALL/sell→PUT, derives expiry from
  the deal timestamp). **Cold start:** when `n < MIN_TRACKED_SAMPLES`, the
  tracked-win gate is skipped.

- **`strategy/risk.py`** — `RiskManager.is_allowed(balance)` checks, in order:
  min balance (`stake_amount × min_balance_multiplier`), max trades/hour (sliding
  1h window), daily loss limit, post-loss cooldown. Sets `self.block_reason` when
  blocking. `record_trade(direction, amount, result)` fed real WIN/LOSS outcomes.

- **`strategy/manager_v2.py`** — `StrategyManagerV2.run_once()`: the full v2
  orchestrator. Wires all of the above in sequence.

- **`utils/logger.py`** — Loguru. `setup_logger(project_root, level)` once at
  startup. Human logs → stdout + `logs/bot.log` (1-day rotation, 7-day
  retention); trades appended as JSON lines to `data/trades.jsonl`.

### Adding a new TA signal

1. Create `signals/<name>.py` subclassing `BaseSignal`, set `name`/`weight`,
   implement `async def evaluate(df) -> SignalResult`.
2. Register an instance in the `signals = [...]` list in `main_v2.py` inside
   `_build_components()`.
3. Add a test in `tests/test_signals.py` (build a DataFrame with `o/h/l/c/v`
   columns and a `date_range` index, assert on `result.direction`/`confidence`).

## Dashboard

The optional web UI (`python3 -m dashboard.server`, http://127.0.0.1:8787) reads
live trade data from `data/decisions.jsonl` and `data/live_state.json`. Key features:

- **Top chips:** Balance, Est. Weekly projection (from all historical trades),
  connection status, trading mode.
- **Est. Weekly:** Calculated as `(total_pnl / minutes_elapsed) × (7×24×60)`.
  Color-coded: green if positive, red if negative, orange if no data.
- **KPI strip:** Traded/Skipped counts, Win Rate, Avg Confluence, P&L.
- **Active Trades panel:** In-progress trades with entry, expiry, at-risk amount.
- **Performance chart:** Equity curve and win/loss distribution over 1H/1D/1W/ALL.
- **Trade History table:** Clickable rows open detail modals showing:
  - Full signal breakdown (each of 5 signals + confluence gate result)
  - Tracked win rate (the strategy's own outcome history)
  - Our TA direction + confidence scores
  - Outcome, P&L, balance after, PO trade ID
- **Settings tab:** Live-editable configuration (Pydantic BotSettings singleton),
  persists to `.env` via python-dotenv. Key settings:
  - **Signal gates:** MIN_SIGNAL_AGREEMENT (2–5), MIN_CONFLUENCE_SCORE (0.0–1.0)
  - **Trading:** STAKE_AMOUNT ($0.50–$50.00), DEFAULT_EXPIRY_SECONDS
  - **TA parameters:** All signal thresholds (RSI, MACD, Bollinger, EMA, etc.)
  - **Risk limits:** MAX_TRADES_PER_HOUR, MAX_DAILY_LOSS_USD, COOLDOWN_AFTER_LOSS_SECONDS
  - Changes take effect on next trade (no restart needed for most settings).

## Conventions

- Everything in the live path is `async`/`await`; loops swallow per-iteration
  exceptions and `log.error` rather than crashing the bot.
- Results passed between layers are frozen dataclasses (`DirectionScreen`,
  `PredictionScreen`, `SignalResult`, `ConfluenceResult`, `Decision`, `GateResult`);
  mutable state lives in `RiskManager`, `WinRateTracker`, and the API client.
  `DecisionRow` is intentionally mutable (fields like `trade_id` and `outcome`
  are backfilled after the row is created).
- Direction is always the string `"CALL"`, `"PUT"`, or `None` — never
  booleans/enums.
- Imports are absolute from the project root. Run all commands from the repo root.
- Tests must run fully offline — mock the PocketOption API.

## Safety notes (do not weaken without explicit user request)

1. **DEMO default** — `TRADE_MODE=DEMO` is the hard default. Hard-reset in `__init__`.
2. **Demo guard** — `broker/po_api.py` checks `is_demo()` via the API (authoritative)
   with SSID-string fallback. If mismatched, the trade is **aborted**.
3. **DRY_RUN** — when `True`, `buy/sell` logs the trade and returns without calling
   the API.
4. **Single PO WS session** — run the bot via `tools/run_supervised.sh`; don't
   start a second instance against the same SSID.
