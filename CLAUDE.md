# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**PocketOptionBot v2** — Telegram-driven binary options trading bot.

It reads trade signals from the Telegram bot **`po_broker_bot`** by _driving its
inline button menus_ with a Telethon user session (MTProto). For each signal it:
1. Extracts the top pair + win rate (prediction screen)
2. Navigates to the direction screen to get CALL/PUT
3. Fetches live candles via the PocketOption WS API and runs 5 internal TA signals
4. Decides: agree with the bot AND our TA → place trade via the API; otherwise SKIP
5. Awaits the `check_win` outcome and logs everything to `data/decisions.jsonl`

> ⚠️ Both the unofficial PocketOption API and the Telethon **user** session
> violate the respective platforms' ToS and can break or get accounts flagged.
> This is for educational/research use. Keep DEMO the default.

> **Migration status:** v2 is the live path. The legacy CDP modules
> (`broker/connector.py`, `broker/scraper.py`, `broker/executor.py`,
> `data/feed.py`, `verify_selectors.py`) are kept but **unwired** — not in the
> live path, candidates for removal.

## Commands

```bash
# Install
pip3 install -r requirements.txt

# Run the v2 bot (requires .env with PO_SSID + TELEGRAM_* configured)
python3 main_v2.py               # run indefinitely
python3 main_v2.py --cycles 5   # run exactly 5 cycles then exit

# Smoke test — one dry-run cycle against real bot (DRY_RUN forced true)
python3 tools/v2_smoke.py
python3 tools/v2_smoke.py --pair GBPUSD_otc   # skip navigation, test TA only

# Gate pipeline against synthetic signals — NO network/SSID/Telegram needed
python3 demo_signal_test.py

# Tests (all offline — no network, no SSID, no Telegram creds)
pytest                    # all 100 tests
pytest tests/ -v          # verbose
pytest tests/test_signals.py  # one module
```

There is no lint/format/typecheck config committed. Async tests use explicit
`@pytest.mark.asyncio` markers. Everything must be testable offline — mock the
Telethon client and the PocketOption API; never hit the network in tests.

## Configuration

All runtime config comes from `.env` (copy `.env.example` → `.env`), loaded by
Pydantic into a single global `settings` singleton in `config/settings.py`.
Import it as `from config.settings import settings`. When adding a setting: add
the field to `BotSettings` with an `alias` matching the uppercase env var name,
and document it in `.env.example`.

Key settings groups:

- **Telegram (Telethon user session):** `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
  `TELEGRAM_SESSION`, `SIGNAL_BOT_USERNAME` (default `po_broker_bot`).
- **PocketOption WS API:** `PO_SSID` (the full `42["auth",{...}]` string copied
  from the **trading terminal's** WebSocket — DevTools → Network → Socket →
  Messages, the outgoing `auth` frame). It must contain `session` and `uid`
  fields; `isDemo` (0/1) inside the payload selects demo vs live. The homepage
  socket emits a different `sessionToken` frame — that one is **not** accepted by
  `binaryoptionstoolsv2`.
- **v2 gate settings:** `PAIR_SELECT_MIN_WIN_RATE` (default `0.0` = disabled
  during testing; set to `0.82` for real runs), `DEFAULT_EXPIRY_SECONDS` (30),
  `CLICK_TRADE_ANYWAY` (true — auto-dismiss nag screens), `STAKE_AMOUNT` (1.50).
- **TA thresholds:** `MIN_SIGNAL_AGREEMENT` (default `2` — how many of 5 signals must
  agree), `MIN_CONFLUENCE_SCORE` (default `0.40`, adaptive based on agreement count),
  `CANDLE_INTERVAL_SECONDS` (default `5` seconds — decoupled from expiry).
- **Safety:** `TRADE_MODE` (defaults to `DEMO`, hard-reset to DEMO if
  unset/empty; `LIVE` must be explicit), `DRY_RUN` (defaults `true` — log trades
  without calling the API; set to `false` for real execution), plus the RiskManager
  limits (`MAX_TRADES_PER_HOUR`, `MAX_DAILY_LOSS_USD`, etc.).

Secrets (`PO_SSID`, Telegram credentials) and the Telethon `*.session` file live
in `.env` / the working dir and are gitignored. Never commit them.

## Architecture (v2 live path)

```
po_broker_bot (Telegram)
        │
        ▼  telegram_feed/navigator.py (drives buttons)
  Start Autotrade → prediction screen → pair selection → direction screen
        │
        ▼  telegram_feed/prediction_parser.py + pair_norm.py
  PredictionScreen → top PairPrediction (pair, win_rate, is_top)
        │  gate: win_rate ≥ PAIR_SELECT_MIN_WIN_RATE
        │
        ▼  telegram_feed/direction_parser.py
  DirectionScreen → direction (CALL/PUT), setup, indicators_raw
        │
        ▼  broker/po_api.py → data/candles.py → signals/confluence.py
  5-signal TA engine (RSI, MACD, Bollinger, EMA Cross, Candle Patterns)
        │  ≥3 signals same direction + score ≥ MIN_CONFLUENCE_SCORE
        │
        ▼  strategy/decision.py
  Decision(trade, combined_probability, skip_reason)
        │
        ▼  strategy/trade_logger.py
  Write DecisionRow → data/decisions.jsonl
        │
        ├─ SKIP → back_to_menu (background task)
        └─ TRADE → strategy/risk.py → broker/po_api.py buy/sell()
                 ↓ (immediately, non-blocking)
                 asyncio.create_task(back_to_menu)
                 ↓ (main loop continues immediately for next pair analysis)
                 ┌──────────────────────────────────────┐
                 │ Background async tasks run parallel: │
                 │ 1. Menu navigation                   │
                 │ 2. Trade outcome resolution:         │
                 │    - Wait for expiry time            │
                 │    - check_win(trade_id)             │
                 │    - backfill_outcome()              │
                 │    - record() win/loss for tracking  │
                 └──────────────────────────────────────┘
```

### Components

- **`telegram_feed/navigator.py`** — `Navigator` drives `po_broker_bot` button
  menus via Telethon. **SAFETY:** must NEVER click an amount/stake button — that
  places a martingale bot trade, not our API trade. Only clicks: pair names,
  "Start Autotrade", "Main Menu", "Trade Anyway" nag buttons.

- **`telegram_feed/prediction_parser.py`** — `parse_prediction(text) ->
  PredictionScreen | None`. Parses the pair/win-rate prediction screen. Returns
  `None` if the text doesn't look like a prediction screen.

- **`telegram_feed/direction_parser.py`** — `parse_direction_screen(text) ->
  DirectionScreen | None`. Parses the CALL/PUT direction screen (BUY→CALL,
  SELL→PUT).

- **`telegram_feed/pair_norm.py`** — `normalize_pair(label) -> str | None`.
  Normalises pair labels like `GBP/USD OTC` → `GBPUSD_otc`. Uses a legacy
  table first, then a generic fallback.

- **`broker/po_api.py`** — `PocketOptionAPIClient` wraps
  `binaryoptionstoolsv2.PocketOptionAsync(ssid)`. Exposes `buy/sell(pair, amount,
  expiry)`, `check_win(trade_id)`, `balance()`, `get_candles(pair, period, count)`.
  `connect()` **must** await `wait_for_assets()` after constructing the client —
  the Rust backend initialises the WebSocket lazily, so skipping this makes the
  first `get_candles()` hang indefinitely. `get_candles(pair, period, count)`
  takes a candle **count** for our callers but converts it to the library's
  `offset` arg (historical seconds = `count * period`). **Critical safety
  function:** enforces the demo guard using the API-native
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
  min_samples)`. **Cold start:** when `n < MIN_TRACKED_SAMPLES`, the tracked-win
  gate is skipped.

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
- Tests must run fully offline — mock Telethon and the PocketOption API.

## Safety notes (do not weaken without explicit user request)

1. **DEMO default** — `TRADE_MODE=DEMO` is the hard default. Hard-reset in `__init__`.
2. **Demo guard** — `broker/po_api.py` checks `is_demo()` via the API (authoritative)
   with SSID-string fallback. If mismatched, the trade is **aborted**.
3. **DRY_RUN** — when `True`, `buy/sell` logs the trade and returns without calling
   the API.
4. **Navigator safety** — never click amount/stake buttons (martingale trap).
5. **Single session writer** — only one Telethon session writer at a time.
6. **PAIR_SELECT_MIN_WIN_RATE=0.0** during testing (gate disabled); restore to
   `0.82` for real runs.
