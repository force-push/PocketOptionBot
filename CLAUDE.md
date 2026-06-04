# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Trading bot for PocketOption (binary options). It ingests trade signals from the
Telegram bot **`po_broker_bot`** (read via a Telethon user session), filters them
through three quality gates to "find high win rate trades", and places CALL/PUT
trades via the **unofficial PocketOption WebSocket API** (`binaryoptionstoolsv2`,
authenticated with an SSID session token). It then reads each trade's real
outcome with `check_win` and feeds that back into a persistent win-rate tracker
and the risk manager.

> ⚠️ Both the unofficial PocketOption API and the Telethon **user** session
> violate the respective platforms' ToS and can break or get accounts flagged.
> This is for educational/research use. Keep DEMO the default.

> **Architecture is mid-migration.** The repo is moving from a DOM-scraping,
> time-driven design to the Telegram-driven, event-driven design described here.
> See `PLAN.md` for the full plan and phases. The legacy CDP modules
> (`broker/connector.py`, `broker/scraper.py`, `broker/executor.py`,
> `data/feed.py`, `verify_selectors.py`) are kept but **unwired** — not in the
> live path, candidates for removal.

## Commands

```bash
# Install (pick one)
pip3 install -r requirements.txt          # pip
poetry install && poetry shell            # poetry

# Run the live bot (requires .env with PO_SSID + TELEGRAM_* configured)
python3 main.py

# Run the gate pipeline against synthetic signals — NO network/SSID/Telegram needed
python3 demo_signal_test.py

# Tests (all offline — no network, no SSID, no Telegram creds)
pytest                                    # all tests
pytest tests/test_parser.py               # one file
pytest tests/test_win_rate.py::test_cold_start   # one test
pytest -v                                 # verbose
```

There is no lint/format/typecheck config committed. Async tests use explicit
`@pytest.mark.asyncio` markers (no `asyncio_mode` is configured in
`pyproject.toml`). Everything must be testable offline — mock the Telethon client
and the PocketOption API; never hit the network in tests.

## Configuration

All runtime config comes from `.env` (copy `.env.example` → `.env`), loaded by
Pydantic into a single global `settings` singleton in `config/settings.py`.
Import it as `from config.settings import settings`. When adding a setting: add
the field to `BotSettings` with an `alias` matching the uppercase env var name,
and document it in `.env.example`.

Key settings groups:

- **Telegram (Telethon user session):** `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
  `TELEGRAM_PHONE`, `TELEGRAM_SESSION`, `SIGNAL_BOT_USERNAME` (default
  `po_broker_bot`).
- **PocketOption WS API:** `PO_SSID` (the full `42["auth",{...}]` string copied
  from the browser; demo/live is encoded in it).
- **Gating thresholds:** `MIN_CHANNEL_WIN_RATE` (default `0.80`),
  `MIN_TRACKED_WIN_RATE` (`0.55`), `MIN_TRACKED_SAMPLES` (`20`),
  `MIN_CONFLUENCE_SCORE` (`0.75`, reused for the TA gate).
- **Safety:** `TRADE_MODE` (defaults to `DEMO`, hard-reset to DEMO if
  unset/empty; `LIVE` must be explicit), `DRY_RUN` (defaults `true` — log trades
  without calling the API), plus the RiskManager limits.

Secrets (`PO_SSID`, Telegram credentials) and the Telethon `*.session` file live
in `.env` / the working dir and are gitignored. Never commit them.

## Architecture

The bot is **event-driven**. `main.py` wires the components and runs two
coroutines with `asyncio.gather`: a Telegram listener that pushes raw messages
onto an `asyncio.Queue`, and `StrategyManager.run()` which consumes that queue.

The decision sequence inside `StrategyManager` per signal — order matters:

```
raw text → parse_signal() → SignalGate (3 gates, all must pass)
        → RiskManager.is_allowed(balance) → PocketOptionAPIClient.buy/sell()
        → (per-trade task) check_win() → WinRateTracker.record() + RiskManager.record_trade()
```

### Components and how they connect

- **`telegram_feed/client.py`** — `TelegramSignalFeed` uses Telethon
  (`events.NewMessage(from_users=SIGNAL_BOT_USERNAME)`) to receive the bot's DMs
  and push raw message text onto an `asyncio.Queue`. The package is named
  `telegram_feed` (not `telegram`) to avoid shadowing the PyPI `telegram` package.
- **`telegram_feed/parser.py`** — `parse_signal(text) -> TelegramSignal | None`.
  Regex-table based and **fail-soft**: unparseable messages return `None`, never
  raise. Normalizes pair names to API symbols (e.g. `EUR/USD OTC` →
  `EURUSD_otc`). `TelegramSignal` is a frozen dataclass: `pair`, `direction`
  (`"CALL"`/`"PUT"`), `expiry_seconds`, `stated_win_rate` (`float | None`),
  `raw`, `timestamp`. The exact regexes depend on real `po_broker_bot` samples;
  keep them centralized and easy to update.
- **`broker/po_api.py`** — `PocketOptionAPIClient` wraps
  `binaryoptionstoolsv2.PocketOptionAsync(ssid)`. Exposes `buy/sell(pair, amount,
  expiry)`, `check_win(trade_id)`, `balance()`, `get_candles(pair, period,
  count)`. **This is the critical safety function.** Before any real buy it
  enforces the demo guard (decode `isDemo` from the SSID / account info; if it
  doesn't match `TRADE_MODE`, **abort** with an error) and honors `DRY_RUN` (log
  the would-be trade, skip the API call). Same fail-closed behavior the legacy
  executor had.
- **`data/candles.py`** — adapter converting API candle dicts into the
  `o/h/l/c/v` time-indexed pandas DataFrame the signals consume.
- **`signals/`** — each signal subclasses `BaseSignal` (`signals/base.py`), sets
  class-level `name`/`weight`, implements `async def evaluate(df) ->
  SignalResult`. **DataFrame columns are short names `o, h, l, c, v`**, time
  indexed. Signals are self-contained and defensive: return a neutral
  `SignalResult(direction=None, confidence=0.0, ...)` on insufficient data or
  errors rather than raising. Indicators use **pure pandas/numpy** — `pandas-ta`
  is listed in `pyproject.toml` but disabled in `requirements.txt` (incompatible
  with newer Python); do not reintroduce it.
- **`signals/confluence.py`** — `ConfluenceEngine` normalizes weights, evaluates
  all signals, sums weighted confidence into `call_score`/`put_score`. **Two hard
  gates: ≥3 signals must agree on a non-None direction, AND the winning side must
  beat the other.** A tie returns `None`. Reused as gate 3 (TA confirmation).
- **`strategy/win_rate.py`** — `WinRateTracker` keeps per-(pair, direction,
  expiry-bucket) win/loss counts, persisted to `data/win_rates.json`. Methods:
  `record(key, outcome)`, `rate(key) -> (rate, n)`, `passes(key, min_rate,
  min_samples)`. **Cold start:** when `n < MIN_TRACKED_SAMPLES`, the tracked-win
  gate is skipped (rely on gates 1 + 3) so stats can warm up.
- **`strategy/signal_gate.py`** — runs the three gates and returns a pass/fail
  with a reason: (1) `stated_win_rate >= MIN_CHANNEL_WIN_RATE`, (2)
  `WinRateTracker.passes(...)`, (3) fetch candles via the API → `ConfluenceEngine`
  direction agrees with the signal.
- **`strategy/risk.py`** — `RiskManager.is_allowed(balance)` checks, in order:
  min balance (`trade_amount × min_balance_multiplier`), max trades/hour (sliding
  1h window over a `deque`), daily loss limit, post-loss cooldown. Sets
  `self.block_reason` when blocking. `record_trade(direction, amount, result)`
  after a trade resolves; `reset_daily()` at market open. Now fed real
  WIN/LOSS from `check_win`, so the cooldown/daily-loss limits are finally
  effective.
- **`strategy/manager.py`** — the event-driven decision loop: consume raw text
  from the queue, parse, gate, risk-check, place, and spawn a per-trade task that
  awaits `check_win` (which blocks until expiry) and records the outcome.
  `MAX_OPEN_TRADES` caps concurrent in-flight trades.
- **`utils/logger.py`** — Loguru. `setup_logger(project_root, level)` once before
  `log_trade()`. Human logs → stdout + `logs/bot.log` (1-day rotation, 7-day
  retention); every signal/trade/outcome appended as JSON lines to
  `data/trades.jsonl`.

### Adding a new signal

1. Create `signals/<name>.py` subclassing `BaseSignal`, set `name`/`weight`,
   implement async `evaluate`.
2. Register an instance in the `signals = [...]` list in `main.py` (weights are
   auto-normalized).
3. Add a test in `tests/test_signals.py` (build a DataFrame with `o/h/l/c/v`
   columns and a `date_range` index, assert on `result.direction`/`confidence`).

## Conventions

- Everything in the live path is `async`/`await`; loops swallow per-iteration
  exceptions and `log.error` rather than crashing the bot.
- Results passed between layers are frozen dataclasses (`TelegramSignal`,
  `SignalResult`, `ConfluenceResult`, `GateResult`); mutable state lives in
  `RiskManager`, `WinRateTracker`, and the API client.
- Direction is always the string `"CALL"`, `"PUT"`, or `None` — never
  booleans/enums.
- Imports are absolute from the project root (e.g. `from signals.base import
  BaseSignal`); run commands from the repo root.
- Tests and `demo_signal_test.py` must run fully offline — mock Telethon and the
  PocketOption API.

## Safety notes (do not weaken without explicit user request)

The DEMO default, the API client's demo-mode guard, the `DRY_RUN` gate, and the
RiskManager limits are intentional protections against accidental real-money
loss. Treat changes that bypass them as high-risk and confirm intent first. Keep
secrets and the Telethon `*.session` file out of git.
