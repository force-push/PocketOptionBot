# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Modular trading bot for PocketOption (binary options). It connects to a **user-launched Chrome instance** over the Chrome DevTools Protocol (CDP) via Playwright, scrapes live price/balance/timer data from the DOM, computes technical-analysis signals, combines them through a weighted confluence engine, enforces risk limits, and places CALL/PUT trades by clicking buttons on the page.

> ⚠️ The bot never launches its own browser or logs in. The user must already have Chrome running with `--remote-debugging-port=9222` and a logged-in PocketOption tab open. The bot finds the tab by matching `pocketoption.com` in the URL.

## Commands

```bash
# Install (pick one)
pip3 install -r requirements.txt          # pip
poetry install && poetry shell            # poetry

# Run the live bot (requires Chrome on CDP + .env configured)
python3 main.py

# Run signal logic against synthetic data — NO browser needed, best for dev/debugging
python3 demo_test.py

# Verify DOM selectors against the live page (requires Chrome on CDP)
python3 verify_selectors.py

# Tests
pytest                                    # all tests
pytest tests/test_signals.py              # one file
pytest tests/test_risk.py::test_cooldown_after_loss   # one test
pytest -v                                 # verbose
```

There is no lint/format/typecheck config committed. Async tests use explicit `@pytest.mark.asyncio` markers (no `asyncio_mode` is configured in `pyproject.toml`).

## Configuration

All runtime config comes from `.env` (copy `.env.example` → `.env`), loaded by Pydantic into a single global `settings` singleton in `config/settings.py`. Import it as `from config.settings import settings`. Two safety-critical defaults are enforced at multiple layers:

- **`TRADE_MODE` defaults to `DEMO`** and is hard-reset to DEMO if unset/empty (validator + `__init__` override). `LIVE` must be explicit.
- **`DRY_RUN` defaults to `true`** — logs trades without clicking any buttons.

When adding a new setting: add the field to `BotSettings` with an `alias` matching the uppercase env var name, and document it in `.env.example`.

## Architecture

The flow is a two-coroutine pipeline started by `main.py` and run with `asyncio.gather`:

1. **`PriceFeed.start()`** (`data/feed.py`) — polls `scraper.current_price()` at `candle_interval/10`, aggregates ticks into rolling OHLCV candles (a `deque` capped at `HISTORY_LENGTH`), and exposes them as a pandas DataFrame via the `.df` property.
2. **`StrategyManager.run()`** (`strategy/manager.py`) — the decision loop. Every `candle_interval_seconds` it reads `data_feed.df`, scores it, checks the score threshold, checks risk, then places a trade.

The decision sequence inside `StrategyManager` is the heart of the system and the order matters:

```
df → ConfluenceEngine.score() → score >= MIN_CONFLUENCE_SCORE?
   → RiskManager.is_allowed(balance)? → TradeExecutor.place_trade()
```

### Components and how they connect

- **`broker/connector.py`** — `CDPConnector` attaches to existing Chrome via `connect_over_cdp`, finds the PocketOption tab, retries with exponential backoff. It deliberately does NOT close the page on disconnect (Chrome owns it).
- **`broker/scraper.py`** — `PocketOptionScraper` reads all live data in one `page.evaluate()` call returning a `ScrapedData` dataclass. **All DOM selectors live in the top-level `SELECTORS` dict** — each entry has `css`, `xpath`, and a `js` fallback expression. When the PocketOption UI changes, update only this dict (use `verify_selectors.py` to test). Free-text values are parsed with the `_extract_float`/`_extract_int` helpers.
- **`signals/`** — each signal subclasses `BaseSignal` (`signals/base.py`), sets a class-level `name` and `weight`, and implements `async def evaluate(df) -> SignalResult`. **DataFrame columns are short names: `o, h, l, c, v`** (open/high/low/close/volume), time-indexed. Signals must be self-contained and defensive: return a neutral `SignalResult(direction=None, confidence=0.0, ...)` on insufficient data or errors rather than raising. Indicators are computed with **pure pandas/numpy** — `pandas-ta` is listed in `pyproject.toml` but disabled in `requirements.txt` (incompatible with newer Python), so do not reintroduce it.
- **`signals/confluence.py`** — `ConfluenceEngine` normalizes signal weights, evaluates all signals, sums weighted confidence into `call_score`/`put_score`. **Two hard gates: at least 3 signals must agree on a non-None direction, AND the winning side's score must beat the other.** A tie returns `None`. Returns a `ConfluenceResult` with a per-signal `breakdown`.
- **`strategy/risk.py`** — `RiskManager.is_allowed(balance)` checks, in order: min balance (`trade_amount × min_balance_multiplier`), max trades/hour (sliding 1h window over a `deque`), daily loss limit, and post-loss cooldown. It sets `self.block_reason` (string) when blocking. Call `record_trade(direction, amount, result)` after a trade resolves to update P&L state; `reset_daily()` at market open.
- **`broker/executor.py`** — `TradeExecutor.place_trade()` is the **critical safety function**. It always calls `scraper.is_demo_mode()` first: if `TRADE_MODE=DEMO` but the page is NOT in demo, it **aborts** with an ERROR result. If `DRY_RUN` is set, it logs the trade and returns without clicking. Only otherwise does it fill the amount input and click the CALL/PUT button.
- **`utils/logger.py`** — Loguru setup. `setup_logger(project_root, level)` must be called once before `log_trade()`. Human logs go to stdout + `logs/bot.log` (1-day rotation, 7-day retention); every trade is appended as one JSON line to `data/trades.jsonl`.
- **`utils/dashboard.py`** — optional Rich terminal UI.

### Adding a new signal

1. Create `signals/<name>.py` subclassing `BaseSignal`, set `name`/`weight`, implement async `evaluate`.
2. Register an instance in the `signals = [...]` list in `main.py` (weights are auto-normalized, so absolute values need not sum to 1).
3. Add a test in `tests/test_signals.py` following the existing pattern (build a DataFrame with `o/h/l/c/v` columns and a `date_range` index, assert on `result.direction`/`result.confidence`).

## Conventions

- Everything in the live path is `async`/`await`; the bot is single-process, two-coroutine. Loops swallow per-iteration exceptions and `log.error` rather than crashing the bot.
- Results passed between layers are frozen dataclasses (`SignalResult`, `ConfluenceResult`, `ScrapedData`, `Tick`); mutable state lives in `RiskManager`, `PriceFeed`, and `TradeExecutor`.
- Direction is always the string `"CALL"`, `"PUT"`, or `None` — never booleans/enums.
- Imports are absolute from the project root (e.g. `from signals.base import BaseSignal`); run commands from the repo root so the package layout resolves.

## Safety notes (do not weaken without explicit user request)

The DEMO default, the executor's demo-mode guard, the `DRY_RUN` gate, and the RiskManager limits are intentional protections against accidental real-money loss. Treat changes that bypass them as high-risk and confirm intent before making them.
