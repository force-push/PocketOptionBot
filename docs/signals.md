# TA Signal Design — PocketOptionBot v2

## Overview

Five signals feed into a `ConfluenceEngine` that produces a single CALL/PUT/None
decision.  Two independent gates must both pass before a trade is taken:

1. **Agreement gate** (`MIN_SIGNAL_AGREEMENT`, default **2/5**) — at least N signals
   must agree on the same non-None direction.  Lowered to 2 for calibration so
   trades execute and real outcomes inform tuning. Raise to 3+ for stricter entry.
2. **Score floor** (adaptive based on agreement count, default **0.10–0.40**) — the
   weighted sum of confidences for the winning direction must exceed a threshold that
   varies by how many signals agree:
   - 2 signals agree → threshold = 0.10 (calibration mode)
   - 3 signals agree → threshold = 0.25
   - 4 signals agree → threshold = 0.32
   - 5 signals agree → threshold = 0.40

This adaptive approach prevents the score gate from being too strict when fewer signals
agree (they need to be more confident), while still filtering out low-confidence trades
when many signals agree.

Both gates are tunable via `.env` / dashboard without a code change.

---

## Candle Resolution

**Setting:** `CANDLE_INTERVAL_SECONDS` (default **5 s**)

Candle period is intentionally decoupled from trade expiry.  The original code
used `period = expiry_seconds` (e.g. 30 s candles for 30 s trades), meaning each
candle represented exactly one trade window.  This caused two problems:

- MACD needs 26+ slow-EMA candles to warm up (= 13 minutes at 30 s).  If the API
  returned fewer candles, MACD returned null every cycle.
- EMA and MACD crossover signals need fine-grained price data to detect the exact
  bar of a trend shift.  At 30 s resolution, multi-bar momentum patterns are
  invisible.

With 5 s candles: 100 candles = **8.3 minutes of context**.  MACD warm-up needs
35 candles = 175 s ≈ 3 min.  All five signals can evaluate with room to spare.

### Choosing candle period

| Period | 100 candles | Notes |
|--------|------------|-------|
| 5 s    | 8.3 min    | Recommended for 30 s–60 s expiry.  Fine-grained momentum. |
| 15 s   | 25 min     | Less noise; crossover signals fire less often. |
| 30 s   | 50 min     | Original (incorrect) value — one candle per trade. |
| 60 s   | 100 min    | Too coarse for sub-minute trades; hourly trend ≠ 30 s entry. |

---

## Signal Reference

### RSI (weight 0.20)

Mean-reversion signal.  Fires when price is in extreme territory.

| RSI value | Signal | Confidence |
|-----------|--------|-----------|
| < `RSI_OVERSOLD` (30) | CALL | Scales with distance from threshold |
| > `RSI_OVERBOUGHT` (70) | PUT | Scales with distance from threshold |
| Between thresholds | null | No signal |

**Tuning:** Tightening to 20/80 filters noise but reduces trade frequency.
Loosening to 35/65 fires more often at lower quality.

---

### MACD (weight 0.20)

Trend-direction signal with two tiers.

**Why two tiers?**  The original implementation only fired on the exact bar of a
crossover.  A crossover is a 1-bar event; in a 100-candle window there may be
zero crossovers, so MACD returned null on most cycles.  For short binary options,
sustained momentum alignment is as relevant as the crossover moment.

| Condition | Signal | Confidence |
|-----------|--------|-----------|
| MACD line just crossed above signal line | CALL | 0–1.0 (histogram momentum) |
| MACD line just crossed below signal line | PUT  | 0–1.0 (histogram momentum) |
| MACD above signal (established trend) | CALL | 0–0.60 (gap magnitude) |
| MACD below signal (established trend) | PUT  | 0–0.60 (gap magnitude) |
| MACD flat (equal to signal) | null | — |

The 0.60 cap on established-trend confidence ensures a genuine crossover always
outscores a sustained trend in the weighted confluence sum.

**Params:** `MACD_FAST` (12), `MACD_SLOW` (26), `MACD_SIGNAL_PERIOD` (9).

---

### Bollinger Bands (weight 0.20)

Mean-reversion signal.  Fires when price breaks outside the bands.

| Condition | Signal | Confidence |
|-----------|--------|-----------|
| Price ≤ lower band | CALL | Distance below band / std dev |
| Price ≥ upper band | PUT  | Distance above band / std dev |
| Price within bands | null | — |

**Params:** `BOLLINGER_PERIOD` (20), `BOLLINGER_STD` (2.0).  Wider std (2.5)
fires less often on more extreme breaks; narrower (1.5) fires on smaller deviations.

---

### EMA Cross (weight 0.15)

Trend-direction signal with two tiers — same design rationale as MACD.

| Condition | Signal | Confidence |
|-----------|--------|-----------|
| Fast EMA just crossed above slow EMA | CALL | 0–1.0 (gap %) |
| Fast EMA just crossed below slow EMA | PUT  | 0–1.0 (gap %) |
| Fast EMA above slow (established) | CALL | 0–0.55 (gap %) |
| Fast EMA below slow (established) | PUT  | 0–0.55 (gap %) |
| EMAs equal | null | — |

EMA's cap (0.55) is slightly lower than MACD's (0.60) because EMA crossovers on
short timeframes are noisier, so the trend-bias signal is given a smaller weight.

**Confidence weighting by gap:**
Crossover confidence is calculated as `min(1.0, gap_pct × 100)` where `gap_pct` is
the percentage gap between the EMAs relative to the slow EMA value. This means:

- **Gap = 0.1 (0.01%)**: confidence ≈ 0.10 — strong, clean crossover
- **Gap = 0.001 (0.0001%)**: confidence ≈ 0.001 → 0.00 when rounded — near-zero momentum

A crossover with near-zero separation (e.g., fast=1.19497, slow=1.19498, gap=0.00001)
indicates **almost no momentum** behind the trend change. This is likely floating-point
noise or a brief kiss with immediate reversal, not a sustained trend. The algorithm
correctly assigns ~0.0 confidence to such weak crossovers — trading them usually loses
money.

**Params:** `EMA_FAST` (9), `EMA_SLOW` (21).

---

### Candle Pattern (weight 0.25)

Pattern recognition — fires on the last 2–3 candles.  Highest weight because
candlestick reversals are directly observable price-action evidence, not derived
indicators.

| Pattern | Signal | Confidence |
|---------|--------|-----------|
| Bullish Engulfing | CALL | 0.80 |
| Bearish Engulfing | PUT  | 0.80 |
| Hammer (long lower wick) | CALL | 0.70 |
| Shooting Star (long upper wick) | PUT | 0.70 |
| Doji (indecision) | null | 0.30 |
| No pattern | null | 0.00 |

---

## Confluence Score Math

The score is the **weighted sum of confidences for the winning direction only**:

```
score = Σ (signal_confidence × normalized_weight)  for all signals where direction == winner
```

Normalized weights sum to 1.0: RSI 0.20 + MACD 0.20 + Bollinger 0.20 + EMA 0.15 + CandlePattern 0.25

### Typical score ranges

| Scenario | approx score |
|----------|-------------|
| 3 signals agree, moderate conf (0.4–0.5) | 0.22–0.28 |
| 3 signals agree, strong conf (0.6–0.8) | 0.33–0.44 |
| 4 signals agree, moderate conf | 0.32–0.42 |
| 4 signals agree, strong conf | 0.48–0.64 |
| 5 signals agree, strong conf | 0.64–0.85 |
| Fresh crossover on MACD + EMA, others agree | 0.60–0.90 |

**Default floor: `MIN_CONFLUENCE_SCORE = 0.40`** — requires roughly 3 signals at
strong confidence or 4 at moderate.  Raise to 0.55 for stricter entries; lower to
0.30 to observe more trades during calibration.

---

## Tuning workflow

Once real trade data accumulates in `data/decisions.jsonl`:

1. Open the dashboard → click any history row → see per-signal breakdown.
2. Look for patterns: does `no_direction` always coincide with RSI neutral + MACD
   weak trend?  That's a signal threshold issue.
3. Adjust via dashboard Settings → **TA Signal Parameters**, save, restart the bot.
4. Watch the next few cycles in the logs — the per-signal reason strings show the
   exact indicator values (e.g. `RSI neutral: 52.4 (range 30–70)`).

PocketOption expiry options change dynamically; if a previously available expiry
disappears, update `DEFAULT_EXPIRY_SECONDS` in Settings.  The `select_expiry()`
helper snaps the requested value to the nearest allowed one automatically.

---

## Trade Execution & Background Resolution

Once a trade passes both confluence gates and the risk manager approves it:

1. **Immediate execution** — trade is placed via the PocketOption API
2. **Main loop continues** — bot does NOT block waiting for expiry (30+ seconds)
3. **Background resolution** — async task waits for expiry, checks outcome, updates logs
4. **Results stored** — outcomes backfilled into `data/decisions.jsonl` with WIN/LOSS/DRAW

**Key settings:**
- `TRADE_MODE` — must be `DEMO` (default, safe). Never set to `LIVE` unless intentional.
- `DRY_RUN` — when `true`, trades are logged but not executed (no outcomes). Set to
  `false` to actually execute trades on the API and see real results.
- `MAX_TRADES_PER_HOUR` — sliding 1-hour window limit (default 24)
- `MAX_DAILY_LOSS_USD` — daily loss limit (default $50)

The background resolver allows the bot to process ~2 trades/minute instead of
~2 trades/30-second expiry. This dramatically increases throughput during calibration
and lets you gather data on signal performance quickly.
