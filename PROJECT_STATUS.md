# PocketOptionBot — Project Status

**Date:** 2026-06-05
**Branch:** `feature/telebot-evolution` → merged to `main`
**Version:** 0.2.0 (v2 — Telegram-driven)
**Status:** ✅ v2 COMPLETE — 100 tests passing

---

## What Changed in v2

PocketOptionBot evolved from a DOM-scraping CDP bot (v0.1) into a **Telegram-driven, API-executed** bot.

| Dimension | v0.1 (legacy) | v0.2 (current) |
|---|---|---|
| Signal source | DOM price scraper, time-driven | po_broker_bot Telegram DMs, event-driven |
| Trade execution | Playwright button clicks | PocketOption WS API (`binaryoptionstoolsv2`) |
| Direction signal | Internal TA only | Bot direction + internal TA confirmation |
| Outcome tracking | `PENDING` only (no DOM feedback) | Real WIN/LOSS via `check_win()` |
| Risk limits | Cooldown/daily-loss ineffective | Fully effective (fed real outcomes) |
| Learning log | `data/trades.jsonl` (basic) | `data/decisions.jsonl` (full decision audit trail) |
| Win rate tracker | None | Per-pair `data/win_rates.json` |
| Demo guard | DOM page scrape | SSID decode + API-native `is_demo()` |

---

## Completed Tasks (v2 feature branch — 13 tasks)

| # | Task | Module | Tests |
|---|---|---|---|
| 1 | Prediction parser | `telegram_feed/prediction_parser.py` | ✅ |
| 2 | Direction-screen parser | `telegram_feed/direction_parser.py` | ✅ |
| 3 | Generic pair normalizer | `telegram_feed/pair_norm.py` | ✅ |
| 4 | Expiry selection | `strategy/expiry.py` | ✅ |
| 5 | Decision logic | `strategy/decision.py` | ✅ |
| 6 | Learning log writer | `strategy/trade_logger.py` | ✅ |
| 7 | v2 Settings | `config/settings.py` | ✅ |
| 8 | Navigator (button driver) | `telegram_feed/navigator.py` | ✅ |
| 9 | Orchestrator | `strategy/manager_v2.py` | ✅ |
| 10 | Entrypoint | `main_v2.py` | ✅ |
| 11 | Smoke tool | `tools/v2_smoke.py` | ✅ |
| 12 | API guard upgrade | `broker/po_api.py` | ✅ |
| 13 | Cleanup + full suite | `strategy/signal_gate.py` | ✅ |

**Total: 100 tests passing (all offline)**

---

## Key Files

| File | Purpose |
|---|---|
| `main_v2.py` | v2 entrypoint. `python3 main_v2.py [--cycles N]` |
| `tools/v2_smoke.py` | One dry-run cycle smoke test. Run before each real session. |
| `tools/gen_telegram_session.py` | One-time Telethon session auth |
| `data/decisions.jsonl` | Full decision audit log (one row per evaluated signal) |
| `data/win_rates.json` | Persisted per-pair win rate tracker |
| `logs/bot.log` | Human-readable rotating log |
| `.env` | All runtime config (never committed) |
| `docs/superpowers/plans/2026-06-04-telebot-evolution.md` | Implementation plan (reference) |

---

## Module Summary

### `telegram_feed/`

| Module | Description |
|---|---|
| `navigator.py` | Drives po_broker_bot buttons via Telethon: `/start` → Start Autotrade → pair selection → direction screen. Handles nag screens automatically. **Never clicks amount/stake buttons** (safety invariant). |
| `prediction_parser.py` | Parses the prediction screen text → `PredictionScreen` with `PairPrediction` objects (pair, win rate, is_top). |
| `direction_parser.py` | Parses the direction screen text → `DirectionScreen` (direction=CALL/PUT, setup, indicators_raw). |
| `pair_norm.py` | Normalises pair labels like `GBP/USD OTC` → `GBPUSD_otc` using a legacy mapping table with generic fallback. |
| `client.py` | Legacy `TelegramSignalFeed` listener (kept, not in v2 path). |
| `parser.py` | Legacy signal parser (kept, not in v2 path). |

### `broker/`

| Module | Description |
|---|---|
| `po_api.py` | `PocketOptionAPIClient`: wraps `binaryoptionstoolsv2.PocketOptionAsync`. Enforces demo guard (API-native `is_demo()` + SSID fallback), `DRY_RUN` gate, and fail-closed behavior. Exposes `buy/sell/check_win/balance/get_candles`. |
| `connector.py` | Legacy CDP connector (unwired). |
| `scraper.py` | Legacy DOM scraper (unwired). |
| `executor.py` | Legacy CDP executor (unwired). |

### `strategy/`

| Module | Description |
|---|---|
| `manager_v2.py` | `StrategyManagerV2.run_once()`: full orchestrator. navigate → parse → TA → decide → log → [trade] → check_win → backfill. |
| `decision.py` | Pure function: bot + our direction agreement → `Decision(trade, combined_probability, skip_reason)`. |
| `expiry.py` | `select_expiry()`: snaps a requested duration to the nearest allowed expiry. |
| `trade_logger.py` | `write_decision()`: append a `DecisionRow` to JSONL. `backfill_outcome()`: rewrite file to update trade outcome after check_win. |
| `win_rate.py` | `WinRateTracker`: per-(pair, direction, expiry-bucket) win/loss counts, persisted to `data/win_rates.json`. Cold-start handling (skip gate 2 until n ≥ min samples). |
| `risk.py` | `RiskManager`: 5 hard gates (min balance, trades/hr, daily loss, cooldown, max open trades). Now fed real WIN/LOSS from `check_win`. |
| `signal_gate.py` | Legacy 3-gate filter (kept; used by `manager.py`). |
| `manager.py` | Legacy event-driven manager (kept, not in v2 path). |

### `signals/`

| Module | Description |
|---|---|
| `confluence.py` | `ConfluenceEngine.score(df)` → `ConfluenceResult(direction, score, breakdown, reason)`. Hard gates: ≥3 signals must agree on **same** direction; tied scores → None. |
| `rsi.py` | RSI oversold/overbought (period=14). |
| `macd.py` | MACD line vs signal line crossover. |
| `bollinger.py` | Price vs upper/lower Bollinger Bands. |
| `ema_cross.py` | Fast vs slow EMA crossover (default 9/21). |
| `candle_pattern.py` | Engulfing, hammer, shooting star, doji patterns. |

---

## Next Steps

### Immediate (before live trading)
1. **Smoke test** — `python3 tools/v2_smoke.py` each session start to confirm Telegram session is alive and navigation works.
2. **Enable pair gate** — Set `PAIR_SELECT_MIN_WIN_RATE=0.82` in `.env` (currently `0.0` for testing).
3. **Confirm demo P&L** — Run `TRADE_MODE=DEMO, DRY_RUN=false` for several days. Analyse `data/decisions.jsonl` for calibration.

### Short-term (v2.1)
- **Dashboard** — Web UI to display `decisions.jsonl` data (cycle outcomes, pair win rates, P&L, signal breakdowns).
- **Dynamic stakes** — Size position based on combined probability (Kelly-derived).
- **Better pair selection** — Cross-reference bot win rate with our tracked win rate per pair.
- **Blocked pairs** — Auto-block pairs that show historical negative P&L (carry forward from Telebot's `pair_learnings.json`).

### Medium-term (v3)
- **Improve signal quality** — Expand TA signals; backtest against decisions.jsonl outcomes.
- **Autonomous calibration** — Auto-tune gate thresholds based on rolling outcomes.
- **Multi-pair support** — Evaluate all pairs in a single prediction screen, not just the top pick.

---

## Safety Checklist Before Live Trading

- [ ] `tools/v2_smoke.py` passes cleanly (Telegram session works, navigation works)
- [ ] `TRADE_MODE=DEMO`, `DRY_RUN=false` runs profitably for ≥ 1 week
- [ ] `data/decisions.jsonl` shows consistent agreement between bot + TA direction on winning pairs
- [ ] `PAIR_SELECT_MIN_WIN_RATE=0.82` is set
- [ ] Win rate tracker has ≥ 20 samples per active pair (`data/win_rates.json`)
- [ ] No legacy `pocket_robot_trader.py` running (session conflict)
- [ ] Emergency kill: `Ctrl+C` (graceful) or `kill <pid>` (force)
- [ ] You have read and accepted the binary options risk disclaimer

---

**Last Updated:** 2026-06-05
