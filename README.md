# PocketOptionBot v2

**Telegram-driven binary options bot.** Reads trade signals from `po_broker_bot` via Telegram, confirms with internal technical analysis, then places independent CALL/PUT trades via the PocketOption WebSocket API.

> ⚠️ **Risk Disclaimer:** Binary options carry extreme risk of capital loss. Both the unofficial PocketOption API and the Telethon user session violate the respective platforms' Terms of Service. This project is for **educational and research purposes only.** Always use DEMO mode. Never risk money you cannot afford to lose.

---

## How It Works

```
po_broker_bot (Telegram)
        │
        │  Telethon user session reads DMs
        ▼
  Navigator drives po_broker_bot menus
        │  → top pair + win rate (prediction screen)
        │  → CALL/PUT direction (direction screen)
        ▼
  Pair quality gate
        │  win rate ≥ PAIR_SELECT_MIN_WIN_RATE (default 0.82)
        ▼
  Internal TA Confluence Engine (5 signals)
        │  RSI · MACD · Bollinger · EMA Cross · Candle Patterns
        │  ≥ 3 signals must agree on same direction
        ▼
  Decision logic
        │  bot direction must match our TA direction
        │  combined probability = (bot win% + our confluence score) / 2
        ▼
  Risk Manager gates
        │  min balance · max trades/hr · daily loss limit · cooldown
        ▼
  PocketOption API (binaryoptionstoolsv2)
        │  buy/sell(pair, $1.50, expiry)
        │  Never clicks the martingale bot's amount button
        │  Up to 6 trades open concurrently
        ▼
  Background resolver (non-blocking)
        │  poll_trade_outcome() → polls closed_deals() after expiry
        │  WIN / LOSS / DRAW (check_win fallback if polling exhausted)
        ▼
  decisions.jsonl  +  WinRateTracker  +  RiskManager
```

---

## Architecture

```
PocketOptionBot/
├── main_v2.py                    # v2 entrypoint (--cycles N)
├── main.py                       # legacy entrypoint (unwired, kept)
│
├── config/
│   └── settings.py               # All config via .env (Pydantic)
│
├── telegram_feed/
│   ├── client.py                 # TelegramSignalFeed (legacy listener)
│   ├── navigator.py              # Button-drives po_broker_bot menus
│   ├── prediction_parser.py      # Parses pair/win-rate screen
│   ├── direction_parser.py       # Parses CALL/PUT direction screen
│   ├── pair_norm.py              # Normalises pair labels → API symbols
│   └── parser.py                 # Legacy signal parser (kept)
│
├── broker/
│   └── po_api.py                 # PocketOptionAPIClient (buy/sell/check_win)
│   └── [connector/scraper/executor.py]  # Legacy CDP modules (unwired)
│
├── signals/
│   ├── base.py                   # BaseSignal abstract class
│   ├── rsi.py                    # RSI (oversold/overbought)
│   ├── macd.py                   # MACD crossover
│   ├── bollinger.py              # Bollinger Bands mean reversion
│   ├── ema_cross.py              # EMA golden/death cross
│   ├── candle_pattern.py         # Candlestick patterns
│   └── confluence.py             # ConfluenceEngine: weighted scoring + ≥3 gate
│
├── strategy/
│   ├── manager_v2.py             # v2 orchestrator (navigate→TA→decide→trade)
│   ├── decision.py               # Pure agree/disagree + combined probability
│   ├── expiry.py                 # Nearest-allowed expiry selection
│   ├── trade_logger.py           # decisions.jsonl writer + outcome backfill
│   ├── signal_gate.py            # Legacy 3-gate filter (kept)
│   ├── win_rate.py               # Per-pair win rate tracker (data/win_rates.json)
│   ├── risk.py                   # RiskManager (balance/hr/daily/cooldown)
│   └── manager.py                # Legacy event-driven manager (kept)
│
├── data/
│   ├── candles.py                # API candle dicts → o/h/l/c/v DataFrame
│   └── feed.py                   # Legacy price feed (kept)
│
├── tools/
│   ├── v2_smoke.py               # One dry-run cycle smoke test
│   ├── gen_telegram_session.py   # One-time Telethon session auth
│   └── test_telegram_feed.py     # Live feed capture / debugging
│
├── utils/
│   └── logger.py                 # Loguru: logs/ + data/trades.jsonl
│
├── tests/                        # 100 offline unit tests
│
└── docs/
    └── superpowers/plans/
        └── 2026-06-04-telebot-evolution.md  # Full implementation plan
```

---

## Quick Start

### 1. Prerequisites

- Python 3.12+
- An existing Telethon session authenticated to your Telegram account  
  (run `python3 tools/gen_telegram_session.py` once if not set up)
- A PocketOption SSID (copy the `42["auth",{...}]` string from your browser's DevTools Network tab while logged in to pocketoption.com)

### 2. Install

```bash
cd ~/code/openclaw/projects/PocketOptionBot
pip3 install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

**Minimum required settings:**

```env
# Telegram
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION=~/.telebot/telegram.session

# PocketOption
PO_SSID=42["auth",{"session":"...","isDemo":1,...}]

# Safety (leave these until you are confident)
TRADE_MODE=DEMO
DRY_RUN=true
STAKE_AMOUNT=1.50
```

### 4. Smoke test (no trade placed)

```bash
python3 tools/v2_smoke.py
# Runs one full cycle: navigate → TA → decide → log (DRY_RUN forced true)
# Check data/decisions.jsonl for the result
```

### 5. Run the bot

```bash
python3 main_v2.py               # run until Ctrl-C
python3 main_v2.py --cycles 5    # run exactly 5 cycles then exit
```

---

## Web Dashboard

A live monitoring + settings UI (FastAPI + WebSocket backend, zero-build vanilla
JS frontend). Landscape layout: **Performance** (equity/P&L curve + win/loss)
· **Active Trades** (live countdowns) · **Trade History**, plus an editable
**Settings** tab. It reads the bot's output files and updates live over a
WebSocket — it does **not** need the trading stack, an SSID, or Telegram.

### Run it locally (one command)

```bash
git clone https://github.com/force-push/PocketOptionBot.git
cd PocketOptionBot
./scripts/run_dashboard.sh          # venv + install + seed demo data + serve
```

Then open **http://127.0.0.1:8787**. Use `--no-seed` to keep existing data.

### Or step by step (works on Windows too)

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dashboard.txt
python tools/dashboard_demo.py       # optional: seed synthetic demo data
python -m dashboard.server           # http://127.0.0.1:8787
```

`requirements-dashboard.txt` is a minimal 5-package subset (FastAPI, uvicorn,
watchfiles, pydantic-settings, python-dotenv) — no playwright / telethon / Rust
wheel needed just to view the dashboard.

### Demo data vs. live trading data

- **Demo (default above):** `tools/dashboard_demo.py` writes deterministic
  synthetic `data/decisions.jsonl` + `data/live_state.json` so the UI is fully
  populated with no bot running. Re-run it any time to refresh.
- **Live:** run the bot with the bridge enabled so it streams real state to the
  dashboard as it trades:

  ```bash
  DASHBOARD_ENABLED=true python3 main_v2.py
  ```

  Start the dashboard server in a second terminal; it picks up changes live.

### Settings tab (writes to `.env`)

The Settings tab can edit configuration and save it back to `.env`. Safety rails
are enforced server-side: secrets are masked and only written when changed, and
flipping `TRADE_MODE` to **LIVE** is fail-closed — it requires explicit
confirmation **and** an SSID that decodes as a live session. Most changes need a
bot restart to take effect (the UI flags which).

### Dashboard settings (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DASHBOARD_ENABLED` | `false` | bot streams live state when `true` |
| `DASHBOARD_HOST` | `127.0.0.1` | bind address (keep localhost) |
| `DASHBOARD_PORT` | `8787` | server port |
| `DASHBOARD_TOKEN` | _(unset)_ | when set, required to save settings (sent as a Bearer token) |

> 🔒 Bind to `127.0.0.1` only. The Settings tab can change trading config, so do
> **not** expose the dashboard publicly without setting `DASHBOARD_TOKEN`.

---

## Configuration Reference

All settings live in `.env`. See `.env.example` for the full list.

### Critical safety settings

| Variable | Default | Description |
|---|---|---|
| `TRADE_MODE` | `DEMO` | `DEMO` or `LIVE`. Hard-reset to DEMO if unset. |
| `DRY_RUN` | `true` | Log trades but never call buy/sell on the API. |
| `STAKE_AMOUNT` | `1.50` | Fixed stake per trade (USD). |

### v2 gate settings

| Variable | Default | Description |
|---|---|---|
| `PAIR_SELECT_MIN_WIN_RATE` | `0.0` | Minimum bot-stated win rate to consider a pair. Set to `0.82` for real runs; `0.0` disables the gate during testing. |
| `DEFAULT_EXPIRY_SECONDS` | `30` | Trade expiry. Snapped to nearest allowed value. |
| `CLICK_TRADE_ANYWAY` | `true` | Auto-click the "low-balance" nag page when it appears. |
| `DECISIONS_LOG_PATH` | `data/decisions.jsonl` | Path for the structured decision log. |
| `MIN_CONFLUENCE_SCORE` | `0.35` | Minimum TA confluence score to agree with a signal (reduced from 0.75 to allow more trades during testing; actual threshold is adaptive based on signal agreement). |
| `MIN_SIGNAL_AGREEMENT` | `3` | Minimum number of signals that must agree on same direction (increased from 2 to 3 for stricter confluence). |
| `BLOCKED_PAIRS` | `["EURUSD_otc", "ETHUSD_otc"]` | List of pair API symbols (e.g., `"EURUSD_otc"`) to skip during pair selection. When the bot presents a list of candidate pairs, the navigator cycles through and selects the first non-blocked pair, avoiding wasted analysis time. If all pairs are blocked, the cycle is skipped. |
| `SHADOW_RECORD_MODE` | `false` | **Research/data-collection mode (DEMO only).** When `true` and `TRADE_MODE=DEMO`, the bot stops *blocking* at the TA-agreement, EV, and risk gates — it places the bot-direction trade anyway, tags the row `shadow=true` with `would_skip_reason`, and records the outcome. This builds an **uncensored** dataset (normally we only see outcomes for trades that passed every gate). Hard-guarded: ignored in LIVE; `low_payout` is still enforced; shadow outcomes are written to `decisions.jsonl` but do **not** feed the production win-rate tracker or risk stats. See [Research & Calibration](#research--calibration). |

### Risk settings

| Variable | Default | Description |
|---|---|---|
| `MAX_TRADES_PER_HOUR` | `10` | Rolling 1-hour cap. |
| `MAX_DAILY_LOSS_USD` | `20.0` | Daily loss stops trading for the day. |
| `COOLDOWN_AFTER_LOSS_SECONDS` | `120` | Pause after each loss. |
| `MIN_BALANCE_MULTIPLIER` | `5.0` | Balance must be ≥ this × stake to trade. |

### Telegram settings

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_API_ID` | — | From my.telegram.org |
| `TELEGRAM_API_HASH` | — | From my.telegram.org |
| `TELEGRAM_SESSION` | `po_session` | Path to `.session` file or session name. |
| `SIGNAL_BOT_USERNAME` | `po_broker_bot` | The Telegram bot to read from. |

---

## Technical Analysis Signals

All signals consume an `o/h/l/c/v` time-indexed DataFrame from `data/candles.py`.

| Signal | Weight | CALL trigger | PUT trigger |
|---|---|---|---|
| RSI | 0.20 | RSI < 30 (oversold) | RSI > 70 (overbought) |
| MACD | 0.20 | MACD crosses above signal | MACD crosses below signal |
| Bollinger | 0.20 | Price at lower band + reverting | Price at upper band + reverting |
| EMA Cross | 0.15 | Fast EMA crosses above slow EMA | Fast EMA crosses below slow EMA |
| Candle Patterns | 0.25 | Bullish engulfing / hammer | Bearish engulfing / shooting star |

**Confluence rule (updated 2026-06-09):** the trade decision is now gated on **MACD + EMA
only** (`decision_signals`) — both must agree on the same direction. RSI, Bollinger, and
CandlePattern are still evaluated and recorded in the decision log for research, but they no
longer affect whether a trade is taken. Data over ~410 trades showed only MACD/EMA carry a
positive edge and that 3-signal agreement won *less* than 2-signal. See
[`docs/signal-strategy-research.md`](docs/signal-strategy-research.md) for the full analysis
and the candidate signals (ADX, ATR, Supertrend, …) queued for testing.

---

## Decision Logic

Each cycle produces a `DecisionRow` appended to `data/decisions.jsonl`:

```
TRADE  → bot direction matches our TA direction + both gates pass
SKIP   → one of: no_direction · ta_disagree · ta_low_score · risk_blocked
```

**Confidence** (logged, not gated) — stored as `combined_probability`, shown in the
dashboard as **confidence** (it is a heuristic score, not a calibrated probability):
```
confidence = (bot_win_rate + our_confluence_score) / 2
```

A learned, calibrated `P(win)` is also recorded per trade as `calibrated_probability`
when a model exists — see [Research & Calibration](#research--calibration). It is
display/diagnostic only and never influences trade decisions.

---

## Decision Log (`data/decisions.jsonl`)

One JSON line per evaluated signal. Key fields:

```json
{
  "cycle_id": "20260605T042310-0001",
  "pair_raw": "GBP/USD",
  "pair_api": "GBPUSD",
  "bot_win_rate": 0.90,
  "bot_direction": "CALL",
  "our_direction": "CALL",
  "our_confluence_score": 0.78,
  "agreement": true,
  "combined_probability": 0.84,
  "calibrated_probability": 0.61,
  "decision": "TRADE",
  "skip_reason": null,
  "shadow": false,
  "would_skip_reason": null,
  "stake": 1.5,
  "trade_id": "trade_abc123",
  "outcome": "WIN",
  "pnl": 1.28,
  "pnl_currency": "USD",
  "balance_before": 1000.0,
  "balance_after": 1001.28,
  "ts": "2026-06-05T04:23:10.000000+00:00"
}
```

Use this log to calibrate signal quality, tune gates, and identify which pairs perform well over time.

---

## Research & Calibration

Tooling for understanding *why* trades win or lose and for improving the signal stack.

### Signal-attribution report

```bash
python scripts/analyze_signals.py            # full report
python scripts/analyze_signals.py --min-n 30 # raise the min sample for flags
```

Read-only analysis over `data/decisions.jsonl`. For resolved trades it reports, per
signal, the win rate when the signal **agrees / is neutral / opposes** the traded
direction (with Wilson CIs and lift), confluence-score and agreement-count buckets,
per-pair win rates, the break-even edge vs observed payouts, and a censoring summary.
It flags signals that hurt when they agree, look inverted (opposing beats base), or
never fire. When shadow data exists it also breaks outcomes down by `would_skip_reason`.

### Probability calibrator

A learned win-probability model (L2 logistic regression) that records a real
`calibrated_probability` alongside the heuristic `confidence`.

```bash
python -m strategy.train_calibrator   # train from decisions.jsonl → data/models/
```

- `strategy/probability_calibrator.py` — model + graceful fallback to the heuristic
  mean when no model/sklearn is present (never raises).
- **Decision-inert:** the calibrated value is display/diagnostic only; `decide()`, the
  EV gate, and risk sizing are unaffected.
- Model artifacts in `data/models/` are gitignored (regenerable). Retrain as data grows.

> The model is only as good as the data. On the first ~300 trades it sits near
> AUC 0.53 (no better than the average) — keep it dormant until the dataset is larger.

### Building an uncensored dataset (shadow mode)

The decision log is **censored**: outcomes only exist for trades that passed every
gate, so the disagreement cases needed to calibrate signals are never observed. Enable
`SHADOW_RECORD_MODE=true` (DEMO only) to trade and record the would-be-skipped cases:

```bash
# .env
TRADE_MODE=DEMO
SHADOW_RECORD_MODE=true
```

The bot then places bot-direction trades it would normally skip (`no_direction`,
`ta_disagree`, `negative_ev`, `risk_blocked`), tags them `shadow=true` with the
`would_skip_reason`, and records outcomes — **without** feeding the production
win-rate tracker or risk stats. Let it run, then re-run `analyze_signals.py` to see
which gates actually earn their keep.

---

## Safety Invariants

These must **never** be weakened without explicit intent:

1. **DEMO by default.** `TRADE_MODE=DEMO` is the hard default. Even an empty `TRADE_MODE=` env var resets to DEMO.
2. **Demo guard.** Before any real buy, `broker/po_api.py` decodes `isDemo` from the SSID using the API-native `is_demo()` method (with SSID-string fallback). If SSID is live but `TRADE_MODE=DEMO`, the trade is **aborted**.
3. **DRY_RUN.** When `DRY_RUN=true`, `buy/sell` logs the would-be trade and returns without calling the API.
4. **Navigator never clicks amount buttons.** The only safe action is clicking pair names, "Start Autotrade", "Main Menu", and "Trade Anyway" nag buttons. Clicking an amount/stake button places a **martingale bot trade** with the bot's own tokens — our trades go through the PocketOption API exclusively.
5. **Single session writer.** Only one process may use the Telethon session at a time. Ensure `telebot/scripts/pocket_robot_trader.py` is stopped before running `main_v2.py`.

---

## Data Files

| Path | Description |
|---|---|
| `data/decisions.jsonl` | Structured log: one row per evaluated signal |
| `data/win_rates.json` | Per-pair win rate tracker (persisted) |
| `data/trades.jsonl` | Legacy trade log (kept for compatibility) |
| `logs/bot.log` | Human-readable rotating log (1 day, 7-day retention) |

---

## Testing

All 100 tests run fully offline — no network, no SSID, no Telegram credentials.

```bash
pytest                    # all tests
pytest tests/ -v          # verbose
pytest tests/test_signals.py  # one module
```

For a live smoke test against the real bot (no trade placed):

```bash
python3 tools/v2_smoke.py
python3 tools/v2_smoke.py --pair GBPUSD_otc   # skip navigation, test TA only
```

---

## Development Notes

- All live-path code is `async/await`. Errors are caught per-iteration and logged; the bot never crashes on a single bad cycle.
- Frozen dataclasses are used for immutable results (`TelegramSignal`, `SignalResult`, `ConfluenceResult`, `DirectionScreen`, `PredictionScreen`). Mutable state lives in `RiskManager`, `WinRateTracker`, and the API client.
- Direction is always the string `"CALL"`, `"PUT"`, or `None` — never booleans or enums.
- Imports are absolute from project root.
- `pandas-ta` is **not** used (incompatible with newer Python). All indicators are pure pandas/numpy.

---

## Progression Path

| Phase | Config | Purpose |
|---|---|---|
| Smoke test | `DRY_RUN=true` | Verify navigation + TA works end-to-end |
| Capture mode | `PAIR_SELECT_MIN_WIN_RATE=0.0`, `DRY_RUN=true` | Observe all signals, log everything |
| Gated testing | `PAIR_SELECT_MIN_WIN_RATE=0.82`, `DRY_RUN=true` | Verify gate logic against real signals |
| Demo live | `TRADE_MODE=DEMO`, `DRY_RUN=false` | Real trades on demo account |
| Live | `TRADE_MODE=LIVE`, `DRY_RUN=false` | Only after sustained demo profitability |

---

**Built with:** Python 3.12+ · Telethon · binaryoptionstoolsv2 · Pydantic · Loguru · pandas/numpy
