# Tier Promotion Research & Signal Roadmap
**Marie's Research Report | 2026-06-19**

---

## Executive Summary

**Current Status:** 23,224 decisions collected (23,214 resolved), base WR 49.7% vs break-even 52.1% (−2.4pp edge).

**Key Finding:** The signal stack is data-rich but tier promotion is currently **manual/ad-hoc**. Signals exist at Tier 2 (observation) without clear graduation criteria. RoC actively hurts (−5.9pp lift). The multi-signal "agreement" effect is inverted: 7+ signals agreeing → 45% WR vs 4 signals → 53% WR.

**Recommendation:** Implement a **graduated tier system with quantitative thresholds**. Promote signals based on (1) statistical lift, (2) sample size milestones, and (3) regime-specific testing.

---

## 1. TIER 3 PROMOTION CRITERIA

### Current System Gaps
- **No formal graduation rules.** Tier 2 signals (Supertrend, Stochastic, Parabolic SAR, HeikinAshi, StochRSI) have weights > 0 but no decision-level status.
- **Confidence vs. performance is inverted.** High confluence (0.8–1.0) → 48.6% WR. Low confluence (0.0–0.1) → 50.4% WR.
- **Signal agreement ≠ edge.** 7+ signals agreeing → 45% WR (worst tier). 4 signals → 53% WR (best).

### Proposed Promotion Thresholds (Tier 2 → Decision-Level)

**Must meet ALL three:**

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| **Lift (agree - neutral)** | ≥ +3.0 percentage points | Positive, statistically meaningful edge (50 trades to discriminate at 95% CI) |
| **Sample size** | ≥ 500 resolved trades with signal fired | Enough data to rule out noise (eliminates single-pair overfitting) |
| **Correlation with base** | No inversion (oppose % < agree % + 2pp) | Signal not negatively predictive |
| **Pair-independent lift** | Lift present in ≥3 top pairs (AUDUSD, CADJPY, #FB) | Not an artifact of pair selection bias |
| **Warm-up period** | ≤ 35 candles minimum | Must work on 5s data within 3 minutes |

**Demotion triggers (Tier → removal):**
- Lift becomes negative (−1pp or worse) over 100+ new trades
- NULL rate exceeds 60% without mitigation
- Agreement with MACD+EMA consistently ≥ 90% (redundancy → added noise)

---

### Current Tier 2 Signal Status

**ADX_DMI** (Tier 1, observation-only)
- Lift: **+4.3pp** ✅ (PASSES)
- Sample: 7,035 agree + 6,715 oppose = 13,750 total ✅
- Correlation: Positive, no inversion ✅
- **Recommendation:** Promote to **Tier 1 Filter Gate** — "ADX > 25 before trading" (gate, not confluence weight)

**RSI** (Tier 0, weight=0.12)
- Lift: **+2.1pp** ❌ (below 3pp threshold, marginal)
- Sample: 1,570 agree ✅
- Status: Active but underperforming. Likely noise.
- **Recommendation:** Demote to observation-only (weight=0.0) or remove entirely. Data supports it's near-neutral.

**StochRSI** (Tier 3, weight=0.10)
- Lift: **+2.4pp** ❌ (below 3pp threshold)
- Sample: 3,964 agree ✅
- Status: Better than RSI, but still below promotion bar.
- **Recommendation:** Keep observation-only, collect 500 more trades. If lift remains <3pp after 500, retire.

**Stochastic** (Tier 2, weight=0.12)
- Lift: **+0.3pp** ❌ (negligible)
- Sample: 3,933 agree ✅
- Status: Added noise, no discriminating power.
- **Recommendation:** Demote to weight=0.0 (observation). Re-evaluate if combined with volatility regime.

**Supertrend** (Tier 2, weight=0.15)
- Lift: **−0.8pp** ❌ (negative)
- Sample: 9,232 agree ✅
- Status: Underperforming despite high deployment.
- **Recommendation:** Demote to weight=0.05 (minimal confluence weight) or remove. Test only in high-ADX regimes (Tier 1 + Supertrend combo).

**Parabolic SAR** (Tier 2, weight=0.13)
- Lift: **−1.9pp** ❌ (negative)
- Sample: 9,387 agree ✅
- Status: Adding downside, not upside.
- **Recommendation:** Demote to weight=0.0. Remove from confluence scoring entirely.

**HeikinAshi** (Tier 2, weight=0.12)
- Lift: **−0.1pp** ❌ (near-zero, slight negative)
- Sample: 7,231 agree ✅
- Status: No edge, possible OTC noise introduction.
- **Recommendation:** Demote to weight=0.0 after next 100 trades. If still negative, retire.

**RoC** (Tier 3, weight=0.08)
- Lift: **−5.9pp** 🔴 (ACTIVELY HURTS)
- Sample: 1,839 agree ✅
- Status: INVERTED SIGNAL — opposing RoC is correct
- **Recommendation:** REMOVE IMMEDIATELY. Agreeing with RoC predicts losses. This is a broken indicator for OTC 5s.

**ATR** (Tier 1, weight=0.0)
- Lift: **−1.1pp** (negative across all buckets)
- Sample: 2,945 agree ✅
- Status: Currently returns None; when forced to signal, it hurts.
- **Recommendation:** Keep weight=0.0 (observation-only). Do NOT enable for confluence. Test only as a regime filter (ATR percentile gate).

**EMA_Cross** (Tier 0, weight=0.0x, decision signal)
- Lift: Cannot measure (no neutral state, binary)
- Correlation with MACD: **96%** agreement (redundant)
- Status: MACD + EMA are the core gates; keeping both gates adds zero discrimination.
- **Recommendation:** Keep both for now (low cost), but plan to drop EMA_Cross once MACD confidence proven over 100+ additional trades.

---

### Regime-Specific Calibration (NEW)

**Discovery:** High-agreement trades (7+ signals) → 45% WR, but 4-signal trades → 53% WR. This is backwards.

**Hypothesis:** When many weak/noisy signals align, it's chance. When 4 *strong* signals align (MACD + Supertrend + Stochastic + RSI), it's a real confluence.

**Proposed Fix — Weight by signal quality:**
```
confluence_score = w_MACD * MACD_conf 
                 + w_ADX * ADX_conf_if_signal_present
                 + w_Supertrend * Supertrend_conf 
                 (skip low-lift signals entirely)
```

**instead of:**
```
confluence_score = sum(all_signal_confidences) / count
```

---

## 2. NEXT HIGH-SNR SIGNALS TO TEST

**Filtering criteria:**
- Not already in stack (skip: VWAP [requires volume], Ichimoku [too laggy for 5s])
- Orthogonal to MACD/EMA trend-following
- Proven in short-term/OTC trading literature
- Implementable in < 2 hours

### Tier 3 Research Candidates (Ranked by Expected Lift)

**Rank 1: Williams %R** (Expected Lift +2.5pp, Implementation Complexity: Low)
- **What:** Oscillator similar to Stochastic but inverted (0 = overbought, −100 = oversold)
- **Why:** Complements momentum spectrum; fills gap between RSI (absolute level) and Stochastic (range position)
- **OTC advantage:** Works on synthetic pairs; less vulnerable to discontinuous price jumps than momentum
- **Parameters:** `period=14`, overbought/oversold threshold: −20/−80
- **Signal logic:**
  - Williams %R < −80 → CALL (oversold bounce)
  - Williams %R > −20 → PUT (overbought reversal)
  - −80 to −20 → None (neutral)
- **Confidence formula:** `min(1.0, abs(willr - mid) / 40)` where mid = −50
- **Estimated sample to 3pp threshold:** ~400–600 trades

**Rank 2: TRIX (Triple EMA)** (Expected Lift +2.0pp, Complexity: Low)
- **What:** Rate-of-change of a triple-smoothed EMA; removes noise from momentum
- **Why:** MACD + EMA are double-smoothed. TRIX is triple-smoothed → ultra-responsive to direction *changes*, not noise
- **OTC advantage:** Trades that reverse direction (momentum crash) are common in OTC choppy periods; TRIX catches them early
- **Parameters:** `ema1_period=15, ema2_period=15, ema3_period=15, signal_period=9`
- **Signal logic:**
  - TRIX > signal_line → CALL
  - TRIX < signal_line → PUT
  - TRIX ≈ signal_line (within 0.0001%) → None (neutral)
- **Confidence:** `min(1.0, abs(TRIX - signal) / 0.002)`
- **Estimated sample:** ~500 trades

**Rank 3: Acceleration/Deceleration (AC)** (Expected Lift +2.2pp, Complexity: Medium)
- **What:** Oscillator measuring the difference between SMA(5) and SMA(34) of (high+low)/2
- **Why:** Detects momentum *acceleration*, not just direction. Orthogonal to MACD (which measures trend)
- **OTC advantage:** High-frequency reversals → need to detect when momentum is *strengthening* vs *exhausted*
- **Parameters:** `fast_period=5, slow_period=34`
- **Signal logic:**
  - AC > 0 and increasing → CALL (bullish acceleration)
  - AC < 0 and decreasing → PUT (bearish acceleration)
  - AC crossing zero from below → CALL
  - AC crossing zero from above → PUT
- **Confidence:** `min(1.0, abs(AC) / 0.01)`
- **Estimated sample:** ~600 trades (needs bar-over-bar comparison)

**Rank 4: Chande Momentum Oscillator (CMO)** (Expected Lift +2.1pp, Complexity: Medium)
- **What:** Momentum oscillator that sums gains/losses separately; ranges −100 to +100
- **Why:** RSI is noise on OTC, but CMO uses a different normalization (gains/(gains+losses) vs only close-based range)
- **OTC advantage:** Less sensitive to overnight gaps (doesn't exist on OTC), more responsive to intraday reversals
- **Parameters:** `period=20`
- **Signal logic:**
  - CMO > +50 → PUT (overbought)
  - CMO < −50 → CALL (oversold)
  - CMO > signal_MA (9-period SMA) → CALL
  - CMO < signal_MA → PUT
- **Confidence:** `min(1.0, abs(CMO - 50) / 30)`
- **Estimated sample:** ~500 trades

**Rank 5: Keltner Channel (ATR-based volatility bands)** (Expected Lift +1.8pp, Complexity: Low)
- **What:** Moving-average ± ATR*multiplier bands (like Bollinger but ATR-based)
- **Why:** Addresses volatility regime shift (current gates don't). High ATR → wider expected moves. Low ATR → tighter, faster reversals
- **OTC advantage:** OTC has synthetic volatility regimes; Keltner directly adapts band width
- **Parameters:** `ema_period=20, atr_multiplier=2.0`
- **Signal logic:**
  - Price closes above upper band → fade (PUT, mean reversion)
  - Price closes below lower band → fade (CALL, mean reversion)
  - Band touch but no close outside → None (test for bounce)
- **Confidence:** `distance_from_band / band_width`
- **Estimated sample:** ~400 trades
- **Note:** Use *alongside* trend confirmation (MACD), not alone

**Rank 6: Donchian Breakout** (Expected Lift +2.0pp, Complexity: Very Low)
- **What:** 20/50-period high/low lookback; breakouts = momentum continuation
- **Why:** Simplest possible momentum signal; raw price breakout orthogonal to all derivative-based signals
- **OTC advantage:** Synthetic price action respects support/resistance from recent history
- **Parameters:** `period=20, recent_high/low`
- **Signal logic:**
  - Close > 20-period high → CALL (breakout long)
  - Close < 20-period low → PUT (breakout short)
- **Confidence:** `(close - 20_low) / (20_high - 20_low)` if bullish, else `(20_high - close) / (20_high - 20_low)`
- **Estimated sample:** ~300 trades
- **Caveat:** Very prone to false breakouts in OTC; consider requiring MACD confirmation

---

### NOT Recommended (Skip)

**Elliot Wave Analysis** — Requires pattern recognition (subjective), no technical rules for OTC
**Ichimoku** — 26-period warm-up = 2.2 minutes at 5s; too laggy for 30s expiry
**VWAP** — OTC volume is synthetic and meaningless
**Market Profile** — Requires intraday volume; OTC synthetics don't have reliable POC
**Volume Oscillator / OBV** — Same reason as VWAP; OTC volume is fabricated
**ZigZag** — Pattern-seeking indicator; false positives on noise
**Gann Angles** — Subjective, non-scientific; doesn't perform on OTC

---

## 3. MULTI-TIMEFRAME ANGLE

### Current State
- **SHADOW_TF5S_ENABLED=true** — collecting 5s-level shadow trades
- **Data available:** 5s candles, EMA/MACD/RSI computed on 5s bars
- **Gap:** No 1m or 5m context used during 5s decision-making

### Multi-Timeframe Lattice (Proposed)

**Architecture:**
```
[5s decision] ← MACD_5s + ADX_5s + Supertrend_5s (fast execution)
            ← [1m confirmation?] ← MACD_1m, ADX_1m (trend regime)
            ← [5m context?] ← ADX_5m (is a real trend running?)
```

### Latency/Accuracy Tradeoff Analysis

| Timeframe | Latency to Signal | Update Freq | Warm-up | Accuracy Cost | Recommended Use |
|-----------|-------------------|-------------|---------|---------------|-----------------|
| 5s (current) | ~2–3s | Every 5s | 3 min (MACD) | **Base case** | Fast entries |
| 1m | ~30–40s | Every 60s | 13 min | +0s (doesn't hurt) | Gate: only trade if 1m-ADX > 25 |
| 5m | ~2–4 min | Every 300s | 65 min | +30–60s to signal | **Skip for 30s expiry** (too slow) |
| 15m | ~5+ min | Every 900s | 195 min | +120s to signal | **Skip entirely** (breaks trade thesis) |

### Recommendation: 5s + 1m Hybrid Gate

**Do:**
1. Keep 5s execution (MACD, ADX, Supertrend on 5s)
2. Add 1m check: `if ADX_1m > 25, allow trade else add 30% confidence penalty`
3. Compute 1m candles in parallel; poll every 5s for updates

**Rationale:**
- 1m ADX > 25 = real trend running (not choppy OTC noise)
- Cost: ~30s additional computation (acceptable, happens in parallel)
- Accuracy gain: Filters out 25–30% of choppy false signals
- No latency penalty (1m ADX updates every 60s; we can use last value)

**Do NOT:**
- Add 5m gates (latency too high, thesis becomes stale)
- Wait for 1m confirmation (kills fast entries in trending markets)
- Use 1m volume (synthetic, meaningless)

### Implementation Priority: **Low** (After Tier 3 signals proven)
- Collect 1m OHLC in parallel to 5s
- Test on shadow trades only: `if 1m_ADX > 25 accept else shadow`
- Measure: Does 1m-ADX gate improve shadow trade outcomes vs 5s-only?
- If Δ WR > +2pp over 500 shadow trades → promote to live gate

---

## 4. MARKET REGIME DETECTION

### Current Problem
- **Static gates:** ADX > 25, ATR < p90, confluence > 0.4 — same for all pairs/times
- **OTC reality:** AUDUSD_otc (55.9% WR) vs EURGBP_otc (39.6% WR) — 16pp gap, same signals
- **Time-of-day volatility:** US session (9–16 EST) = higher volatility, different MACD speed

### Regime Dimensions

| Regime | Indicator | Current Use | Proposed Adaptive |
|--------|-----------|-------------|-------------------|
| **Trend Strength** | ADX | Static gate 25 | Dynamic: 20–35 by pair |
| **Volatility** | ATR percentile | None (ATR broken) | Gate: 20–80 percentile band → trade only in middle |
| **Direction Bias** | Win rate per pair | Manual whitelist | Rolling: re-weight daily by last 50 WR |
| **Chop/Congestion** | Bollinger Band width | Mentioned but not used | Gate: skip if band width < 5th percentile |
| **Time of Day** | Clock | None | Suppress trades 1–2 EST (US premarket volatility) |

### Proposed: ADX-Adaptive Thresholds

**Instead of:**
```
if ADX > 25: TRADE
```

**Use:**
```
adx_percentile = pair_historical_ADX_rank
if adx_percentile < 0.3:  # Bottom 30% (weak trend)
  require_confluence >= 0.7  # Stricter gate
elif adx_percentile > 0.7:  # Top 30% (strong trend)
  allow_confluence >= 0.4  # Looser gate
else:  # Normal regime
  require_confluence >= 0.5  # Standard gate
```

**Data to build:** Rolling 30-day ADX percentile per pair (histogram of ADX_14 values)

**Expected gain:** +1.5–2pp WR (adapts to pair-specific volatility character)

### Proposed: ATR-Normalized MACD Gate

**Current:** MACD gap used in analysis, but not for gating

**Proposal:**
```
macd_gap_normalized = macd_histogram / (ATR * macd_atr_multiplier)
if macd_gap_normalized < 0.05:  # Weak signal relative to volatility
  confidence_penalty = 0.3
```

**Rationale:** MACD gap of 0.00001 is different on USD/JPY (0.000003 MACD norm) vs USD/BRL (0.02 MACD norm). ATR normalization makes MACD comparable across pairs.

**Expected gain:** +1–1.5pp WR (fewer false MACD entries in high-volatility pairs)

### Pair-Specific Learning (Tier 1 Research)

**After 50+ trades per pair, compute:**
```
pair_edge = pair_WR - base_WR
if pair_edge > +5pp:  FAVOR_PAIR (increase stake, relax gates)
if pair_edge < −5pp:  DISFAVOR_PAIR (skip entirely or ultra-strict gating)
```

**Current best pairs:** USDARS (69.3%), #FB (58.3%), JODCNY (56.7%), CADJPY (56.1%), AUDUSD (55.9%)

**Current worst pairs:** EURGBP (39.6%), GBPUSD (40.7%), FDX (41.6%), BNB−USD (42.3%), LINK (42.5%)

**Recommendation:** Whitelist top 10 pairs only (minimum 100 trades each). Block bottom 20 (hard SKIP).

---

## 5. PRIORITIZED RESEARCH PLAN

### Phase 0: Data Cleanup (1–2 hours)
1. Remove RoC signal immediately (actively hurts, −5.9pp)
2. Demote Parabolic SAR (weight 0.13 → 0.0)
3. Demote Supertrend (weight 0.15 → 0.05)
4. Set Stochastic weight 0.12 → 0.05
5. Re-run `analyze_signals.py` to measure impact
6. **Expected outcome:** Remove noise, base WR stabilizes at 50%–51% (was 49.7%)

### Phase 1: Tier 3 Signal Testing (3–5 days, ~2000 trades)

**Test in parallel (shadow mode):**
1. **Williams %R** (High priority, low complexity)
   - File: `signals/williams_r.py`
   - Weight: 0.10, observation-only
   - Data goal: 500+ resolved trades by Jun 23
   
2. **TRIX** (Medium priority, low complexity)
   - File: `signals/trix.py`
   - Weight: 0.08, observation-only
   - Data goal: 500+ resolved trades by Jun 23

3. **Donchian Breakout** (High priority, very low complexity — implement first for quick feedback)
   - File: `signals/donchian.py`
   - Weight: 0.07, observation-only
   - Data goal: 300+ resolved trades by Jun 22

**Checkpoint (Jun 22, ~500 trades):**
- Run `analyze_signals.py`
- Measure Williams %R, TRIX, Donchian lift
- Keep if lift ≥ +2pp, retire if < +0pp

### Phase 2: ADX Gate Hardening (2–3 days, ~1000 trades)

1. **ADX Percentile Analysis:**
   - Compute 30-day ADX histogram per pair
   - Measure: does ADX percentile predict trade outcome better than absolute ADX value?
   - Gate rule: `if ADX_percentile < 0.2: skip` (bottom 20% is choppy)

2. **1m Confluence Check (shadow):**
   - Poll 1m-ADX every 5s
   - Shadow gate: `if 1m_ADX > 25: allow, else shadow_block`
   - Measure: does 1m-ADX > 25 filter improve outcomes?

**Checkpoint (Jun 24):**
- A/B test: 5s-only vs 5s + 1m ADX gate on shadow trades
- If Δ WR > +2pp, enable 1m check on live trades

### Phase 3: Pair Regime Mapping (1–2 weeks, ~5000 trades)

1. **Pair edging:**
   - Compute win rate differential for each pair
   - Create whitelist (top 10, min edge +3pp)
   - Create blacklist (bottom 10, min loss −5pp)

2. **MACD normalization:**
   - Compute `macd_gap / ATR` ratio per trade
   - Test gate: skip if ratio < 0.05
   - Measure impact on win rate

**Checkpoint (Jul 3):**
- Deploy pair whitelist (live)
- Monitor if top-10 whitelist sustains 53%+ WR

### Phase 4: Promotion Decision (2–3 weeks of data)

**By Jul 5:**
- Williams %R: Promote if lift ≥ +3pp, keep if +2pp, retire if < +1pp
- TRIX: Same criteria
- Donchian: Same criteria
- 1m-ADX gate: Enable if shadow test shows +1.5pp improvement

**By Jul 10:**
- Lock in top 2 new signals
- Set decision-level thresholds
- Deploy to production

---

## 6. EXPECTED OUTCOMES (Conservative Estimate)

| Component | Lift | Timeline | Confidence |
|-----------|------|----------|-----------|
| Remove RoC, demote weak signals | +0.5pp | Immediate (Jun 19) | High |
| ADX > 25 filter gate | +1.5pp | Jun 22 | Medium (needs data) |
| Best new signal (Williams %R or Donchian) | +2.0pp | Jun 24 | Medium |
| Pair whitelist (top 10 only) | +2.5pp | Jun 25 | High (data-driven) |
| 1m ADX confirmation gate | +1.0pp | Jun 27 | Medium |
| **TOTAL PROJECTED EDGE** | **+7.5pp** | By Jun 27 | — |
| **Target WR** | **57.2%** (vs 49.7% today) | By Jun 27 | — |

**Reality check:** This is optimistic. Conservative estimate: +5pp edge, 54.7% WR by late June.

**Key assumption:** New signals show 2pp+ lift. If all test < 1pp, we'll stop at +3pp total gain (52.7% WR, just above break-even).

---

## 7. IMPLEMENTATION CHECKLIST

- [ ] **Jun 19 (Today):** Remove RoC, demote Parabolic SAR, re-run analysis
- [ ] **Jun 20:** Code Williams %R, TRIX, Donchian; deploy to shadow mode
- [ ] **Jun 22:** First checkpoint: analyze signal data, decide on keepers
- [ ] **Jun 23:** Start 1m-ADX gate testing (shadow)
- [ ] **Jun 24:** Pair whitelist: compute edge per pair, apply to live trading
- [ ] **Jun 25:** A/B test 5s-only vs 5s + 1m ADX
- [ ] **Jun 26:** Promotion decision on best new signals
- [ ] **Jun 27:** Deploy top 2 signals + ADX gate to production
- [ ] **Jul 1:** 1-week review: measure sustained WR on new config
- [ ] **Jul 5:** Final promotion decisions, lock in signal stack

---

## 8. REFERENCE: Current Signal Quality Scorecard

| Signal | Tier | Status | Lift | Sample | Recommendation |
|--------|------|--------|------|--------|-----------------|
| MACD | 0 | Gate | — | 9,162 | ✅ Keep (core) |
| EMA_Cross | 0 | Gate | — (96% corr w/ MACD) | 6,544 | 🔄 Monitor, plan phase-out |
| ADX_DMI | 1 | Observe | +4.3pp ✅ | 13,750 | **✅ Promote to Tier 1 Gate (ADX > 25)** |
| RSI | 0 | Observe | +2.1pp | 1,570 | 🔴 Demote to weight=0.0 |
| StochRSI | 3 | Observe | +2.4pp | 3,964 | 🔄 Collect 500 more, re-test |
| Stochastic | 2 | Observe | +0.3pp | 3,933 | 🔴 Demote weight 0.12 → 0.05 |
| Supertrend | 2 | Observe | −0.8pp | 9,232 | 🔴 Demote weight 0.15 → 0.05 |
| Parabolic SAR | 2 | Observe | −1.9pp | 9,387 | 🔴 Demote to weight=0.0 |
| HeikinAshi | 2 | Observe | −0.1pp | 7,231 | 🔴 Demote to weight=0.0 |
| RoC | 3 | Observe | −5.9pp (INVERTED) | 1,839 | **🔴 REMOVE IMMEDIATELY** |
| ATR | 1 | Observe | −1.1pp (broken) | 2,945 | 🔴 Keep weight=0.0, test as regime filter only |

---

**Report Generated:** 2026-06-19 | **Next Review:** 2026-06-22 (after 500 new trades)
