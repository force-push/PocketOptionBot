---
title: "Option A — Payout-First, Signals-Driven Trading"
type: feature-requirements + build-plan
status: APPROVED — ready to build
owner: Kym
author: Praxis
date: 2026-06-09
related: [signal-strategy-research, tier2-signals, tier3-signals]
---

# Option A — Payout-First, Signals-Driven Trading

## 1. Background & Problem

Today the bot is **prediction-first**: every cycle drives the `po_broker_bot`
Telegram UI (`start_autotrade → wait_for_prediction → select_pair → read
direction screen`) to obtain a direction, then runs our own TA confluence and
only trades when our direction agrees with the broker bot's
(`decide()` → `ta_disagree` skip otherwise).

This couples the trade loop to a fragile, rate-limited Telegram path. On
2026-06-09 a `FloodWait` of 3198s blocked all trading for ~1 hour. The broker
bot's predictive edge is also unproven, yet it gates every trade.

**Key finding:** trade *execution* already runs through the PocketOption API
(`broker/po_api.py::buy()/sell()`), not Telegram. The Telegram navigator is used
*only* for the prediction and pair-menu. Therefore a payout-first, signals-only
loop can bypass Telegram entirely on the hot path while keeping execution
unchanged.

## 2. Goals / Non-Goals

**Goals**
- G1. Drive the trade loop by **payout** (scan all pairs ≥ floor), not by the
  broker bot prediction.
- G2. Source trade **direction from our own confluence engine**, gated on
  MACD + EMA_Cross (current gate retained).
- G3. Make the broker-bot path **toggleable via config** so we can revert to
  prediction-first instantly. Keep the navigator code intact.
- G4. Keep all other 9 signals running as **shadow/observation** (recorded, not
  gating) to accumulate the 500-trade dataset for later promotion.
- G5. Remove Telegram from the hot path when in signals mode → no FloodWait
  dependency.

**Non-Goals**
- N1. No change to risk/EV/win-rate/concurrency gates (kept exactly as-is).
- N2. No retuning of signal weights or thresholds in this work.
- N3. No promotion of shadow signals to deciding (separate, data-driven step
  after 500 trades).
- N4. No removal or refactor of the `po_broker_bot` navigator.

## 3. Locked Decisions

| # | Decision |
|---|----------|
| D1 | **Broker bot = dormant, config toggle.** `PREDICTION_SOURCE=signals\|broker_bot`, default `signals`. Navigator retained but not invoked in signals mode. |
| D2 | **Gate = MACD + EMA_Cross.** Direction = confluence direction; trade only when the MACD+EMA decision gate passes (current behaviour). |
| D3 | **Other 9 signals = shadow.** Evaluated and recorded every cycle, never gate. (Already the case via `decision_signals`.) |
| D4 | **Pair scan = all ≥ floor**, ranked by payout, evaluated up to the concurrency cap. |
| D5 | **Risk/EV/win-rate/concurrency = unchanged.** |
| D6 | **Floor = config**, `MIN_PAYOUT_PCT`, default `92`. |

## 4. Functional Requirements

- **FR-1 — Mode switch.** A config value `PREDICTION_SOURCE` selects the loop
  driver: `signals` (new payout-first loop) or `broker_bot` (current
  prediction-first loop). Default `signals`. Invalid value → fail closed to
  `broker_bot` with a warning, so we never silently change behaviour.

- **FR-2 — Payout-first pair enumeration (signals mode).** Each cycle:
  1. `get_active_pairs()` → filter `is_active` and `payout ≥ MIN_PAYOUT_PCT`.
  2. Exclude `blocked_pairs`.
  3. Rank by payout desc (already sorted by the API helper).
  4. Evaluate pairs in order; place trades for those passing all gates until the
     concurrent-trade cap is reached, then stop the cycle.

- **FR-3 — Direction from confluence.** For each candidate pair, fetch candles
  (`get_candles`), run `ConfluenceEngine.score(df)`. The MACD+EMA decision gate
  produces `direction ∈ {CALL, PUT, None}` and a `score`. `None` → skip pair
  (`reason=no_direction`).

- **FR-4 — Signals-mode decision.** `decide()` gains a signals-mode path with no
  broker bot input: trade when `direction` is non-None and the confluence gate
  passed; `combined_probability` derived from the tracked per-pair win-rate
  (replacing `bot_win_rate`). No `ta_disagree` concept in signals mode.

- **FR-5 — Shadow recording.** All non-deciding signals' direction + confidence
  are recorded to the decision log every evaluated cycle (trade or skip), so the
  500-trade attribution dataset accrues regardless of mode.

- **FR-6 — Risk parity.** EV filter, per-pair win-rate gate, negative-EV skip,
  max concurrent trades, max trades/hr, cooldown, min balance — all applied
  identically to the current loop. Option A changes *what* we trade and *why*,
  not *whether risk allows it*.

- **FR-7 — Execution unchanged.** Orders placed via `po_api.buy()/sell()`;
  outcomes resolved via `poll_trade_outcome()`; results recorded via the existing
  `WinRateTracker`, `trade_logger`, and dashboard bridge.

- **FR-8 — Broker-bot mode untouched.** With `PREDICTION_SOURCE=broker_bot` the
  loop behaves exactly as today (regression-safe).

- **FR-9 — Observability.** Startup log states the active mode and floor. Per
  cycle in signals mode: log pairs scanned, pairs passing gate, trades placed,
  skips with reasons. Dashboard continues to read `live_state.json` / `events.jsonl`.

## 5. Config Additions (`config/settings`)

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `PREDICTION_SOURCE` | enum(`signals`,`broker_bot`) | `signals` | FR-1 |
| `MIN_PAYOUT_PCT` | int | `92` | Already exists (`min_payout_pct`); confirm default + surface in `.env.example` |
| `MAX_PAIRS_PER_CYCLE` | int | `0` (=all) | Optional bound; 0 = evaluate all ≥ floor |

No new risk/EV keys (D5).

## 6. Data Flow

**Signals mode (new, default):**
```
loop tick
  → get_active_pairs() → filter payout ≥ MIN_PAYOUT_PCT, drop blocked, rank
  → for each pair (until concurrency cap):
        get_payout (confirm) → get_candles
        → ConfluenceEngine.score()  [MACD+EMA gate + 9 shadow signals]
        → decide(signals-mode): direction? gate passed? → P(win) from tracker
        → risk gates (EV, win-rate, concurrency, cooldown…)
        → buy()/sell()  → background poll_trade_outcome() → tracker + logger + bridge
  → record decision rows (incl. shadow signal breakdown) for every evaluated pair
  → sleep(cycle pause)
```

**Broker-bot mode (retained):** unchanged from current `run_once`.

## 7. Component Changes (file-by-file)

| File | Change | Risk |
|------|--------|------|
| `config/settings.py` (+ `.env.example`) | Add `PREDICTION_SOURCE`, `MAX_PAIRS_PER_CYCLE`; confirm `MIN_PAYOUT_PCT` default 92 | Low |
| `strategy/decision.py` | Add signals-mode path to `decide()` (or a sibling `decide_signals()`); P(win) from tracked win-rate; no `ta_disagree` | Low |
| `strategy/manager_v2.py` | Split `run_once()` → `_run_once_broker_bot()` (current body, verbatim) and `_run_once_signals()` (new payout-first); dispatch on `PREDICTION_SOURCE`. Reuse confluence, risk, tracker, logger, bridge | **Med** — core loop |
| `main_v2.py` | Startup log line for mode + floor; no structural change (still calls `manager.run_once()`) | Low |
| `telegram_feed/navigator.py` | **No change.** Only invoked in broker_bot mode | None |
| `tests/` | New: `test_decision_signals_mode.py`, `test_manager_signals_loop.py` (mock api `get_active_pairs`/`get_candles`/`buy`); assert payout filter, gate, concurrency cap, shadow recording | Low |
| `docs/` | This FRD; update `PROJECT_STATUS.md` + `README.md` mode section | Low |

## 8. Concise Build Plan

**Phase 1 — Config + decision core (small, testable)**
1. Add `PREDICTION_SOURCE`, `MAX_PAIRS_PER_CYCLE` to settings + `.env.example`; confirm `MIN_PAYOUT_PCT=92`.
2. Add signals-mode to `decide()` + unit test (`test_decision_signals_mode.py`).
3. ✅ Verify: `pytest tests/test_decision_signals_mode.py`.

**Phase 2 — Signals loop**
4. Refactor `manager_v2.run_once()` into broker-bot (verbatim) + signals branches; dispatch on mode.
5. Implement `_run_once_signals()`: enumerate → filter → per-pair confluence → decide → risk → execute → record; honour concurrency cap and `MAX_PAIRS_PER_CYCLE`.
6. Ensure shadow signal breakdown is written for every evaluated pair (FR-5).
7. ✅ Verify: `pytest tests/test_manager_signals_loop.py` (mocked API).

**Phase 3 — Wire-up + regression**
8. Startup mode/floor log in `main_v2.py`.
9. ✅ Regression: run `PREDICTION_SOURCE=broker_bot` with `--cycles 1` → behaviour identical to today.
10. ✅ Full suite: `pytest tests/` (expect prior 169 green + new).

**Phase 4 — Live demo validation**
11. Run signals mode, `dry_run=True`, `--cycles 5` → inspect decision log: pairs scanned, gate hits, shadow rows present, **no Telegram calls**.
12. Run signals mode, `dry_run=False` DEMO → confirm real demo orders, outcomes resolved, `trades.jsonl` + `win_rates.json` updating, dashboard populating.
13. Leave running to accumulate toward the **500-trade** shadow dataset, then run `scripts/analyze_signals.py` for promotion review (separate work).

**Estimated effort:** Phases 1–3 ≈ half a day of focused work; Phase 4 is observation.

## 9. Risks & Rollback

- **R1 — Loop refactor regresses broker-bot mode.** Mitigation: move the current
  `run_once` body verbatim into `_run_once_broker_bot()`; Phase 3 step 9 regression.
- **R2 — Pair enumeration cost / rate limits on the PO API.** Mitigation:
  `MAX_PAIRS_PER_CYCLE` bound; reuse existing cycle pause; concurrency cap stops
  the scan early once full.
- **R3 — Signals over-trade without the broker-bot filter.** Mitigation: MACD+EMA
  gate + EV + per-pair win-rate gates remain; observe in Phase 4 dry-run before live.
- **R4 — Direction quality unknown standalone.** Accepted: that is exactly what the
  500-trade dataset measures. Demo-only until validated.
- **Rollback:** set `PREDICTION_SOURCE=broker_bot`. Zero code revert needed.

## 10. Open Questions

- OQ1. In signals mode, should we still honour `pair_select_min_win_rate` as a
  *pre-filter* (skip pairs whose tracked win-rate is below gate before running
  TA), or only apply win-rate inside the existing risk/EV gates? Default
  assumption: apply as today inside risk/EV; no extra pre-filter. Flag if you
  want the pre-filter for efficiency.
