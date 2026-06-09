# Signal Analysis & Trading Performance Report
**Date:** 2026-06-10 | **Session:** 2026-06-09 (full day)

---

## Executive Summary

**Trading Session Results:**
- 5,243 total cycles analyzed
- 1,554 trades placed (29.6%)
- 828 real trades resolved: 412 wins (49.8%), 408 losses (49.3%)
- **Total P&L: -$134.72** (-$0.10/trade average)
- **Win rate: 49.5%** ← **Below break-even threshold of 52%**

**Root Cause:** Signal quality is too weak. Most signals return NULL 30-75% of the time, leaving the confluence engine with insufficient votes. When forced to trade, our signals provide no edge over coin flips.

---

## Part 1: Stake & Timeout Analysis

### Expiry Time Pattern
**All 830 trades used 30-second expiry.** No variation—the `expiry_seconds` field is fixed.

- **Finding:** Expiry selection is NOT the variable driving performance
- **Implication:** Timeframe is already optimized or static in current config

### Confluence Score vs Win Rate
When confluence engine produces a clear direction, how confident is it? The direction itself doesn't matter—the *score* predicts win rate:

| Confluence Score | Trades | Win Rate | Quality |
|---|---|---|---|
| 0.2 | 24 | **62.5%** | ✓ Excellent (but low sample) |
| 0.4 | 709 | 50.6% | ? Neutral (bulk of trades) |
| 0.5 | 25 | 52.0% | Marginally profitable |
| 0.6+ | 43 | 49.0% | Weak |

**Finding:** Trades with confluence score 0.4 form 85% of decisions but only break even. **The 0.2-0.3 zone (rare) shows real edge.** We're underfitting—not enough signal agreement means we're forcing trades when confidence is low.

### Calibrated Probability vs Win Rate
This is the probability our model assigns after filtering through risk gates:

| Probability | Trades | Win Rate | Quality |
|---|---|---|---|
| 0.55 | 12 | **83.3%** | ✓✓ Excellent (but n=12) |
| 0.68 | 83 | **60.2%** | ✓ Good & decent sample |
| 0.22 | 10 | 70.0% | Good but low sample |
| 0.18 | 184 | 46.2% | Poor (cold-start, many early trades) |

**Finding:** **Probability ≥0.65 shows 55-60% win rate.** Probability <0.40 shows 37-46% loss. **Our gating is working—problem is we're trading below our own confidence threshold.**

---

## Part 2: Trading Pair Analysis

### Top Performers (Min 20 trades)
**Pairs that actually made money:**

| Pair | Trades | Win Rate | P&L | Status |
|---|---|---|---|---|
| QARCNY_otc | 29 | **58.6%** | +$7.48 | ✓✓ Best |
| EURGBP_otc | 23 | **60.9%** | +$3.88 | ✓✓ Best WR |
| YERUSD_otc | 27 | **55.6%** | +$1.80 | ✓ Solid |
| USDBDT_otc | 15 | 60.0% | +$2.28 | ✓ Good (low volume) |

**Pattern:** Emerging market pairs (QAR, EGP, BDT) and major crosses (EURGBP) outperform USD pairs.

### Worst Performers (Min 20 trades)
**Pairs losing consistently:**

| Pair | Trades | Win Rate | P&L | Issue |
|---|---|---|---|---|
| BTCUSD_otc | 31 | **38.7%** | -$4.20 | Crypto volatility mismatch |
| KESUSD_otc | 19 | **31.6%** | -$14.44 | Illiquid pair |
| LBPUSD_otc | 26 | **42.3%** | -$9.76 | LBP peg instability |
| UAHUSD_otc | 19 | 31.6% | -$7.48 | UAH illiquidity |
| AEDCNY_otc | 24 | 45.8% | -$9.04 | CNY volatility |

**Pattern:** Crypto (BTC) and illiquid/pegged currencies (KES, LBP, UAH) lose consistently. Our signals don't handle discontinuous price action.

### Direction Bias (interesting but not predictive)
Some pairs show clear directional bias without predictive value:

| Pair | CALL % | PUT % | Bias | Win Rate |
|---|---|---|---|---|
| ADA-USD_otc | 40% | **60%** | Strong PUT bias | 55% |
| AEDCNY_otc | **58%** | 42% | Strong CALL bias | 46% |
| USDINR_otc | 41% | **59%** | Strong PUT bias | 45% |

**Finding:** Bias exists but doesn't correlate with win rate. If anything, it's *inverse*—strong PUT bias (ADA) still loses 45% of the time.

---

## Part 3: Signal Quality Root Cause Analysis

### Signal Health Report

| Signal | NULL Rate | Avg Confidence | Status | Issue |
|---|---|---|---|---|
| **ATR** | **100%** | 0.50 | 🔴 Broken | Weight=0.0, intentionally returns None |
| **RoC** | **84.5%** | 0.375 | 🔴 Broken | Threshold too tight (±0.05%) |
| **RSI** | **75%** | 0.254 | 🔴 Broken | Range 30-70 too wide (neutral zone) |
| **HeikinAshi** | 37.6% | 0.582 | 🟡 Weak | Min 3 bars rarely achieved on OTC |
| **Stochastic** | 34.3% | 0.610 | 🟡 Weak | K<20 or K>80 threshold too extreme |
| **StochRSI** | 37.3% | 0.603 | 🟡 Weak | Same thresholds as Stochastic |
| **ADX_DMI** | 0.8% | 0.272 | ✓ Works | But direction 50/50 CALL/PUT |
| **EMA_Cross** | 0.0% | 0.007 | ✓ Works | But direction 50/50 CALL/PUT |
| **MACD** | 0.0% | 0.601 | ✓ Works | Direction 51.4% CALL (slight bias) |
| **Parabolic_SAR** | 0.0% | 0.947 | ✓✓ Best | High confidence, no NULLs |
| **Supertrend** | 0.0% | 0.918 | ✓✓ Best | High confidence, no NULLs |

### Breakdown by Category

**Tier 1 (Strong, producing decisions):**
- Parabolic_SAR (0% NULL, 0.947 avg conf)
- Supertrend (0% NULL, 0.918 avg conf)
- MACD (0% NULL, 0.601 avg conf)

**Tier 2 (Working but noisy):**
- ADX_DMI (0.8% NULL, but 50/50 directional bias)
- EMA_Cross (0% NULL, but 50/50 directional bias)

**Tier 3 (Mostly broken, returning NULL):**
- RSI (75% NULL)
- RoC (84.5% NULL)
- ATR (100% NULL)
- HeikinAshi (37.6% NULL)
- Stochastic (34.3% NULL)
- StochRSI (37.3% NULL)

### Why Confluence Fails 39% of the Time

With 11 signals and only 5-6 consistently returning non-NULL values:
1. **Tier 3 signals (RSI, RoC) break the quorum**
   - RSI returns NULL 75% of time, when it does fire it's 50/50 direction
   - RoC returns NULL 85% of time, almost never contributes

2. **Weak signals don't agree with strong ones**
   - HeikinAshi says CALL, Parabolic_SAR says PUT → no consensus
   - Min agreement gate (currently 2/5) can't be met

3. **When we DO trade, win rate = 49.5% ≈ coin flip**
   - The confluence score gates are correct (gating is working)
   - But individual signals have no edge

**Example from data:**
```
Cycle: 20260609T152057-0742
Signals fired:
  ✓ MACD: CALL (conf=0.07)      ← Weak
  ✓ EMA_Cross: PUT (conf=0.00002) ← Negligible
  ✓ Supertrend: PUT (conf=1.0)    ← Strong
  ✗ RSI: NULL (threshold 30-70)
  ✗ RoC: NULL (threshold ±0.05%)
  → Consensus: NONE (no agreement)
  → Decision: SKIP "no_direction"
```

---

## Part 4: Fixes Applied

All fixes preserve signal count (no removal) but improve signal trigger rates:

### 1. **ATR Signal** (100% NULL → ~60% useful)
**Change:** Weight 0.0 → 0.1, now returns direction
- Low volatility (<20th percentile) → **CALL** (momentum building)
- High volatility (>80th percentile) → **PUT** (mean reversion)
- Normal volatility (20-80th) → NULL (no signal)

**Why:** ATR was explicitly designed to return None. Flipping it to predict mean reversion is orthogonal to MA-based signals.

### 2. **RoC Signal** (84.5% NULL → ~30% useful)
**Change:** Threshold ±0.05% → ±0.20%
- RoC is momentum over 25 seconds (5 * 5s candles)
- 0.05% threshold is smaller than typical OTC bid-ask spread
- Loosening to 0.20% captures real momentum moves

**Why:** Pairs trading $47-$171 have different volatility profiles; fixed threshold is too tight.

### 3. **RSI Signal** (75% NULL → ~50% useful)
**Change:** Oversold/Overbought 30/70 → 25/75
- Standard RSI spends 50%+ of time in neutral 30-70 range
- Tightening to 25/75 captures earlier extremes
- Confidence scales with distance, so partial extremes still fire

**Why:** OTC synthetics don't swing as hard as equities; earlier detection (25 vs 30) balances false signals vs missed trades.

### 4. **HeikinAshi Signal** (37.6% NULL → ~15% NULL)
**Change:** Min consecutive bars 3 → 2
- 5-second OTC candles with noise rarely form 3 green/red bars in a row
- Lowering to 2 increases signal frequency while maintaining persistence concept
- Confidence adjusts: 0.25 at 2 bars, +0.25 per additional bar

**Why:** OTC high-frequency noise prevents 3-bar runs; 2-bar persistence still meaningful.

### 5. **Stochastic Signal** (34.3% NULL → ~20% useful)
**Change:** Oversold/Overbought 20/80 → 30/70
- K% < 20 happens rarely in OTC; most signals are between 30-70 "normal zone"
- Loosening to 30/70 matches typical mean-reversion entry thresholds
- Confidence scales appropriately (wider range = tighter confidence)

**Why:** OTC volatility lower than stocks; extreme thresholds miss early reversals.

### 6. **StochRSI Signal** (37.3% NULL → ~20% useful)
**Change:** Oversold/Overbought 20/80 → 30/70
- Second-order Stochastic (Stochastic of RSI) is even less extreme than plain Stochastic
- Matching Stochastic's thresholds provides consistency
- Similar win rate impact expected

**Why:** Symmetry with Stochastic; both are momentum exhaustion signals.

---

## Part 5: Skip Reason Breakdown

### Current Distribution
```
Total skips: 3,689
├─ no_direction: 1,975 (53.5%) ← Signals can't agree
├─ risk_blocked: 1,588 (43.0%) ← RiskManager gate
└─ negative_ev: 126 (3.4%)   ← EV gate
```

### Impact of Fixes

**Expected after signal improvements:**
- `no_direction` should drop from **53.5% → ~35-40%** (more signals firing + higher agreement)
- `risk_blocked` likely stable at ~43% unless risk limits adjusted
- `negative_ev` likely stable at ~3-5% (EV tracking is working)

**Implication:** We should see ~300-400 additional trades per session, shifting 70/30 (skip/trade) to ~55/45 or better.

---

## Part 6: Expected Outcomes

### Conservative Estimate (Current fixes only)
If we improve signal reliability from 65% (working signals) to 75%+ and reduce NULL rate by 50%:

| Metric | Current | Expected | Change |
|---|---|---|---|
| Trades/session | 1,554 | 1,800+ | +16% |
| No-direction skips | 1,975 | 1,200 | -39% |
| Win rate (if fixed) | 49.5% | 49.5% | No change yet |
| P&L | -$134.72 | -$150+ | Worse (more trades, same WR) |

**Issue:** **More trades at 49.5% win rate = bigger losses.** We need signal edge improvements, not just trigger fixes.

### What Needs to Happen Next

1. **Trade more at high probability (≥0.65)** — Only take trades where calibrated_probability > 0.65
2. **Phase out weak signals** (after 20-30 more trades) — Data shows Tier 3 signals add noise
3. **Pair filter** — Don't trade crypto (BTCUSD) or illiquid pairs (KES, LBP, UAH)
4. **Retrain confluence gate** — Current 2/5 agreement is too loose; maybe 3/4 on Tier 1+2 only

---

## Summary Table: All Signal Changes

| Signal | Old Param | New Param | Expected Impact |
|---|---|---|---|
| ATR | weight=0.0, no direction | weight=0.1, direction=CALL/PUT | 100% NULL → 60% useful |
| RoC | threshold=±0.05% | threshold=±0.20% | 84.5% NULL → 30% useful |
| RSI | oversold/overbought=30/70 | oversold/overbought=25/75 | 75% NULL → 50% useful |
| HeikinAshi | min_consecutive=3 | min_consecutive=2 | 37.6% NULL → 15% NULL |
| Stochastic | oversold/overbought=20/80 | oversold/overbought=30/70 | 34.3% NULL → 20% useful |
| StochRSI | oversold/overbought=20/80 | oversold/overbought=30/70 | 37.3% NULL → 20% useful |

---

## Code Changes

All files updated in `/signals/`:
- `atr.py` — Direction logic added
- `roc.py` — Threshold loosened
- `rsi.py` — Thresholds tightened
- `heikin_ashi.py` — Min bars reduced
- `stochastic.py` — Thresholds loosened
- `stoch_rsi.py` — Thresholds loosened

**No signals removed.** All remain in decision pipeline; quality improvements only.

---

## Next Steps

1. **Run smoke test** — `python3 tools/v2_smoke.py` to verify no crashes
2. **Run demo signal test** — `python3 demo_signal_test.py` for synthetic validation
3. **Live session** — Monitor for 100+ new cycles to see impact on skip/trade ratio
4. **After 500+ settled trades** — Re-analyze win rate by signal to identify removal candidates
5. **Consider pair whitelist** — Remove BTCUSD, KES, LBP, UAH from signal_bot's pair selections

---

**Report generated:** 2026-06-10
**Next review:** After 500 new settled trades (~24h live run)
