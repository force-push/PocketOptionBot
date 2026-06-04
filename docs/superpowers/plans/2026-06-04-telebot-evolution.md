# PocketOptionBot — Telebot Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the `po_broker_bot` interaction from Telebot's button-clicking autotrader into a system that reads the bot's pair + direction signals, confirms them with our own technical analysis on PocketOption candle data, and places independent trades via the PocketOption API — logging everything for win-rate learning.

**Architecture:** A Telethon **Navigator** drives the bot UI exactly like Telebot (`/start` → Start Autotrade → pick pair → "Trade Anyway" → direction screen). At the direction screen, instead of clicking an amount button, we parse the bot's `Direction: BUY/SELL` + indicator rundown, run our **ConfluenceEngine** on the pair's live candles (fetched via the PocketOption API), and **only if our direction agrees** do we place a $1.50 trade through `binaryoptionstoolsv2`, await `check_win`, and record the outcome. Pure parsing/decision logic is split from Telethon/API I/O so the brain is unit-testable.

**Tech Stack:** Python 3.14, Telethon (MTProto user session), `binaryoptionstoolsv2` 0.2.11 (Rust/PyO3 PocketOption API), pandas/numpy (hand-rolled TA), pydantic-settings, loguru, pytest + pytest-asyncio.

---

## 1. Context & Discoveries (read before implementing)

This plan supersedes the original `PLAN.md` assumption that `po_broker_bot` emits a CALL/PUT signal in one text message. **It does not.** The real flow was captured live on 2026-06-04.

### 1.1 The real `po_broker_bot` flow (verified from live screens)

```
/start → Main menu
   "🟠 Trading mode: DEMO 🟠 … 💰 Real Balance: 487.18 AUD … 💎 Available Tokens: 4 … Start Autotrade"
   [btn: 🚀 Start Autotrade]
        │
        ▼
Prediction message
   "📊 Bot Prediction:
    Highest chance to win right now:
    **🏆 AUD/USD OTC: Win rate ≈78%**
    ✅CHF/JPY OTC: Win rate ≈70%
    ✅USD/EGP OTC: Win rate ≈77%
    ✅IRR/USD OTC: Win rate ≈59%
    🚀 Make your choice below"
   → choose the 🏆 top pair whose win% ≥ threshold; click its button
        │
        ▼
Low-tokens NAG (interstitial — appears most cycles)
   "⚡ Tokens running low … you can trade anyway …"
   [btns: 🚀 Trade Anyway | Get Tokens | ⬅️ Main Menu | 💬 Message Victor]
   → click "🚀 Trade Anyway"
        │
        ▼
DIRECTION + stake screen (image with caption)
   "🟢 Strong Bullish Setup Detected
    **MACD** confirms upward momentum, with **RSI** clear of overbought levels.
    **Direction:** 🟢 BUY
    Select trade amount"
   [amount buttons render here]
   → Telebot clicks an amount. WE DO NOT. We parse direction + run our TA + trade via API.
```

### 1.2 Locked parse specs (from real captures)

| Field | Source screen | Pattern / rule |
|---|---|---|
| Pairs + win% | prediction | `🏆 (PAIR) OTC: Win rate ≈(NN)%` = top pick; `✅(PAIR)…: Win rate ≈(NN)%` = others |
| Direction | direction caption | `Direction:` … `(BUY\|SELL)` → **BUY = CALL, SELL = PUT** |
| Setup label | direction caption | `Strong Bullish Setup` / `Strong Bearish Setup` |
| Bot indicators | direction caption | always names **MACD** and **RSI** in prose (momentum / overbought-oversold) |
| Nag dismiss | nag screen | button text contains `Trade Anyway` |
| Account mode | main menu | `Trading mode: DEMO`; `Real Balance: N AUD`; `Demo Balance: N USD`; `Available Tokens: N` |

Real fixtures (use verbatim in tests):

- **Prediction:** `"📊 Bot Prediction: \n\nHighest chance to win right now:\n\n**🏆 AUD/USD OTC: Win rate ≈78%**\n✅CHF/JPY OTC: Win rate ≈70%\n✅USD/EGP OTC: Win rate ≈77%\n✅IRR/USD OTC: Win rate ≈59%\n\n🚀 Make your choice below"`
- **Direction BUY:** `"🟢 **Strong Bullish Setup Detected**\n\n**MACD** confirms upward momentum, with **RSI** clear of overbought levels. \n\n**Direction:** 🟢 BUY\n\nSelect trade amount"`
- **Direction SELL:** `"🔴 Strong Bearish Setup Detected\n\nMACD signals downward momentum, with RSI showing no oversold conditions.\n\nDirection: 🔴 SELL"`
- **Nag:** `"⚡ **Tokens running low** Your Tokens are low - you can **trade anyway**…"` buttons `[['🚀 Trade Anyway', 'Get Tokens'], ['⬅️ Main Menu', '💬 Message Victor']]`

### 1.3 The critical domain insight (why P&L ≠ win rate)

`po_broker_bot` runs **martingale** (stake-doubling steps), which inflates its reported win rate to 93–100% while several pairs are net-**negative** in realized AUD. Telebot's `config/pair_learnings.json` proves it (EUR/USD: 95.3% win, **−49 AUD**, blocked; AUD/USD: 94.9% win, **+11 AUD**, preferred). **PocketOptionBot places single, non-martingale API trades**, so there is no recovery ladder — our directional accuracy is the entire edge, and binary payout math (~92% payout → break-even ≈ 52% win) governs profitability. **Realized P&L is the success metric, not win rate.**

### 1.4 What already exists in the codebase (reuse, don't rebuild)

- `broker/po_api.py` — `PocketOptionAPIClient` with `connect/buy/sell/check_win/balance/get_candles`, **demo guard** (SSID `isDemo` vs `TRADE_MODE`, fail-closed), and **DRY_RUN**. ✅ Solid. (Upgrade opportunity: the live lib also exposes `is_demo()`, `is_ssid_valid()`, `payout()` — see Task 12.)
- `signals/` — `BaseSignal` + 5 signals (RSI .20, MACD .20, Bollinger .20, EMA_Cross .15, CandlePattern .25) consuming a `o/h/l/c/v` time-indexed DataFrame. ✅
- `signals/confluence.py` — `ConfluenceEngine.score(df) -> ConfluenceResult(direction, score, breakdown, reason)`; **already fixed** to require ≥3 signals on the *same* side (commit `d0058c1`). ✅
- `data/candles.py` — `candles_to_df()` adapter (API candle dicts → DataFrame). ✅
- `strategy/win_rate.py` — `WinRateTracker` (per pair/direction/expiry bucket, persisted JSON, cold-start aware). ✅
- `strategy/risk.py` — `RiskManager.is_allowed()/record_trade()` (balance, trades/hr, daily loss, cooldown). ✅
- `telegram_feed/parser.py` — `_PAIR_MAP` normalization table + `parse_signal`. **Partially reusable** (normalization), but `parse_signal`'s single-message direction assumption is obsolete.
- `tests/` — 74 passing tests.

### 1.5 What is wrong / missing (this plan fixes)

1. **No navigator.** Current `telegram_feed/client.py` only *reads* a passive queue; the real flow needs active button-driving. → Task 6.
2. **Direction is parsed from the wrong screen.** `parser.py`/`signal_gate.py` Gate 1 assume direction + win% live in one message. → split parsers, Tasks 1–2.
3. **Pair normalization is table-only** and misses live pairs (KES/USD, SAR/CNY, IRR/USD, OMR/CNY, MAD/USD…). → generic normalizer, Task 3.
4. **Bug in `signal_gate.py`**: `log.debug("Gate 1 PASS: stated win rate %.1%", …)` — `%.1%` is not a valid loguru `{}`-style placeholder; the value is dropped and the literal is malformed. → fixed when Gate logic is replaced (Task 8) / Task 13 cleanup.
5. **No expiry/timeframe selection.** PO supports 5s/10s/15s/30s/1m/…; the bot trades 30s. → Task 4.
6. **No learning log.** We must record signals, probabilities, agreement, and outcomes in one structured row. → Task 5 + Task 9.
7. **82% gate** must be configurable and **temporarily disabled during capture/testing**, re-enabled for real runs. → Task 7 (`SignalGate` win% gate driven by `settings.min_channel_win_rate`, plus a `settings.pair_select_min_win_rate` for navigation).

---

## 2. Target Architecture & File Structure

```
PocketOptionBot/
├── telegram_feed/
│   ├── prediction_parser.py   NEW  parse prediction → PredictionScreen(pairs[], top)
│   ├── direction_parser.py    NEW  parse direction caption → DirectionScreen(direction, indicators, setup)
│   ├── pair_norm.py           NEW  generic PAIR/QUOTE [OTC] → API symbol normalizer
│   ├── navigator.py           NEW  Telethon button-driver (I/O); reaches the direction screen
│   └── parser.py              KEEP normalization table reused by pair_norm fallback
├── strategy/
│   ├── decision.py            NEW  pure agreement + combined-probability logic
│   ├── expiry.py              NEW  pure expiry/timeframe selection
│   ├── trade_logger.py        NEW  structured per-evaluation learning row → data/decisions.jsonl
│   ├── manager_v2.py          NEW  orchestrates Navigator → parse → TA → decide → API → record
│   ├── signal_gate.py         MODIFY  win% gate configurable; fix format bug
│   ├── win_rate.py            KEEP
│   └── risk.py                KEEP
├── broker/po_api.py           MODIFY  add is_demo()/is_ssid_valid() guard upgrade (Task 12)
├── config/settings.py         MODIFY  add expiry, pair_select_min_win_rate, stake, nag toggle
├── main_v2.py                 NEW  entrypoint wiring the v2 pipeline
├── analysis/                  NEW (Phase 3)  notebooks/scripts over data/decisions.jsonl
└── ui/                        NEW (Phase 4)  professional dashboard
```

**Design rule:** every file with `_parser`, `decision`, `expiry`, `pair_norm` is **pure** (no I/O) and fully unit-tested. `navigator.py`, `manager_v2.py`, `po_api.py` hold the I/O and are exercised by an integration script + manual demo runs.

---

## 3. Learning Log Schema (`data/decisions.jsonl`)

One JSON object per *evaluated* signal (whether traded or skipped). This is the dataset Phase 3 learns from.

```json
{
  "ts": "2026-06-04T20:41:00Z",
  "cycle_id": "20260604T204100-0007",
  "pair_raw": "AUD/USD OTC",
  "pair_api": "AUDUSD_otc",
  "bot_win_rate": 0.78,
  "bot_is_top_pick": true,
  "bot_direction": "CALL",
  "bot_setup": "bullish",
  "bot_indicators_raw": "MACD confirms upward momentum, with RSI clear of overbought levels.",
  "our_direction": "CALL",
  "our_confluence_score": 0.81,
  "our_signal_breakdown": {"RSI": ["CALL", 0.7], "MACD": ["CALL", 0.9], "Bollinger": [null, 0.0], "EMA_Cross": ["CALL", 0.6], "CandlePattern": [null, 0.0]},
  "agreement": true,
  "combined_probability": 0.795,
  "expiry_seconds": 30,
  "decision": "TRADE",
  "skip_reason": null,
  "stake": 1.5,
  "trade_id": "abc123",
  "status": "PENDING",
  "outcome": "win",
  "pnl": 1.38,
  "pnl_currency": "USD",
  "balance_before": 48592.71,
  "balance_after": 48594.09
}
```

`decision ∈ {TRADE, SKIP}`. `skip_reason ∈ {below_win_gate, no_direction, ta_disagree, ta_low_score, risk_blocked, no_candles, api_error}`. Outcome fields are backfilled after `check_win` resolves.

---

## 4. Phase 1 — End-to-End Trade Loop (detailed, TDD)

Phase 1 delivers: navigate → parse prediction → pick pair → dismiss nag → parse direction → fetch candles → run our TA → agree? → place $1.50 demo trade → check_win → log everything. Stake fixed at **$1.50**, default expiry **30s**, `TRADE_MODE=DEMO`, `DRY_RUN=true` until the pipe is proven, then `DRY_RUN=false` on demo.

> All commands run from repo root with the project venv: `.venv/bin/python -m pytest …`.

---

### Task 1: Prediction parser

**Files:**
- Create: `telegram_feed/prediction_parser.py`
- Test: `tests/test_prediction_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prediction_parser.py
from telegram_feed.prediction_parser import parse_prediction, PredictionScreen, PairPrediction

PRED = ("📊 Bot Prediction: \n\nHighest chance to win right now:\n\n"
        "**🏆 AUD/USD OTC: Win rate ≈78%**\n"
        "✅CHF/JPY OTC: Win rate ≈70%\n"
        "✅USD/EGP OTC: Win rate ≈77%\n"
        "✅IRR/USD OTC: Win rate ≈59%\n\n🚀 Make your choice below")

def test_parses_all_pairs():
    scr = parse_prediction(PRED)
    assert isinstance(scr, PredictionScreen)
    assert [p.pair_raw for p in scr.pairs] == [
        "AUD/USD OTC", "CHF/JPY OTC", "USD/EGP OTC", "IRR/USD OTC"]
    assert scr.pairs[0].win_rate == 0.78
    assert scr.pairs[0].is_top is True
    assert scr.pairs[1].is_top is False

def test_top_pick_helper():
    scr = parse_prediction(PRED)
    assert scr.top_pick().pair_raw == "AUD/USD OTC"

def test_non_prediction_returns_none():
    assert parse_prediction("🟢 Strong Bullish Setup Detected") is None
    assert parse_prediction("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_prediction_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: telegram_feed.prediction_parser`

- [ ] **Step 3: Write minimal implementation**

```python
# telegram_feed/prediction_parser.py
"""Parse a po_broker_bot 'Bot Prediction' message into pairs + win rates."""
from __future__ import annotations

import re
from dataclasses import dataclass

_LINE_RE = re.compile(r"([A-Z]{2,5}/[A-Z]{2,5}(?:\s+OTC)?)\s*:\s*Win rate\s*[≈~]?\s*(\d+)%", re.IGNORECASE)
_TOP_RE = re.compile(r"🏆")


@dataclass(frozen=True)
class PairPrediction:
    pair_raw: str
    win_rate: float  # 0.0–1.0
    is_top: bool


@dataclass(frozen=True)
class PredictionScreen:
    pairs: tuple[PairPrediction, ...]

    def top_pick(self) -> PairPrediction | None:
        for p in self.pairs:
            if p.is_top:
                return p
        return self.pairs[0] if self.pairs else None


def parse_prediction(text: str) -> PredictionScreen | None:
    if not text or "bot prediction" not in text.lower():
        return None
    out: list[PairPrediction] = []
    for line in text.splitlines():
        m = _LINE_RE.search(line)
        if not m:
            continue
        out.append(PairPrediction(
            pair_raw=m.group(1).strip().upper().replace("  ", " "),
            win_rate=float(m.group(2)) / 100.0,
            is_top=bool(_TOP_RE.search(line)),
        ))
    return PredictionScreen(pairs=tuple(out)) if out else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_prediction_parser.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add telegram_feed/prediction_parser.py tests/test_prediction_parser.py
git commit -m "feat: prediction parser for po_broker_bot pair/win-rate screen"
```

---

### Task 2: Direction-screen parser

**Files:**
- Create: `telegram_feed/direction_parser.py`
- Test: `tests/test_direction_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_direction_parser.py
from telegram_feed.direction_parser import parse_direction_screen, DirectionScreen

BUY = ("🟢 **Strong Bullish Setup Detected**\n\n"
       "**MACD** confirms upward momentum, with **RSI** clear of overbought levels. \n\n"
       "**Direction:** 🟢 BUY\n\nSelect trade amount")
SELL = ("🔴 Strong Bearish Setup Detected\n\n"
        "MACD signals downward momentum, with RSI showing no oversold conditions.\n\n"
        "Direction: 🔴 SELL")

def test_buy_maps_to_call():
    d = parse_direction_screen(BUY)
    assert isinstance(d, DirectionScreen)
    assert d.direction == "CALL"
    assert d.setup == "bullish"
    assert "MACD" in d.indicators_raw and "RSI" in d.indicators_raw

def test_sell_maps_to_put():
    d = parse_direction_screen(SELL)
    assert d.direction == "PUT"
    assert d.setup == "bearish"

def test_non_direction_returns_none():
    assert parse_direction_screen("📊 Bot Prediction: …") is None
    assert parse_direction_screen("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_direction_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# telegram_feed/direction_parser.py
"""Parse the post-pair-selection direction/stake screen caption."""
from __future__ import annotations

import re
from dataclasses import dataclass

_DIR_RE = re.compile(r"direction\s*[:\-]?\s*[^A-Za-z]*(buy|sell)", re.IGNORECASE | re.DOTALL)
_BULL_RE = re.compile(r"bullish", re.IGNORECASE)
_BEAR_RE = re.compile(r"bearish", re.IGNORECASE)
_IND_RE = re.compile(r"(MACD|RSI|EMA|Bollinger|momentum|overbought|oversold)", re.IGNORECASE)


@dataclass(frozen=True)
class DirectionScreen:
    direction: str          # "CALL" or "PUT"
    setup: str              # "bullish" | "bearish" | "unknown"
    indicators_raw: str     # the prose line naming the bot's indicators


def parse_direction_screen(text: str) -> DirectionScreen | None:
    if not text:
        return None
    m = _DIR_RE.search(text)
    if not m:
        return None
    word = m.group(1).lower()
    direction = "CALL" if word == "buy" else "PUT"
    setup = "bullish" if _BULL_RE.search(text) else "bearish" if _BEAR_RE.search(text) else "unknown"
    # indicator prose = lines mentioning indicator keywords (excluding the Direction line)
    ind_lines = [ln.strip() for ln in text.splitlines()
                 if _IND_RE.search(ln) and "direction" not in ln.lower()]
    return DirectionScreen(direction=direction, setup=setup,
                           indicators_raw=" ".join(ind_lines).strip())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_direction_parser.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add telegram_feed/direction_parser.py tests/test_direction_parser.py
git commit -m "feat: direction-screen parser (BUY/SELL → CALL/PUT + indicator prose)"
```

---

### Task 3: Generic pair normalizer

**Files:**
- Create: `telegram_feed/pair_norm.py`
- Test: `tests/test_pair_norm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pair_norm.py
from telegram_feed.pair_norm import normalize_pair

def test_known_table_pairs():
    assert normalize_pair("AUD/USD OTC") == "AUDUSD_otc"
    assert normalize_pair("EUR/USD") == "EURUSD"

def test_generic_otc_pairs_not_in_table():
    # pairs that appear live but aren't in the legacy table
    assert normalize_pair("KES/USD OTC") == "KESUSD_otc"
    assert normalize_pair("SAR/CNY OTC") == "SARCNY_otc"
    assert normalize_pair("IRR/USD OTC") == "IRRUSD_otc"
    assert normalize_pair("OMR/CNY OTC") == "OMRCNY_otc"

def test_non_otc_generic():
    assert normalize_pair("MAD/USD") == "MADUSD"

def test_garbage_returns_none():
    assert normalize_pair("Start Autotrade") is None
    assert normalize_pair("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pair_norm.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# telegram_feed/pair_norm.py
"""Normalize a displayed pair label to a PocketOption API symbol.

Strategy: try the legacy explicit table first (telegram_feed.parser._PAIR_MAP);
otherwise apply the generic rule  XXX/YYY [OTC] -> XXXYYY[_otc].
"""
from __future__ import annotations

import re

from telegram_feed.parser import _PAIR_MAP  # reuse the curated table

_GENERIC_RE = re.compile(r"\b([A-Z]{2,5})\s*/\s*([A-Z]{2,5})\b(\s+OTC)?", re.IGNORECASE)


def normalize_pair(label: str) -> str | None:
    if not label:
        return None
    key = label.strip().upper()
    if key in _PAIR_MAP:
        return _PAIR_MAP[key]
    m = _GENERIC_RE.search(key)
    if not m:
        return None
    base, quote, otc = m.group(1).upper(), m.group(2).upper(), m.group(3)
    symbol = f"{base}{quote}"
    return f"{symbol}_otc" if otc else symbol
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pair_norm.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add telegram_feed/pair_norm.py tests/test_pair_norm.py
git commit -m "feat: generic pair normalizer with legacy-table fallback"
```

---

### Task 4: Expiry / timeframe selection (pure)

**Files:**
- Create: `strategy/expiry.py`
- Test: `tests/test_expiry.py`
- Modify: `config/settings.py` (add fields — see Task 7; this task assumes `settings.default_expiry_seconds` and `settings.allowed_expiries` exist)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_expiry.py
from strategy.expiry import select_expiry

ALLOWED = (5, 10, 15, 30, 60, 120, 300)

def test_defaults_to_configured_when_no_hint():
    assert select_expiry(default=30, allowed=ALLOWED) == 30

def test_snaps_requested_to_nearest_allowed():
    assert select_expiry(default=30, allowed=ALLOWED, requested=45) == 30  # nearest of 30/60 → 30
    assert select_expiry(default=30, allowed=ALLOWED, requested=12) == 10

def test_rejects_when_disallowed_and_no_default_match():
    # default itself must be in allowed; guard returns default if requested invalid
    assert select_expiry(default=60, allowed=ALLOWED, requested=99999) == 300  # nearest
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_expiry.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# strategy/expiry.py
"""Pure expiry/timeframe selection. PocketOption supports 5s/10s/15s/30s/1m/…"""
from __future__ import annotations


def select_expiry(default: int, allowed: tuple[int, ...], requested: int | None = None) -> int:
    """Return a valid expiry in seconds.

    If `requested` is given, snap it to the nearest allowed value; otherwise
    return `default` (which must itself be an allowed value).
    """
    if requested is None:
        return default
    return min(allowed, key=lambda a: abs(a - requested))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_expiry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add strategy/expiry.py tests/test_expiry.py
git commit -m "feat: pure expiry/timeframe selection with nearest-allowed snapping"
```

---

### Task 5: Decision logic — agreement + combined probability (pure)

**Files:**
- Create: `strategy/decision.py`
- Test: `tests/test_decision.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decision.py
from strategy.decision import decide, Decision

def test_agreement_trade():
    d = decide(bot_direction="CALL", our_direction="CALL",
               bot_win_rate=0.78, our_confluence=0.80,
               our_score_floor=0.0)
    assert isinstance(d, Decision)
    assert d.trade is True
    assert d.skip_reason is None
    # combined probability is the mean of the two sources by default
    assert abs(d.combined_probability - 0.79) < 1e-9

def test_disagreement_skips():
    d = decide(bot_direction="CALL", our_direction="PUT",
               bot_win_rate=0.78, our_confluence=0.80, our_score_floor=0.0)
    assert d.trade is False
    assert d.skip_reason == "ta_disagree"

def test_no_our_direction_skips():
    d = decide(bot_direction="CALL", our_direction=None,
               bot_win_rate=0.78, our_confluence=0.0, our_score_floor=0.0)
    assert d.trade is False
    assert d.skip_reason == "no_direction"

def test_low_confluence_skips():
    d = decide(bot_direction="CALL", our_direction="CALL",
               bot_win_rate=0.78, our_confluence=0.40, our_score_floor=0.75)
    assert d.trade is False
    assert d.skip_reason == "ta_low_score"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_decision.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# strategy/decision.py
"""Pure trade decision: require our TA to agree with the bot, combine into P(win).

Phase 1 keeps the combiner simple (mean of bot win-rate and our confluence) and
LOGS the components so Phase 3 can calibrate a better model from real outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    trade: bool
    combined_probability: float
    skip_reason: str | None


def decide(
    bot_direction: str,
    our_direction: str | None,
    bot_win_rate: float,
    our_confluence: float,
    our_score_floor: float,
) -> Decision:
    if our_direction is None:
        return Decision(False, 0.0, "no_direction")
    if our_direction != bot_direction:
        return Decision(False, 0.0, "ta_disagree")
    if our_confluence < our_score_floor:
        return Decision(False, (bot_win_rate + our_confluence) / 2.0, "ta_low_score")
    combined = (bot_win_rate + our_confluence) / 2.0
    return Decision(True, combined, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_decision.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add strategy/decision.py tests/test_decision.py
git commit -m "feat: pure agreement + combined-probability decision logic"
```

---

### Task 6: Learning log writer

**Files:**
- Create: `strategy/trade_logger.py`
- Test: `tests/test_trade_logger.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_logger.py
import json
from strategy.trade_logger import DecisionRow, write_decision, backfill_outcome

def test_write_and_read_row(tmp_path):
    path = tmp_path / "decisions.jsonl"
    row = DecisionRow(
        cycle_id="c1", pair_raw="AUD/USD OTC", pair_api="AUDUSD_otc",
        bot_win_rate=0.78, bot_is_top_pick=True, bot_direction="CALL",
        bot_setup="bullish", bot_indicators_raw="MACD/RSI",
        our_direction="CALL", our_confluence_score=0.81,
        our_signal_breakdown={"RSI": ["CALL", 0.7]},
        agreement=True, combined_probability=0.795, expiry_seconds=30,
        decision="TRADE", skip_reason=None, stake=1.5,
    )
    write_decision(path, row)
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["pair_api"] == "AUDUSD_otc"
    assert rec["decision"] == "TRADE"
    assert rec["ts"].endswith("Z") or "T" in rec["ts"]

def test_backfill_outcome(tmp_path):
    path = tmp_path / "decisions.jsonl"
    row = DecisionRow(cycle_id="c2", pair_raw="X", pair_api="X", bot_win_rate=0.8,
                      bot_is_top_pick=True, bot_direction="CALL", bot_setup="bullish",
                      bot_indicators_raw="", our_direction="CALL", our_confluence_score=0.8,
                      our_signal_breakdown={}, agreement=True, combined_probability=0.8,
                      expiry_seconds=30, decision="TRADE", skip_reason=None, stake=1.5,
                      trade_id="tid9")
    write_decision(path, row)
    backfill_outcome(path, trade_id="tid9", outcome="win", pnl=1.38,
                     balance_before=100.0, balance_after=101.38, pnl_currency="USD")
    rec = json.loads(path.read_text().strip().splitlines()[-1])
    assert rec["outcome"] == "win"
    assert rec["pnl"] == 1.38
    assert rec["balance_after"] == 101.38
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_trade_logger.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# strategy/trade_logger.py
"""Append/backfill structured decision rows to data/decisions.jsonl for learning."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class DecisionRow:
    cycle_id: str
    pair_raw: str
    pair_api: str
    bot_win_rate: float
    bot_is_top_pick: bool
    bot_direction: str
    bot_setup: str
    bot_indicators_raw: str
    our_direction: str | None
    our_confluence_score: float
    our_signal_breakdown: dict[str, Any]
    agreement: bool
    combined_probability: float
    expiry_seconds: int
    decision: str               # "TRADE" | "SKIP"
    skip_reason: str | None
    stake: float
    trade_id: str | None = None
    status: str = "PENDING"
    outcome: str | None = None  # "win" | "loss" | "draw"
    pnl: float | None = None
    pnl_currency: str | None = None
    balance_before: float | None = None
    balance_after: float | None = None
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def write_decision(path: str | Path, row: DecisionRow) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(row), default=str, ensure_ascii=False) + "\n")


def backfill_outcome(path: str | Path, trade_id: str, outcome: str, pnl: float,
                     balance_before: float | None = None, balance_after: float | None = None,
                     pnl_currency: str | None = None) -> bool:
    """Rewrite the row whose trade_id matches, filling outcome fields. Returns True if found."""
    p = Path(path)
    if not p.exists():
        return False
    rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    found = False
    for rec in rows:
        if rec.get("trade_id") == trade_id:
            rec.update(status=outcome.upper(), outcome=outcome, pnl=pnl,
                       balance_before=balance_before, balance_after=balance_after,
                       pnl_currency=pnl_currency)
            found = True
    if found:
        with p.open("w", encoding="utf-8") as fh:
            for rec in rows:
                fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    return found
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_trade_logger.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add strategy/trade_logger.py tests/test_trade_logger.py
git commit -m "feat: structured decision/learning log writer + outcome backfill"
```

---

### Task 7: Settings for v2 (expiry, stake, win gate, nag toggle)

**Files:**
- Modify: `config/settings.py`
- Test: `tests/test_settings_v2.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings_v2.py
from config.settings import settings

def test_v2_defaults_exist():
    assert settings.stake_amount == 1.5
    assert settings.default_expiry_seconds == 30
    assert 30 in settings.allowed_expiries
    # win gate for navigation pair-selection (the "82%" knob) — DISABLED during testing
    assert hasattr(settings, "pair_select_min_win_rate")
    assert settings.click_trade_anyway is True
    assert settings.decisions_log_path.endswith("decisions.jsonl")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_v2.py -v`
Expected: FAIL — `AttributeError: 'BotSettings' object has no attribute 'stake_amount'`

- [ ] **Step 3: Write minimal implementation** — add to `BotSettings` in `config/settings.py`:

```python
    # ── v2 (Telebot evolution) ──
    stake_amount: float = Field(default=1.5, alias="STAKE_AMOUNT", gt=0)
    default_expiry_seconds: int = Field(default=30, alias="DEFAULT_EXPIRY_SECONDS", gt=0)
    allowed_expiries: tuple[int, ...] = (5, 10, 15, 30, 60, 120, 300)
    # Navigation pair-selection gate. Set to 0.0 to DISABLE during capture/testing;
    # restore to 0.82 for real runs (the "82%" rule).
    pair_select_min_win_rate: float = Field(default=0.0, alias="PAIR_SELECT_MIN_WIN_RATE", ge=0.0, le=1.0)
    click_trade_anyway: bool = Field(default=True, alias="CLICK_TRADE_ANYWAY")
    decisions_log_path: str = Field(default="data/decisions.jsonl", alias="DECISIONS_LOG_PATH")
```

Note: `allowed_expiries` is a fixed tuple (not env-driven) — pydantic-settings does not parse tuple env vars cleanly; keep it a class default.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings_v2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_settings_v2.py
git commit -m "feat: v2 settings (stake \$1.50, expiry, pair-select win gate, nag toggle)"
```

> **82% gate handling:** during capture/testing leave `PAIR_SELECT_MIN_WIN_RATE=0.0` (disabled — no trades happen, we only navigate). Before real demo trading, set `PAIR_SELECT_MIN_WIN_RATE=0.82` in `.env`.

---

### Task 8: Navigator (Telethon button-driver, I/O)

**Files:**
- Create: `telegram_feed/navigator.py`
- Test: `tests/test_navigator.py` (unit-test the pure helpers with a fake client; full drive is integration-tested in Task 11)

The Navigator exposes pure-ish helpers (button matching) that are unit-tested, plus async drive methods that use Telethon. Model the fake client on Telethon's `iter_messages`/`message.click`.

- [ ] **Step 1: Write the failing test** (button-selection helpers only)

```python
# tests/test_navigator.py
from telegram_feed.navigator import find_pair_button_text, is_nag_screen, is_direction_screen

def test_find_pair_button_among_menu_buttons():
    btns = ["⬅️ Main Menu", "🏆 AUD/USD OTC ≈78%", "CHF/JPY OTC ≈70%"]
    assert find_pair_button_text(btns, "AUDUSD_otc") == "🏆 AUD/USD OTC ≈78%"

def test_is_nag_screen():
    assert is_nag_screen("⚡ Tokens running low - you can trade anyway", ["🚀 Trade Anyway"]) is True
    assert is_nag_screen("📊 Bot Prediction", []) is False

def test_is_direction_screen():
    assert is_direction_screen("Direction: 🟢 BUY  Select trade amount") is True
    assert is_direction_screen("📊 Bot Prediction") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_navigator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# telegram_feed/navigator.py
"""Drive po_broker_bot's inline-button UI to reach the direction screen.

Pure helpers (button matching / screen classification) are unit-tested.
Async `Navigator` methods perform Telethon I/O and are integration-tested.

Flow: ensure_main_menu → start_autotrade → read_prediction → select_pair
      → dismiss_nag (Trade Anyway) → read_direction_screen → back_to_menu
WE NEVER CLICK AN AMOUNT BUTTON — execution happens via the PocketOption API.
"""
from __future__ import annotations

import asyncio

from telegram_feed.pair_norm import normalize_pair
from utils.logger import log

_NAG_MARKERS = ("tokens running low", "trade anyway")
_DIR_MARKERS = ("direction:", "select trade amount", "setup detected")


def find_pair_button_text(button_texts: list[str], pair_api: str) -> str | None:
    """Return the button label whose normalized pair == pair_api (skip Main Menu)."""
    for t in button_texts:
        if "main menu" in t.lower():
            continue
        if normalize_pair(t) == pair_api:
            return t
    return None


def is_nag_screen(text: str, button_texts: list[str]) -> bool:
    low = (text or "").lower()
    if any(m in low for m in _NAG_MARKERS):
        return True
    return any("trade anyway" in (b or "").lower() for b in button_texts)


def is_direction_screen(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _DIR_MARKERS) and "bot prediction" not in low


class Navigator:
    def __init__(self, client, bot_username: str, click_trade_anyway: bool = True):
        self._c = client
        self._bot = bot_username
        self._click_anyway = click_trade_anyway

    async def _recent(self, limit=10):
        msgs = []
        async for m in self._c.iter_messages(self._bot, limit=limit):
            btns = []
            if m.buttons:
                for row in m.buttons:
                    btns.extend(b.text for b in row if b and getattr(b, "text", None))
            msgs.append((m, m.text or "", btns))
        return msgs

    async def _click(self, predicate, limit=12) -> str | None:
        async for m in self._c.iter_messages(self._bot, limit=limit):
            if not m.buttons:
                continue
            for i, row in enumerate(m.buttons):
                for j, b in enumerate(row):
                    if b and getattr(b, "text", None) and predicate(b.text):
                        try:
                            await m.click(i, j)
                            return b.text
                        except Exception as e:
                            log.debug("click failed: %s", e)
        return None

    async def start_autotrade(self) -> None:
        await self._c.send_message(self._bot, "/start")
        await asyncio.sleep(2.5)
        for label in ("🚀 Start Autotrade", "Start Autotrade", "Start Trade"):
            if await self._click(lambda x, L=label: L in x):
                await asyncio.sleep(3)
                return

    async def dismiss_nag_if_present(self) -> bool:
        if not self._click_anyway:
            return False
        for _ in range(3):
            t = await self._click(lambda x: "trade anyway" in x.lower() or "anyway" in x.lower(), limit=8)
            if t:
                await asyncio.sleep(2.5)
                return True
            await asyncio.sleep(1.0)
        return False

    async def select_pair(self, pair_api: str) -> bool:
        clicked = await self._click(lambda x: normalize_pair(x) == pair_api)
        if not clicked:
            return False
        await asyncio.sleep(2.5)
        await self.dismiss_nag_if_present()
        await asyncio.sleep(3)
        return True

    async def read_latest_text(self, limit=6) -> tuple[str, list[str]]:
        msgs = await self._recent(limit)
        if not msgs:
            return "", []
        _, text, btns = msgs[0]
        return text, btns

    async def back_to_menu(self) -> None:
        await self._click(lambda x: "main menu" in x.lower())
        await asyncio.sleep(1)
        await self._c.send_message(self._bot, "/start")
        await asyncio.sleep(2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_navigator.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add telegram_feed/navigator.py tests/test_navigator.py
git commit -m "feat: po_broker_bot navigator (button-driver) with nag handling"
```

---

### Task 9: Orchestrator `manager_v2.py`

**Files:**
- Create: `strategy/manager_v2.py`
- Test: `tests/test_manager_v2.py` (mock Navigator + API + confluence; assert one full cycle records a TRADE row and backfills the outcome)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manager_v2.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from strategy.manager_v2 import StrategyManagerV2

PRED = ("📊 Bot Prediction: \n\nHighest chance to win right now:\n\n"
        "**🏆 AUD/USD OTC: Win rate ≈78%**\n✅CHF/JPY OTC: Win rate ≈70%\n\n🚀 Make your choice below")
DIR_BUY = ("🟢 Strong Bullish Setup Detected\n\nMACD up, RSI fine.\n\nDirection: 🟢 BUY\n\nSelect trade amount")


@pytest.mark.asyncio
async def test_one_cycle_trades_and_logs(tmp_path, monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "pair_select_min_win_rate", 0.0)
    monkeypatch.setattr(settings, "min_confluence_score", 0.0)
    monkeypatch.setattr(settings, "decisions_log_path", str(tmp_path / "decisions.jsonl"))

    nav = MagicMock()
    nav.start_autotrade = AsyncMock()
    nav.read_latest_text = AsyncMock(side_effect=[(PRED, ["🏆 AUD/USD OTC", "CHF/JPY OTC"]), (DIR_BUY, [])])
    nav.select_pair = AsyncMock(return_value=True)
    nav.back_to_menu = AsyncMock()

    api = MagicMock()
    api.get_candles = AsyncMock(return_value=[{"time": i, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for i in range(60)])
    api.balance = AsyncMock(return_value=48592.71)
    trade = MagicMock(); trade.status = "PENDING"; trade.trade_id = "tid42"; trade.id = "trade_1"
    api.buy = AsyncMock(return_value=trade)
    api.sell = AsyncMock(return_value=trade)
    api.check_win = AsyncMock(return_value="win")

    conf = MagicMock()
    conf_result = MagicMock(); conf_result.direction = "CALL"; conf_result.score = 0.81
    conf_result.breakdown = {"RSI": ("CALL", 0.7)}
    conf.score = AsyncMock(return_value=conf_result)

    risk = MagicMock(); risk.is_allowed = MagicMock(return_value=True); risk.record_trade = MagicMock()
    tracker = MagicMock(); tracker.record = MagicMock()

    mgr = StrategyManagerV2(navigator=nav, api_client=api, confluence_engine=conf,
                            risk_manager=risk, tracker=tracker)
    await mgr.run_once()

    api.buy.assert_awaited_once()
    rows = [json.loads(l) for l in (tmp_path / "decisions.jsonl").read_text().splitlines()]
    assert rows[-1]["decision"] == "TRADE"
    assert rows[-1]["outcome"] == "win"
    assert rows[-1]["our_direction"] == "CALL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_manager_v2.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# strategy/manager_v2.py
"""Telebot-evolution orchestrator: navigate → parse → TA → decide → API → record."""
from __future__ import annotations

from datetime import datetime, timezone

from config.settings import settings
from data.candles import candles_to_df
from strategy.decision import decide
from strategy.expiry import select_expiry
from strategy.trade_logger import DecisionRow, write_decision, backfill_outcome
from telegram_feed.direction_parser import parse_direction_screen
from telegram_feed.pair_norm import normalize_pair
from telegram_feed.prediction_parser import parse_prediction
from utils.logger import log

_cycle_counter = 0


class StrategyManagerV2:
    def __init__(self, navigator, api_client, confluence_engine, risk_manager, tracker):
        self._nav = navigator
        self._api = api_client
        self._conf = confluence_engine
        self._risk = risk_manager
        self._tracker = tracker

    def _next_cycle_id(self) -> str:
        global _cycle_counter
        _cycle_counter += 1
        return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{_cycle_counter:04d}"

    async def run_once(self) -> None:
        cid = self._next_cycle_id()
        log_path = settings.decisions_log_path

        await self._nav.start_autotrade()
        pred_text, pred_btns = await self._nav.read_latest_text()
        pred = parse_prediction(pred_text)
        if not pred or not pred.top_pick():
            log.info("[%s] no prediction parsed; skipping", cid)
            return

        top = pred.top_pick()
        pair_api = normalize_pair(top.pair_raw)
        if pair_api is None:
            log.info("[%s] could not normalize pair %r", cid, top.pair_raw)
            return

        if top.win_rate < settings.pair_select_min_win_rate:
            log.info("[%s] %s win%% %.0f below gate %.0f — skip",
                     cid, pair_api, top.win_rate * 100, settings.pair_select_min_win_rate * 100)
            return

        if not await self._nav.select_pair(pair_api):
            log.info("[%s] pair select failed for %s", cid, pair_api)
            return

        dir_text, _ = await self._nav.read_latest_text()
        dscreen = parse_direction_screen(dir_text)
        if dscreen is None:
            log.info("[%s] no direction screen for %s", cid, pair_api)
            return

        expiry = select_expiry(settings.default_expiry_seconds, settings.allowed_expiries)
        candle_list = await self._api.get_candles(pair_api, period=expiry, count=settings.history_length)
        df = candles_to_df(candle_list)
        conf = await self._conf.score(df)

        d = decide(bot_direction=dscreen.direction, our_direction=conf.direction,
                   bot_win_rate=top.win_rate, our_confluence=conf.score,
                   our_score_floor=settings.min_confluence_score)

        balance_before = await self._api.balance()
        row = DecisionRow(
            cycle_id=cid, pair_raw=top.pair_raw, pair_api=pair_api,
            bot_win_rate=top.win_rate, bot_is_top_pick=top.is_top,
            bot_direction=dscreen.direction, bot_setup=dscreen.setup,
            bot_indicators_raw=dscreen.indicators_raw,
            our_direction=conf.direction, our_confluence_score=conf.score,
            our_signal_breakdown={k: list(v) for k, v in (conf.breakdown or {}).items()},
            agreement=(conf.direction == dscreen.direction),
            combined_probability=d.combined_probability, expiry_seconds=expiry,
            decision="TRADE" if d.trade else "SKIP", skip_reason=d.skip_reason,
            stake=settings.stake_amount, balance_before=balance_before,
        )

        if not d.trade:
            write_decision(log_path, row)
            log.info("[%s] SKIP %s: %s", cid, pair_api, d.skip_reason)
            await self._nav.back_to_menu()
            return

        if not self._risk.is_allowed(balance_before):
            row.decision = "SKIP"; row.skip_reason = "risk_blocked"
            write_decision(log_path, row)
            log.warning("[%s] risk blocked: %s", cid, getattr(self._risk, "block_reason", ""))
            await self._nav.back_to_menu()
            return

        api_call = self._api.buy if dscreen.direction == "CALL" else self._api.sell
        trade = await api_call(pair_api, settings.stake_amount, expiry)
        row.trade_id = getattr(trade, "trade_id", None)
        row.status = getattr(trade, "status", "PENDING")
        write_decision(log_path, row)
        log.info("[%s] TRADE %s %s @%.2f exp=%ds id=%s",
                 cid, dscreen.direction, pair_api, settings.stake_amount, expiry, row.trade_id)

        await self._nav.back_to_menu()

        # await outcome and backfill
        if row.trade_id:
            outcome = await self._api.check_win(row.trade_id)
            balance_after = await self._api.balance()
            pnl = (balance_after - balance_before) if (balance_after is not None and balance_before is not None) else None
            backfill_outcome(log_path, trade_id=row.trade_id, outcome=outcome,
                             pnl=pnl if pnl is not None else 0.0,
                             balance_before=balance_before, balance_after=balance_after,
                             pnl_currency="USD")
            self._tracker.record(pair_api, dscreen.direction, expiry, outcome)
            risk_result = {"win": "WIN", "loss": "LOSS", "draw": "PENDING"}.get(outcome.lower(), "PENDING")
            self._risk.record_trade(dscreen.direction, settings.stake_amount, risk_result)
            log.info("[%s] OUTCOME %s pnl=%s", cid, outcome, pnl)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_manager_v2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add strategy/manager_v2.py tests/test_manager_v2.py
git commit -m "feat: v2 orchestrator (navigate→parse→TA→decide→API→record)"
```

---

### Task 10: Entrypoint `main_v2.py`

**Files:**
- Create: `main_v2.py`
- Test: manual (integration) — no unit test; smoke-import in `tests/test_imports.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_imports.py
def test_main_v2_imports():
    import main_v2  # noqa: F401
    assert hasattr(main_v2, "main")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_imports.py -v`
Expected: FAIL — `ModuleNotFoundError: main_v2`

- [ ] **Step 3: Write minimal implementation**

```python
# main_v2.py
"""Entrypoint for the Telebot-evolution pipeline (Phase 1)."""
from __future__ import annotations

import asyncio
from pathlib import Path

from telethon import TelegramClient

from broker.po_api import PocketOptionAPIClient
from config.settings import settings, TradeMode
from signals.bollinger import BollingerSignal
from signals.candle_pattern import CandlePatternSignal
from signals.confluence import ConfluenceEngine
from signals.ema_cross import EMASignal
from signals.macd import MACDSignal
from signals.rsi import RSISignal
from strategy.manager_v2 import StrategyManagerV2
from strategy.risk import RiskManager
from strategy.win_rate import WinRateTracker
from telegram_feed.navigator import Navigator
from utils.logger import setup_logger, log


async def main(cycles: int = 1) -> None:
    setup_logger(Path(__file__).parent, level="INFO")
    log.info("PocketOptionBot v2 — mode=%s dry_run=%s stake=%.2f",
             settings.trade_mode, settings.dry_run, settings.stake_amount)
    if settings.trade_mode == TradeMode.LIVE:
        log.critical("LIVE MODE — 3s pause"); await asyncio.sleep(3)

    tg = TelegramClient(
        str(Path(settings.telegram_session).expanduser()) if getattr(settings, "telegram_session", None) else "po_v2_session",
        settings.telegram_api_id, settings.telegram_api_hash,
    )
    await tg.connect()
    if not await tg.is_user_authorized():
        log.error("Telegram session not authorized — run tools/gen_telegram_session.py"); return

    api = PocketOptionAPIClient()
    if not settings.dry_run:
        await api.connect()

    confluence = ConfluenceEngine([
        RSISignal(period=14), MACDSignal(fast=12, slow=26, signal=9),
        BollingerSignal(period=20, std_dev=2.0), EMASignal(fast=9, slow=21),
        CandlePatternSignal(),
    ])
    risk = RiskManager(
        max_trades_per_hour=settings.max_trades_per_hour,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        cooldown_after_loss_seconds=settings.cooldown_after_loss_seconds,
        trade_amount=settings.stake_amount,
        min_balance_multiplier=settings.min_balance_multiplier,
    )
    tracker = WinRateTracker(json_path=Path("data/win_rates.json"))
    nav = Navigator(tg, settings.signal_bot_username, click_trade_anyway=settings.click_trade_anyway)
    mgr = StrategyManagerV2(navigator=nav, api_client=api, confluence_engine=confluence,
                            risk_manager=risk, tracker=tracker)

    try:
        for _ in range(cycles):
            await mgr.run_once()
    finally:
        await tg.disconnect()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=1)
    args = ap.parse_args()
    asyncio.run(main(cycles=args.cycles))
```

Note: verify `settings` has `telegram_api_id/hash/session` and `signal_bot_username` (they exist per CLAUDE.md). If `telegram_session` field is absent, add it in Task 7 style.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_imports.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main_v2.py tests/test_imports.py
git commit -m "feat: main_v2 entrypoint wiring the v2 pipeline"
```

---

### Task 11: Integration dry-run against the live bot

**Files:**
- Create: `tools/v2_smoke.py` (drives ONE cycle in DRY_RUN; never selects an amount; logs to a temp decisions file)

- [ ] **Step 1:** Ensure `.env` has `TRADE_MODE=DEMO`, `DRY_RUN=true`, `PAIR_SELECT_MIN_WIN_RATE=0.0`, valid `TELEGRAM_*`, and (for non-dry candle fetch later) `PO_SSID`.

- [ ] **Step 2:** Confirm no live Telebot trader is running:

Run: `ps aux | grep pocket_robot_trader | grep -v grep`
Expected: no output.

- [ ] **Step 3:** Run one cycle:

Run: `.venv/bin/python main_v2.py --cycles 1`
Expected: log shows prediction parsed → pair selected → nag dismissed → direction parsed → candles fetched → decision (TRADE/SKIP) → in DRY_RUN the API buy/sell is short-circuited to a `DRY_RUN` status (no real trade). A row is appended to `data/decisions.jsonl`.

- [ ] **Step 4:** Inspect the row:

Run: `tail -1 data/decisions.jsonl | python3 -m json.tool`
Expected: contains `bot_direction`, `our_direction`, `agreement`, `combined_probability`, `decision`.

- [ ] **Step 5: Commit**

```bash
git add tools/v2_smoke.py
git commit -m "chore: v2 smoke-test tool for one dry-run cycle"
```

- [ ] **Step 6 (graduation):** Once dry-run looks correct, set `DRY_RUN=false` (still `TRADE_MODE=DEMO`), run `--cycles 1`, and confirm a real **demo** trade places, `check_win` resolves, and the decisions row backfills `outcome`/`pnl`.

---

### Task 12: API guard upgrade — use `is_demo()` / `is_ssid_valid()`

**Files:**
- Modify: `broker/po_api.py`
- Test: `tests/test_po_api_guard.py` (extend)

- [ ] **Step 1:** Add an async startup check in `connect()` that calls `await self._client.is_ssid_valid()` (if present) and logs/aborts on invalid; and prefer `await self._client.is_demo()` over SSID-string decoding when the client is connected, keeping `_parse_ssid_is_demo` as the offline fallback. Write tests with a mock client exposing `is_demo`/`is_ssid_valid`.

- [ ] **Step 2–5:** TDD as above; commit `feat: prefer API-native is_demo()/is_ssid_valid() in demo guard`.

---

### Task 13: Cleanup & full-suite green

- [ ] Fix the `signal_gate.py` log bug: `log.debug("Gate 1 PASS: stated win rate %.1%", …)` → `log.debug("Gate 1 PASS: stated win rate {:.1%}", signal.stated_win_rate)`.
- [ ] Fix `requirements.txt`: replace `binaryoptionstoolsv2>=2.0.0  # disabled …` with `binaryoptionstoolsv2>=0.2.11` (it works on Python 3.14 via abi3); remove unused `aiofiles`; remove `pandas-ta` from `pyproject.toml`.
- [ ] Run the whole suite: `.venv/bin/python -m pytest -q` → all green.
- [ ] Commit `chore: fix gate log bug, correct deps, drop unused`.

---

## 5. Phase 2 — Decisioning depth (roadmap; own plan later)

Once Phase 1 collects real rows: improve the internal edge.
- Per-signal weight tuning and a calibrated probability model fit on `decisions.jsonl` (logistic regression: features = bot_win_rate, each signal's direction/confidence, setup, expiry → P(win)).
- Expiry selection driven by which timeframe historically wins per pair (extend `select_expiry` with a `requested` from a learned table).
- Dynamic stake (replace fixed $1.50) using payout (`api.payout()`) and Kelly-fraction capped by `RiskManager`.
- Port Telebot's `pair_learnings.json` blocked/preferred lists as an additional gate (skip net-negative pairs).

## 6. Phase 3 — Learning & analysis (roadmap)

- `analysis/` scripts/notebooks over `data/decisions.jsonl`: realized P&L per pair/direction/expiry/win-band, agreement-vs-outcome correlation, calibration curves (predicted P vs realized).
- Nightly job that regenerates the calibrated model + pair learnings consumed by Phase 2.

## 7. Phase 4 — Professional UI (roadmap)

- Reuse Telebot's `dashboard_server.py` pattern (single Python HTTP server, `/api/dashboard` reads the log) but point at `data/decisions.jsonl`.
- Views: live cycle tape, equity curve (realized P&L), agreement rate, per-pair P&L table, calibration plot, current settings + safety state (DEMO/LIVE, DRY_RUN, win gate).
- Distinct, polished frontend (see `frontend-design` skill) — not the minimal Telebot UI.

---

## 8. Self-Review

**Spec coverage:**
- "assess the trading pair" → Tasks 1, 3 (prediction parse + normalize) ✅
- "look at the PO API to review and apply its own TA to the pair" → Task 9 (get_candles → ConfluenceEngine) ✅
- "assess validity and timeframe of stake (5s/10s/30s/1m)" → Task 4 (expiry) + Task 5 (validity/agreement) ✅
- "place the trade via the API" → Task 9 (buy/sell via `po_api`) + Task 11 graduation ✅
- "logging signals, probabilities, wins/losses … to analyse and learn" → Tasks 5, 6, 9 + Phase 3 ✅
- "coherent and professional UI" → Phase 4 ✅
- "$1.50 for now" → Task 7 (`stake_amount=1.5`) ✅
- "nag click-through, built in" → Task 8 (`dismiss_nag_if_present`, robust retries) ✅
- "take out 82% check while testing, turn back on" → Task 7 (`PAIR_SELECT_MIN_WIN_RATE=0.0` testing / `0.82` real) ✅

**Placeholder scan:** every code step contains full code; no TBD/TODO in Phase 1 tasks. Phases 2–4 are explicitly roadmap-level and will get their own detailed plans.

**Type consistency:** `parse_prediction → PredictionScreen.top_pick() → PairPrediction(.pair_raw,.win_rate,.is_top)`; `parse_direction_screen → DirectionScreen(.direction,.setup,.indicators_raw)`; `normalize_pair → str|None`; `select_expiry(default,allowed,requested)`; `decide(...) → Decision(.trade,.combined_probability,.skip_reason)`; `DecisionRow`/`write_decision`/`backfill_outcome`; `Navigator.start_autotrade/select_pair/read_latest_text/back_to_menu`; `StrategyManagerV2.run_once`. Consistent across tasks. ✅

---

## 9. Known constraints & safety

- **DEMO + DRY_RUN are the defaults** and must remain so until Task 11 graduation. The `po_api` demo guard is fail-closed.
- The Navigator **must never click an amount button** — that is the only thing that places a po_broker_bot (martingale/token) trade. Our trades go through the PocketOption API exclusively.
- Telethon session is single-writer: ensure no Telebot `pocket_robot_trader.py` is running before `main_v2.py`.
- ToS: both the unofficial PO API and the Telethon user session violate platform ToS — research/educational use; keep DEMO.
