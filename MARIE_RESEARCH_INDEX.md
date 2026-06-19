# Marie's Research Index — Signal Stack Overhaul 2026-06-19
**Complete Research Deliverable for PocketOptionBot**

---

## 📑 Document Map

### Executive Summaries (Read These First)
1. **RESEARCH_SUMMARY_MARIE.md** — TL;DR of all findings, recommendations, and timeline
   - 5-min read
   - What to do, why, and by when
   - Expected outcomes and contingencies

2. **MARIE_RESEARCH_INDEX.md** — This file
   - Navigation guide for all research
   - Quick lookup by topic

### Full Research (Detailed Analysis)
3. **TIER_PROMOTION_RESEARCH.md** — Statistical foundations
   - Tier promotion criteria (3pp lift threshold, 500-sample rule)
   - Current signal scorecard (which signals pass/fail)
   - Multi-timeframe analysis (5s + 1m hybrid recommended)
   - Regime detection proposals (ADX percentile, MACD normalization)
   - 7.5pp projected edge breakdown

4. **NEXT_SIGNALS_IMPLEMENTATION.md** — Build-ready specifications
   - Code templates for Donchian, Williams %R, TRIX
   - Integration checklist
   - Testing workflow
   - Timeline and milestones
   - Expected impact per signal

### Implementation Ready (Copy & Paste)
5. **docs/tier3-signal-candidates.md** — Production-grade code
   - Complete Python implementations
   - Unit tests for each signal
   - Parameter tuning guidance
   - Gotchas and troubleshooting

6. **RESEARCH_ACTIONS_CHECKLIST.md** — Day-by-day action plan
   - Phase 0–5 (Jun 19–27)
   - Specific code changes and file locations
   - Testing procedures with SQL queries
   - Decision matrices (keep/retire signals)
   - Contingencies if things go wrong

---

## 🎯 Quick Start (Choose Your Path)

### "I want the TL;DR (5 min read)"
→ **RESEARCH_SUMMARY_MARIE.md**
- Headline: +5–7.5pp edge over 7 days
- Action: Remove RoC, add 3 new signals, whitelist pairs
- Timeline: Jun 19–27, shadow mode throughout

### "I want to understand the analysis (30 min read)"
→ **TIER_PROMOTION_RESEARCH.md** (all sections except appendices)
- Why current signals fail
- What makes a "good" signal (3pp lift threshold, 500 samples)
- Ranked candidates for testing
- Why multi-timeframe + regime detection matter

### "I want to code now (60 min to deploy)"
→ **docs/tier3-signal-candidates.md** + **NEXT_SIGNALS_IMPLEMENTATION.md** (Integration section)
- Copy code for Donchian, Williams %R, TRIX
- Modify main_v2.py
- Run smoke tests
- Deploy to shadow mode

### "I want step-by-step checklist (use daily)"
→ **RESEARCH_ACTIONS_CHECKLIST.md**
- Jun 19: RoC removal ✓
- Jun 20–21: Code new signals ✓
- Jun 22: First checkpoint (analyze, decide) ✓
- Jun 23–24: Gate hardening ✓
- Jun 25: Pair whitelist ✓
- Jun 26–27: Final promotion + deploy ✓

---

## 📊 Key Findings at a Glance

### Current Problems (Why we need this research)
1. **RoC is inverted** (-5.9pp lift) → actively hurts performance
2. **More signals = worse outcomes** (7 signals → 45% WR vs 4 signals → 53% WR)
3. **Static gates fail across pair spectrum** (AUDUSD 55.9% vs EURGBP 39.6% = 16pp gap)
4. **Current WR 49.7% is below break-even 52.1%** (−2.4pp edge)

### Proposed Solutions (In priority order)
1. **Remove noise immediately** (RoC, demote Parabolic SAR, Supertrend, Stochastic, HeikinAshi)
   - Est. impact: +0.5pp
   - Timeline: Jun 19 (1 hour)

2. **Test 3 high-SNR signals** (Donchian, Williams %R, TRIX)
   - Est. impact: +2.0–2.5pp each (if ≥+3pp lift)
   - Timeline: Jun 20–22 (shadow mode, 500 trades)

3. **Deploy pair whitelist** (trade top 10 pairs only, skip bottom 10)
   - Est. impact: +2.5pp
   - Timeline: Jun 25 (data-driven, live)

4. **Harden gates with regime adaptation** (ADX percentile, 1m confirmation, MACD normalization)
   - Est. impact: +2.0–3.0pp combined
   - Timeline: Jun 23–27 (shadow → live)

### Expected Outcome
- **Current:** 49.7% WR (−2.4pp vs break-even 52.1%)
- **Target:** 54.7–57.2% WR (+2.6–5pp edge)
- **Timeline:** 7 days (Jun 19–27)
- **Confidence:** Medium (signal lift predictions are estimates; actual depends on data)

---

## 📈 Decision Criteria (Tier Promotion Thresholds)

A signal **graduates** from observation (Tier 2) to decision-level (Tier 1) when:

| Criterion | Threshold | Why |
|-----------|-----------|-----|
| **Lift** | ≥ +3.0pp | Statistically meaningful edge |
| **Sample Size** | ≥ 500 resolved trades | Avoids overfitting |
| **No Inversion** | Oppose % < agree % + 2pp | Signal not negatively predictive |
| **Pair-Independent** | Lift in ≥3 major pairs | Not artifact of pair bias |
| **Warm-up** | ≤ 35 candles (3 min @ 5s) | Works within trade thesis |

**Demotion triggers:**
- Lift becomes negative over 100+ new trades
- Signal fires > 60% of time (dilutes confluence)
- >90% agreement with existing gate signals (redundant)

---

## 🔍 Current Signal Scorecard

| Signal | Lift | Sample | Verdict | Action |
|--------|------|--------|---------|--------|
| **MACD** | — | 9,162 | ✅ Core gate | Keep (gate only) |
| **EMA_Cross** | — (96% corr w/ MACD) | 6,544 | 🔄 Keep for now | Plan phase-out |
| **ADX_DMI** | **+4.3pp** ✅ | 13,750 | ✅ **PROMOTE** | **Tier 1 gate (ADX > 25)** |
| **RSI** | +2.1pp (below 3pp) | 1,570 | ❌ Demote | weight 0.12 → 0.0 |
| **StochRSI** | +2.4pp (below 3pp) | 3,964 | 🔄 Collect more | Keep obs, re-test 500 trades |
| **Stochastic** | +0.3pp (noise) | 3,933 | ❌ Demote | weight 0.12 → 0.05 |
| **Supertrend** | −0.8pp (negative) | 9,232 | ❌ Demote | weight 0.15 → 0.05 |
| **Parabolic SAR** | −1.9pp (negative) | 9,387 | ❌ Demote | weight 0.13 → 0.0 |
| **HeikinAshi** | −0.1pp (near-zero) | 7,231 | ❌ Demote | weight 0.12 → 0.0 |
| **RoC** | **−5.9pp (INVERTED)** 🔴 | 1,839 | 🔴 **REMOVE** | **Delete immediately** |
| **ATR** | −1.1pp (broken) | 2,945 | ❌ Demote | weight 0.0 (keep obs) |
| **Donchian** (NEW) | ~+2.0pp (est.) | TBD | ⏳ Test | Shadow mode Jun 20–22 |
| **Williams %R** (NEW) | ~+2.5pp (est.) | TBD | ⏳ Test | Shadow mode Jun 20–22 |
| **TRIX** (NEW) | ~+2.0pp (est.) | TBD | ⏳ Test | Shadow mode Jun 20–22 |

---

## 📋 Phase Breakdown

### Phase 0: Data Cleanup (Jun 19, 1 hour)
```
Remove RoC signal
Demote Parabolic SAR (0.13 → 0.0)
Demote Supertrend (0.15 → 0.05)
Demote Stochastic (0.12 → 0.05)
Demote HeikinAshi (0.12 → 0.0)
Expected lift: +0.5pp
```
**Files:** main_v2.py, signals/__init__.py

### Phase 1: New Signal Testing (Jun 20–22, shadow)
```
Code Donchian, Williams %R, TRIX
Deploy to shadow mode
Collect 500 resolved trades
Run analyze_signals.py
Decision: keep (≥+2pp lift) or retire (<+0.5pp)
Expected lift: +2.0–2.5pp (if signals pass)
```
**Files:** signals/donchian.py, signals/williams_r.py, signals/trix.py, main_v2.py

### Phase 2: ADX Hardening (Jun 23–24)
```
Analyze ADX percentile distribution per pair
Deploy 1m-ADX gate (shadow)
Measure: does 1m-ADX > 25 improve outcomes?
Expected lift: +1.0–1.5pp (if positive)
```
**Files:** main_v2.py, risk_manager.py

### Phase 3: Pair Regime (Jun 24–25)
```
Compute WR per pair (last 100+ trades)
Identify top 10, bottom 10 pairs
Deploy whitelist/blacklist
Expected lift: +2.5pp (from removing losers)
```
**Files:** .env (PAIR_WHITELIST, PAIR_BLACKLIST), main_v2.py

### Phase 4: Final Promotion (Jun 26–27)
```
Analyze all changes to date
Decide which new signals graduate to decision-level
Deploy final config to production
Expected combined lift: +5 to +7.5pp
```
**Files:** main_v2.py (final signal stack)

---

## 🔗 Cross-References

### By Question

**Q: How do I know when a signal is "good enough" to use in live trading?**
→ TIER_PROMOTION_RESEARCH.md § 1 (Tier 3 Promotion Criteria)
→ RESEARCH_SUMMARY_MARIE.md § 1 (Promotion Thresholds table)

**Q: What signals should I test next?**
→ TIER_PROMOTION_RESEARCH.md § 2 (Next High-SNR Signals, ranked 1–6)
→ docs/tier3-signal-candidates.md (complete code for top 3)

**Q: Why is pair selection so important?**
→ TIER_PROMOTION_RESEARCH.md § 4 (Pair-Specific Learning)
→ RESEARCH_SUMMARY_MARIE.md § Finding 2

**Q: Should I use 5m signals for 30s trades?**
→ TIER_PROMOTION_RESEARCH.md § 3 (Multi-Timeframe Angle)
→ Recommendation: NO, use 5s + 1m hybrid instead

**Q: How do I adapt gates for different market conditions?**
→ TIER_PROMOTION_RESEARCH.md § 4 (Market Regime Detection)
→ Recommendation: ADX percentile, MACD normalization, pair whitelisting

**Q: What code do I need to implement?**
→ docs/tier3-signal-candidates.md (copy-paste ready)
→ NEXT_SIGNALS_IMPLEMENTATION.md § Part 2 (Donchian, Williams %R, TRIX templates)

**Q: What's my day-by-day action plan?**
→ RESEARCH_ACTIONS_CHECKLIST.md (use as daily checklist Jun 19–27)

---

## 📊 Metrics to Track

| Metric | Current | Target | Checkpoint |
|--------|---------|--------|-----------|
| Base WR | 49.7% | 54.7%+ | Daily |
| Break-even threshold | 52.1% | — | Reference |
| Edge | −2.4pp | +2.5–5pp | Jun 27 |
| Confluence agreement lift | Anti-predictive | +3pp+ | Jun 22 |
| New signal lift (avg) | 0pp | +2pp each | Jun 22 |
| Top-10 pair WR | 55.9% (AUDUSD) | 53%+ avg | Jun 25 |
| ADX percentile gate impact | N/A | +1.5pp | Jun 24 |
| 1m-ADX gate impact | N/A | +1.0pp (if enabled) | Jun 24 |

---

## 🔴 Critical Decisions

### Jun 19 EOD: Cleanup Approval
- **Question:** Should we remove RoC and demote weak signals immediately?
- **Recommendation:** YES (low risk, high confidence based on data)
- **Contingency:** If cleanup reduces WR (unexpected), revert and investigate

### Jun 22 EOD: New Signal Verdict
- **Question:** Which of Donchian, Williams %R, TRIX should we keep?
- **Recommendation:** Keep any with ≥ +2pp lift, retire < +0.5pp
- **Contingency:** If all < +1pp, skip Phases 3–4, focus on pair whitelist alone

### Jun 24 EOD: 1m-ADX Gate?
- **Question:** Should we deploy 1m-ADX confirmation gate?
- **Recommendation:** YES if shadow test shows +1.5pp lift, NO otherwise
- **Contingency:** If negative, revert to 5s-only gating

### Jun 25 EOD: Pair Whitelist?
- **Question:** Should we hard-skip bottom 10 pairs?
- **Recommendation:** YES (high confidence, +2.5pp expected lift)
- **Contingency:** If top-10 whitelist crashes (zero trades), expand to top-20

---

## 🎓 Learning Resources

If you want deeper understanding:

1. **Why RoC is inverted on OTC:** Market microstructure research, bid-ask bounce
2. **Why multi-signal agreement backfires:** Curse of dimensionality, high correlation
3. **Why pair selection dominates:** Regime-dependent signals, pair-specific volatility
4. **Why ADX percentile matters:** Adaptive thresholds, pair-specific ADX distributions

See second brain `/second-brain/03-Projects/PocketOptionBot.md` for historical research notes.

---

## 📞 Who to Contact

- **Signal implementation questions:** See NEXT_SIGNALS_IMPLEMENTATION.md
- **Data analysis questions:** See TIER_PROMOTION_RESEARCH.md with actual analyze_signals.py output
- **Day-to-day progress:** See RESEARCH_ACTIONS_CHECKLIST.md
- **Final decisions:** See RESEARCH_SUMMARY_MARIE.md § Contingencies

---

## 📝 Document Status

| Document | Status | Last Updated | Owner |
|----------|--------|--------------|-------|
| RESEARCH_SUMMARY_MARIE.md | ✅ Complete | 2026-06-19 | Marie |
| TIER_PROMOTION_RESEARCH.md | ✅ Complete | 2026-06-19 | Marie |
| NEXT_SIGNALS_IMPLEMENTATION.md | ✅ Complete | 2026-06-19 | Marie |
| docs/tier3-signal-candidates.md | ✅ Complete | 2026-06-19 | Marie |
| RESEARCH_ACTIONS_CHECKLIST.md | ✅ Complete | 2026-06-19 | Marie |
| MARIE_RESEARCH_INDEX.md | ✅ Complete | 2026-06-19 | Marie |

---

## 🚀 Getting Started (Right Now)

1. **Read:** RESEARCH_SUMMARY_MARIE.md (5 min)
2. **Decide:** Phase 0 approval? (Remove RoC now or not?)
3. **Act:** If YES → follow RESEARCH_ACTIONS_CHECKLIST.md Phase 0
4. **Code:** Once approved, copy signal templates from docs/tier3-signal-candidates.md
5. **Deploy:** Shadow mode Jun 20, measure Jun 22, promote Jun 26–27

---

**Prepared by:** Marie, Research Specialist  
**Date:** 2026-06-19  
**For:** PocketOptionBot Signal Stack Overhaul  
**Timeline:** 7 days (Jun 19–27) to +5–7.5pp edge  
**Confidence Level:** Medium (signal lift estimates; actual depends on OTC response)

---

## File Locations

```
/Users/kym/code/openclaw/projects/PocketOptionBot/
├── RESEARCH_SUMMARY_MARIE.md          ← START HERE (TL;DR)
├── TIER_PROMOTION_RESEARCH.md         ← Full analysis
├── NEXT_SIGNALS_IMPLEMENTATION.md     ← Build specs
├── RESEARCH_ACTIONS_CHECKLIST.md      ← Daily actions
├── MARIE_RESEARCH_INDEX.md            ← This file
├── docs/
│   └── tier3-signal-candidates.md     ← Code templates
├── signals/
│   ├── macd.py, ema_cross.py, ...
│   ├── (donchian.py)                  ← Create Jun 20
│   ├── (williams_r.py)                ← Create Jun 20
│   └── (trix.py)                      ← Create Jun 20
├── main_v2.py                         ← Modify Jun 19 & 20
├── scripts/
│   └── analyze_signals.py             ← Run Jun 22
├── data/
│   └── decisions.db                   ← Metrics source
└── .env                               ← Update Jun 25
```

---

**END OF INDEX**
