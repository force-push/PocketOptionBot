# Tier 3 Signals: Momentum & Exhaustion Indicators

## Overview

Tier 3 signals are **momentum/exhaustion indicators** that are orthogonal to the
MACD + EMA trend-following core. They are added as **observation-only** (weight > 0
but NOT in `decision_signals`) following the same methodology as Tier 2.

**Why Tier 3 specifically exists:**
MACD and EMA are both moving-average derivatives — they are *correlated*. When price
is choppy and they disagree, both tend to lose together. Tier 3 adds a different
dimension: *momentum exhaustion* (is the current move running out of steam?) rather
than *trend direction* (which way is price going?). This gives the confluence engine
information it cannot extract from any amount of MACD/EMA data alone.

**Methodology — same as Tier 2:**
1. Add as observation-only: weight > 0, NOT in `decision_signals`
2. Run shadow mode for ~500 resolved trades
3. Run `scripts/analyze_signals.py` to measure agree/neutral/oppose win rates
4. Promote to `decision_signals` only if agree win rate > base by 3%+ points
5. Retire if agree win rate ≤ base or if it is inverted (oppose > agree)

---

## Status Overview

| Signal | File | Status | Weight |
|---|---|---|---|
| Stochastic Oscillator | `signals/stochastic.py` | ✅ Built (landed with Tier 2 batch) | 0.12 |
| Stochastic RSI | `signals/stoch_rsi.py` | ❌ Not built | Planned: 0.10 |
| Rate of Change | `signals/roc.py` | ❌ Not built | Planned: 0.08 |
| Heikin-Ashi Trend | `signals/heikin_ashi.py` | ❌ Not built (missed from Tier 2) | Planned: 0.12 |

> Stochastic is already running as a Tier 2 signal in the codebase. The remaining
> three are the true Tier 3 build queue.

---

## 1. Stochastic RSI (Stoch-RSI)

**File to create:** `signals/stoch_rsi.py`  
**Planned weight:** 0.10  
**Research doc reference:** `signal-strategy-research.md §4 Tier 3`

### What it does

Stoch-RSI applies the Stochastic formula *to the RSI value* rather than to price directly:

```
RSI_14 over the last N candles
Stoch-RSI_K = (RSI - min(RSI, N)) / (max(RSI, N) - min(RSI, N))
Stoch-RSI_D = smooth_k-period SMA of K
```

This makes it **more sensitive and faster** than plain RSI or plain Stochastic.
It spends more time at extremes (0 and 1), which is useful for catching momentum
reversals at short 30s–60s expiries.

### Why build it (not just use plain Stochastic)

Plain RSI was found to be **noise** (§2.3 of signal-strategy-research.md, ~45% WR
regardless of direction). Plain Stochastic was added as Tier 2 but also uses price
directly. Stoch-RSI is a **second-order** indicator: it catches cases where RSI is
near extremes AND momentum is exhausted — a more specific signal that reduces the
noise that killed plain RSI.

Key distinction:
- **RSI** → is price overbought/oversold in absolute terms?
- **Stochastic** → is price near the high/low of its recent range?
- **Stoch-RSI** → is *momentum itself* overbought/oversold? (fastest reversal signal)

### Signals

| Condition | Direction | Confidence |
|---|---|---|
| Stoch-RSI K < 0.20 (momentum oversold) | CALL | `min(1.0, (0.20 - K) / 0.20)` |
| Stoch-RSI K > 0.80 (momentum overbought) | PUT | `min(1.0, (K - 0.80) / 0.20)` |
| K crosses D upward (in oversold zone) | CALL | 0.45 |
| K crosses D downward (in overbought zone) | PUT | 0.45 |
| K between 0.20–0.80 | None | 0.0 |

### Parameters

```python
StochRSISignal(rsi_period=14, stoch_period=14, smooth_k=3, smooth_d=3)
```

### Known caveats

- Faster = noisier: in strong trends Stoch-RSI can pin at 0 or 1 for many bars,
  firing repeatedly in the same direction. This is fine for trend-following but
  needs checking against MACD/EMA agreement in analysis.
- Needs `rsi_period + stoch_period + smooth_k` candles to warm up (~35 candles
  minimum at 5s period = ~3 min). Same warm-up window as MACD.
- If plain Stochastic (already running) shows correlation, Stoch-RSI will likely
  show stronger correlation — but they are correlated with each other. Keep both
  as observation-only until data shows one clearly outperforms.

---

## 2. Rate of Change (RoC / Momentum)

**File to create:** `signals/roc.py`  
**Planned weight:** 0.08  
**Research doc reference:** `signal-strategy-research.md §4 Tier 3`

### What it does

The simplest possible momentum indicator:

```
RoC = (close[now] - close[N bars ago]) / close[N bars ago]  × 100
```

Positive RoC = price moved up N bars ago. Negative = down. Magnitude = speed.

### Why build it

MACD and EMA are both lagged smoothed derivatives of price. RoC is a **raw,
direct** measurement of price momentum with no smoothing. This means:

- It reacts *before* MACD/EMA update (no EMA lag)
- It captures whether the current bar is continuing or reversing a short move
- For 30s OTC trades: a 5-bar (25s) RoC shows whether the last 25 seconds of
  movement is continuing or stalling

The research data showed that all current signals fail together on choppy OTC
data. RoC is the lightest possible addition that is genuinely independent —
it uses a completely different computation path from everything else in the stack.

### Signals

| Condition | Direction | Confidence |
|---|---|---|
| RoC > `threshold` (default 0.05%) | CALL | `min(1.0, abs(RoC) / 0.3)` |
| RoC < `-threshold` (default 0.05%) | PUT | `min(1.0, abs(RoC) / 0.3)` |
| abs(RoC) ≤ threshold | None | 0.0 — flat/no momentum |

The threshold filters out near-zero noise on flat OTC periods. The confidence
scales linearly, capped at 0.3% RoC (typical strong 30s OTC move).

### Parameters

```python
RoCSignal(period=5, threshold=0.05, confidence_cap_pct=0.3)
```

`period=5` at 5s candles = 25 second lookback (roughly one trade expiry). This can
be tuned — `period=3` is faster (15s momentum), `period=10` is slower (50s trend).

### Known caveats

- High sensitivity to single-candle spikes (news events). In OTC synthetic pairs
  this is less common than in real forex, but worth watching.
- No smoothing means the signal can flip every bar. The weight (0.08) keeps its
  individual contribution modest — it only pushes the confluence score meaningfully
  when it aligns with MACD and EMA.
- If OTC data has low RoC values by nature (tight price action), the threshold may
  need tuning to be pair-specific. Start with 0.05% and adjust based on analysis.

---

## 3. Heikin-Ashi Trend (missed from Tier 2)

**File to create:** `signals/heikin_ashi.py`  
**Planned weight:** 0.12  
**Research doc reference:** `signal-strategy-research.md §4 Tier 2` (was listed
here but never implemented in the Tier 2 build batch)

### What it does

Heikin-Ashi (HA) candles are a **price transformation** — not a raw indicator —
that smooths noise by averaging the previous candle into each new one:

```
HA_Close = (open + high + low + close) / 4
HA_Open  = (prev_HA_open + prev_HA_close) / 2
HA_High  = max(high, HA_open, HA_close)
HA_Low   = min(low, HA_open, HA_close)
```

The *colour* (HA_Close > HA_Open = bullish, else bearish) and *persistence*
(N consecutive same-colour bars) indicate trend direction and strength.

### Why build it

OTC synthetic pairs have significant noise — individual candles are unreliable.
HA smoothing specifically reduces false bar-level signals. It is the **most
orthogonal** addition to the signal stack because:

- It doesn't use any indicator formula (RSI, EMA, MACD) — it reworks the *raw
  price data itself*
- N consecutive HA bullish bars is a statement about price persistence, not
  momentum or level
- Research doc noted: "Smoothed candles cut OTC noise; consecutive HA colour =
  persistence" — the exact problem the OTC pairs have

### Signals

| Condition | Direction | Confidence |
|---|---|---|
| ≥ 3 consecutive bullish HA bars | CALL | `min(1.0, (n - 2) × 0.25)` |
| ≥ 3 consecutive bearish HA bars | PUT | `min(1.0, (n - 2) × 0.25)` |
| Bar just switched colour (reversal) | opposite direction | 0.35 |
| < 3 consecutive same-colour bars | None | 0.0 |

Confidence scales with run length: 3 bars = 0.25, 4 = 0.50, 5 = 0.75, 6+ = 1.0.

### Parameters

```python
HeikinAshiSignal(min_consecutive=3)
```

### Known caveats

- HA open/close values don't reflect real executed prices — the signal is purely
  directional, never use for entry/exit pricing.
- HA smoothing adds ~1 bar of lag. At 5s candles that's 5 seconds — acceptable for
  30s expiry, marginal for 5–10s expiry.
- In strong sustained trends, HA fires continuously. This is correct behaviour
  (trend persistence), but weight must stay modest to avoid over-weighting trend
  vs the MACD/EMA core.

---

## Implementation order

Given that data collection is the bottleneck (need ~500 trades per signal to
measure correlation), build and activate all three together so they share the same
observation window:

1. **Heikin-Ashi first** — most orthogonal, no warm-up issues, clean implementation
2. **RoC second** — trivial computation, no library deps
3. **Stoch-RSI third** — most complex (requires RSI sub-calculation), save for last

All three are added to the `signals` list in `main_v2.py` with `decision_signals`
unchanged (`{"MACD", "EMA_Cross"}`). No `.env` changes needed — weights are
code-level until data supports promotion.

---

## Tier summary after Tier 3

| Tier | Signals | Weight > 0? | Can gate trades? |
|---|---|---|---|
| Tier 0 | RSI, MACD, Bollinger, EMA_Cross, CandlePattern | Yes | MACD + EMA only |
| Tier 1 | ADX_DMI, ATR | No (0.0) | Never |
| Tier 2 | Stochastic, Parabolic SAR, Supertrend | Yes | Not yet |
| Tier 3 | Stoch-RSI, RoC, Heikin-Ashi | Yes (once built) | Not yet |

Promotion path for any Tier 2 or 3 signal: collect 500 resolved shadow trades,
run `scripts/analyze_signals.py`, check agree WR > base + 3pts, add to
`decision_signals` in `main_v2.py`.
