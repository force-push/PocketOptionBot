# Shadow Trade Analysis — Signal Weighting & Confirmation
**Analysis date:** 2026-06-11 | **Sample:** 3,656 resolved trades (3,618 CALL/PUT with full signal breakdowns)
**Data:** 939 real · 1,101 majority_blocked · 847 expiry · 594 time_of_day · 175 legacy shadows
**Prior reports:** SIGNAL_VIABILITY_REPORT.md (854 trades, 06-09), SIGNAL_ANALYSIS_REPORT.md

---

## Purpose recap

The shadow trade program was set up to answer four questions:
1. **Signal weighting** — which signals deserve more weight, based on real outcomes?
2. **Majority check** — when 2 high-confidence signals are blocked by 5 opposing ones, who was right?
3. **Time-of-day** — do blocked hours actually lose, measured on fresh data?
4. **Expiry** — does a different trade duration win more than 30s?

We now have 4× the data of the original viability report. The answers below are
honest, including where they kill ideas we liked.

---

## Finding 1 — No signal has directional edge (now at 4× the sample)

Per-signal directional accuracy vs the **actual market move** (win → traded
direction was right; loss → opposite was right; draws excluded):

| Signal | Accuracy | n | High-conf slice |
|---|---|---|---|
| Parabolic_SAR | 50.6% | 3,618 | 51% @ n=3,451 |
| EMA_Cross | 50.2% | 3,618 | — (all low conf) |
| StochRSI | 50.1% | 2,693 | 52% @ n=1,536 |
| Stochastic | 50.0% | 2,766 | 50% @ n=1,811 |
| MACD | 49.7% | 3,618 | 50% @ n=3,472 |
| HeikinAshi | 49.6% | 2,577 | 50% @ n=1,500 |
| **ADX_DMI** | 49.5% | 3,585 | **57% @ n=110** ← see Finding 4 |
| RoC | 49.5% | 739 | 52% @ n=66 |
| ATR | 49.5% | 715 | 50% @ n=715 |
| RSI | 49.4% | 1,181 | 49% @ n=144 |
| Supertrend | 48.7% | 3,618 | 49% @ n=3,380 |

At n=3,618 the standard error is ±0.8%, so the entire table is statistically
flat. This replicates the 06-09 report exactly, on independent data.

## Finding 2 — Reweighting cannot fix this (tested, not assumed)

We trained signed per-signal weights on the first 60% of trades
(weight = accuracy − 0.5) and tested on the last 40%:

| Strategy | Out-of-sample accuracy |
|---|---|
| Trained weights | 48.9% (n=1,452) |
| Trained weights × confidence | 49.9% |
| Simple majority vote | 50.1% (n=976) |

**No linear weighting of the current 11 signals produces edge.** The signals
are highly correlated (all derived from the same 5-second price series, all
trend-following), so reweighting redistributes the same noise. This closes the
"squeeze the weightings" path with the current signal set — the inputs carry
no direction information at the 30s horizon, so no weighting can extract any.

## Finding 3 — The majority check is a no-op (verdict from 1,101 shadows)

| Group | n | WR |
|---|---|---|
| majority_blocked shadows (the trades we block) | 1,101 | **50.4%** |
| Real trades (the trades we take) | 939 | 50.1% |

The blocked trades win at exactly the same rate as the taken ones. The
majority gate neither protects nor costs us — because (Finding 1) signal count
carries no information. It can stay (harmless) or go; it doesn't matter.

## Finding 4 — The two patterns that DO repeat

These are the only two structures that replicated across independent days:

### 4a. Unanimity is contrarian (fade signal)
WR by number of signals agreeing with the traded direction:

| Agreeing | n | WR |
|---|---|---|
| 3 | 678 | 50.3% |
| 4 | 766 | 50.9% |
| 6 | 870 | 50.0% |
| 7 | 573 | 48.0% |
| **8** | **86** | **39.5%** |

Trades with ≥7 agreeing signals, split by day:
- 06-09: traded-direction WR **47.1%** (n=210) → fade = 52.9%
- 06-10: traded-direction WR **46.7%** (n=450) → fade = 53.3%

Combined: fading ≥7-agreement setups yields ~**53.2%** (n=660), just above the
52.1% break-even at 92% payout. This also matches the original report's
"perfect agreement = worse" finding on yet another independent sample — three
confirmations total. **Hypothesis:** all 11 signals are lagging
trend-followers; by the time every one of them aligns, the 5s-candle move is
exhausted and mean-reverts within the 30s window.
Caveat: statistical significance is marginal (p ≈ 0.10); edge after payout is thin.

### 4b. ADX_DMI at high confidence (the only >55% slice)
ADX_DMI with confidence ≥ 0.6, by day:
- 06-09: 56.8% accurate (n=37)
- 06-10: 57.5% accurate (n=73)

Combined **57.3% (n=110)** — the only signal slice above 55% that repeats.
ADX confidence scales with trend *strength* (ADX value), so this says:
direction signals only work when the trend is strong enough to persist 30s.
Caveat: fires on only ~3% of evaluations; p ≈ 0.13 — promising, unproven.

## Finding 5 — The time-of-day filter does NOT replicate ⚠

WR by hour, 06-09 vs 06-10/11 (includes blocked-hour shadows):

| UTC hour | 06-09 | 06-10/11 | Filter says |
|---|---|---|---|
| 06 | 50.0% (12) | 66.7% (36) | TRADE ✓ |
| 08 | 47.6% (42) | **26.7%** (15) | TRADE ✗ |
| 09 | 59.0% (39) | 50.5% (91) | TRADE ~ |
| 11 | 62.7% (51) | **50.9%** (228) | TRADE ✗ (was "90.9%" on n=11) |
| 12 | 43.8% (48) | **52.0%** (488) | BLOCKED ✗ |
| 13 | 49.5% (105) | 49.0% (764) | blocked ✓ |
| 14 | 47.9% (219) | 51.3% (448) | BLOCKED ✗ |
| 00 | — | 37.2% (43) | blocked ✓ |

The hour-to-hour profile flips between days. The flagship "90.9% at 11:00"
was n=11 noise — at n=228 it's 50.9%. Hour 12 was "terrible" (39.3%) and is
now 52.0% on 10× the sample. **The static hour filter is largely curve-fit to
one day's noise.** The blocked-hour shadows that made this test possible are
the program working as intended.

## Finding 6 — Expiry ladder: weak hint that longer is better

| Expiry | n | WR |
|---|---|---|
| 30s (real) | 2,802 | 50.3% |
| 50s | 237 | 44.7% |
| 80s | 236 | 47.0% |
| 128s | 191 | 46.1% |
| **216s** | **174** | **54.0%** |

216s is the best cell and 50s the worst, but n is small (±3.8% SE) and the
middle rungs sag — not a monotonic story yet. Worth growing n at 216s+.

---

## What this means (root cause)

All 11 signals read the same 5-second OTC price feed through trend-following
math. At a 30-second horizon that feed is ~50/50 (we measured the actual
market direction: 49.6% CALL / 50.4% PUT). The information simply isn't in
these inputs. The two repeating patterns are both *second-order*: exhaustion
(fade unanimity) and regime (only trust direction when ADX trend strength is
high). Both point the same way — **the edge, if any, is in when NOT to follow
the signals, not in how to weight them.**

---

## Recommendations (for discussion — nothing implemented yet)

1. **Stop tuning weights on the current signal set.** Tested out-of-sample;
   it cannot work. This retires the original signal-weighting feature as
   specified (weights ∝ accuracy) — the accuracies are all 0.5.

2. **Shadow-test a FADE rule** (new `shadow_kind="fade"`): when ≥7 signals
   agree on a direction, place a shadow in the *opposite* direction.
   Target: ~500 fade shadows. Gate to promote to real: WR ≥ 54% sustained.
   This is the strongest candidate (3 independent confirmations, ~53% now).

3. **Shadow-test an ADX-regime gate** (new `shadow_kind="adx_regime"`): only
   trade signal direction when ADX_DMI confidence ≥ 0.6. Currently ~57% but
   only n=110 — need ~400 more before trusting it. Could combine with (2):
   follow direction in strong trend, fade unanimity otherwise.

4. **Replace the static time-of-day filter with a rolling window.** The fixed
   hour table is curve-fit. Options: (a) drop hour blocking entirely, keep
   shadows collecting; (b) rolling 7-day per-hour WR with a minimum-n
   requirement before an hour can be blocked/promoted. The current filter is
   probably costing nothing but also saving nothing.

5. **Grow the 216s expiry sample** — bias the expiry ladder toward longer
   durations (e.g. [216, 300]) to resolve the longer-is-better hint.

6. **Longer term:** if fade + ADX-regime don't clear break-even, the honest
   conclusion is that this feed at 30s is unpredictable with price-derived
   indicators, and edge must come from elsewhere (payout selection, different
   horizon, or different instruments).

### Suggested sequence
Week 1: implement fade + adx_regime shadows (demo, zero risk), switch expiry
ladder to [216, 300], leave time filter as-is. Week 2: review — promote
whichever clears its gate to real trades; redesign time filter to rolling.

---

## Addendum (2026-06-11): Correlation structure — what "7 agree" really means

Pairwise direction-agreement across 3,911 decision rows shows the 11 signals
collapse into **two anti-correlated factors**:

**Factor 1 — trend bloc (7 signals, agree 57–94% with each other):**
MACD, Parabolic_SAR, EMA_Cross, ADX_DMI, HeikinAshi, RoC, Supertrend.
(MACD~PSAR 89.7%, ADX~EMA 87.8%, HA~RoC 96.8%)

**Factor 2 — oscillator bloc (3 signals, near-duplicates of each other):**
RSI ~ Stochastic **99.8%**, StochRSI ~ Stochastic 91.8%.
RSI ~ Stochastic are literally the same signal measured twice.

**The blocs are near-perfect inverses:** RSI agrees with MACD/PSAR/EMA only
0–2% of the time (oscillators fire contrarian-to-trend by construction:
"oversold → CALL" while trend says PUT). Mean pairwise correlation across all
signals ≈ 0 only because the two blocs cancel.

**Therefore "≥7 agree" is not 7 independent confirmations — it requires the
oscillator bloc to flip and join the trend bloc**, which only happens when
price is simultaneously trending hard AND at an oscillator extreme. That is
the textbook definition of an overextended/exhausted move — and the data
shows it mean-reverts (39.5% WR at 8-agree). The unanimity-fade finding is
the correlation structure speaking, not an anomaly.

**Practical implications:**
- Effective signal count is ~2, not 11. The agreement gate can be satisfied
  by RSI+Stochastic alone — one signal counted twice.
- Adding more price-derived trend or oscillator indicators adds redundancy,
  not information.
- Orthogonality must come from different *information sources*: process
  statistics (autocorrelation, variance ratio, run lengths), volatility
  regime, cross-pair divergence, candle microstructure — not more indicator
  variants on the same 5s series.

### Recommended next diagnostic (before building any new signal)
Run a one-off statistical profile of the raw 5s candle feed per pair:
lag-1..5 return autocorrelation, Lo–MacKinlay variance ratio, and
run-length distribution (P(reversal | N same-color candles)). If lag-1
autocorrelation is negative (mean-reverting process), fade-style entries are
structurally correct and momentum can never work at this horizon — settling
the strategy direction once, from the generating process itself.

---

## Addendum 2 (2026-06-11): Feed process diagnostics — the verdict

Ran `tools/feed_diagnostics.py` over 15 pairs × 3 timeframes (5s/30s/60s,
~150 candles each, pooled):

| Timeframe | lag-1 autocorr (pooled ± SE) | VR(2) | VR(6) |
|---|---|---|---|
| 5s | **−0.019 ± 0.022** | 0.98 | 1.00 |
| 30s | +0.004 ± 0.024 | 1.00 | 1.07 |
| 60s | +0.006 ± 0.021 | 1.01 | 0.97 |

**Verdict: random walk at every tested scale.** No pooled linear structure.
The bound this puts on ANY strategy that reads price history linearly:
directional accuracy ≈ 50% + ρ/π — with |ρ| ≤ ~0.04 (our upper bound), the
ceiling is ≈ **51.3%**, below the 52.1% break-even at 92% payout. This is
the process-level explanation for every 50% result in this report.

**Three secondary findings:**

1. **Cross-pair spread is wide but consistent with noise at one window:**
   OMRCNY −0.181, USDJPY −0.139 (fade-ish) vs EURJPY +0.101, AUDCAD +0.095
   (momentum-ish). Single-window SE is ±0.082, so persistence must be tested
   with repeated windows → now collected automatically (see below).
2. **The candle history endpoint returns flat OHLC** (open==high==low==close
   on every candle — snapshots, not true candles). Candle-anatomy signals
   (wicks, bodies, raw candle color) are structurally degenerate on this
   feed. HeikinAshi still works (recursive transform), but no signal should
   rely on intra-candle shape.
3. **The only non-null cell anywhere: lag-2 autocorr at 30s = +0.061 ± 0.025**
   (2.4σ) — a faint momentum echo at the 60–90s horizon. Weak, but it points
   the same direction as the 216s expiry result (54%). Longer horizons look
   marginally less random than 30s.

**Continuous per-pair profiling now live:** `_record_feed_stats()` in
`strategy/manager_v2.py` piggybacks the live loop's candle fetches (every
10th cycle, zero extra API load) and appends per-pair ac1/ac2/VR(2) windows
to `data/feed_stats.jsonl`. Within a day this gives hundreds of windows per
pair — enough to identify pairs with *persistent* negative autocorrelation
(structural fade candidates) vs noise.

**Strategic conclusion:** price history alone cannot clear break-even at the
30s horizon on this feed. The surviving paths: (a) per-pair pockets of
mean-reversion if feed_stats confirms persistence, (b) longer expiries
(216s/300s ladder already biased), (c) the fade/adx_regime exhaustion
patterns which are *nonlinear* conditions not bounded by the lag-1 result.

---

## Addendum 3 (2026-06-11): First live checkpoint — the sign flip

~12 hours after implementing the fade/adx experiments:

| Experiment | Result | Gate | Verdict so far |
|---|---|---|---|
| fade (≥7 agree → opposite) | **44.8%** (158/353), declining (46.6% → 42.9% by half) | ≥54% over 500 | **failing** |
| fade on 8+-agree | 38.9% (21/54) | — | failing hard |
| adx_regime (conf ≥0.6 → follow) | 47.1% (41/87) | ≥55% over 400 | below water |
| FOLLOW ≥7-agree (concurrent, gate-passing pairs) | **56.7%** (115/203) | — | the mirror image |
| time_of_day hours 12–16 | 46.6–53.2% per hour | — | hours ≈ coin flip, confirmed |
| expiry 216s / 300s since rebias | 36.4% (22) / 31.6% (19); all-time 216s regressed 54% → 52% | — | longer-horizon hint weakening |

**The key observation: unanimity flipped sign.** Retrospectively (06-09/06-10
data), following ≥7-agreement won 46.7–47.1% — so fading it looked right.
Live (06-10 evening onward), following the same condition wins **56.7%** and
fading it loses at 44.8%. Two independently-placed trade populations (fade
shadows vs follow trades) agree with each other — the *pattern itself
reversed direction* within ~24 hours.

This is the same failure mode as the time-of-day filter (Finding 5): an edge
measured on one day's data inverts on the next. Combined with the
random-walk process verdict (Addendum 2), the picture is now coherent:

> **Every conditional edge measurable on this feed is non-stationary.** The
> feed is a random walk whose local quirks drift faster than we can collect
> the samples needed to confirm them. Chasing the current "follow unanimity
> at 56.7%" would be curve-fitting the same trap, one day later.

**The one avenue still genuinely open:** per-pair process persistence from
the continuous profiler. Early (overlapping-window caveat — SEs understated):
#AAPL ac1 −0.061±0.018, EURJPY +0.084±0.024, #TSLA +0.089±0.036. If specific
pairs hold a stable autocorrelation sign over multiple days of
non-overlapping windows, that is a *structural* property of how their feed
is generated, not a drifting conditional — and it would survive where every
indicator-level edge has died.

**Recommendation:** let fade/adx run to their gates for completeness (they
will fail absent a reversal), make no promotions, and reconvene on the
feed_stats per-pair data after 24–48h. If no pair shows stable process
character, the honest endpoint is: this feed at ≤300s horizons is
engineered to be unpredictable, and the bot's value is as a research
harness, not a profit engine.
