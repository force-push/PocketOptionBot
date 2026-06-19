# Marie's Research Actions — Quick Checklist
**2026-06-19 → 2026-06-27**

---

## 🔴 IMMEDIATE (Today, Jun 19)

### Code Cleanup
- [ ] **Remove RoC signal entirely** (−5.9pp, actively hurts)
  - File: `signals/roc.py` or wherever RoC is initialized
  - Remove from `signals` list in `main_v2.py`
  - Verify: rerun bot, check `our_signal_breakdown` has no RoC

- [ ] **Demote Parabolic SAR** weight 0.13 → 0.0
  - Still record in breakdown, but no confluence contribution
  - Expected impact: +0.3pp (remove −1.9pp negative signal)

- [ ] **Demote Supertrend** weight 0.15 → 0.05
  - Keep some signal for observation, reduce confluence weight
  - Expected impact: +0.4pp (reduce −0.8pp negative signal)

- [ ] **Demote Stochastic** weight 0.12 → 0.05
  - Expected impact: +0.2pp (reduce +0.3pp noise)

- [ ] **Demote HeikinAshi** weight 0.12 → 0.0
  - Expected impact: +0.1pp (remove −0.1pp)

### Testing
- [ ] Run `python3 scripts/v2_smoke.py` — verify no crashes
- [ ] Monitor `data/decisions.db` — ensure writes are clean
- [ ] Check `our_signal_breakdown` in next 10 trades — should have no RoC, Parabolic SAR, reduced others

### Verify Impact
- [ ] After 100 trades, run `python3 scripts/analyze_signals.py`
- [ ] Confirm base WR rises from 49.7% → ~50.5% (expected)

---

## 🟡 PHASE 1: Code New Signals (Jun 20–21)

### Create Files
- [ ] **signals/donchian.py** (copy from `docs/tier3-signal-candidates.md`)
  - Estimated time: 30 min
  - Test locally: verify breakout detection works

- [ ] **signals/williams_r.py** (copy from docs)
  - Estimated time: 45 min
  - Test locally: verify oversold/overbought detection

- [ ] **signals/trix.py** (copy from docs)
  - Estimated time: 60 min
  - Test locally: verify triple-EMA + signal line logic

### Integration
- [ ] Update **main_v2.py**: import all 3 signals
- [ ] Add to `signals` list with weights:
  - Donchian: weight=0.07
  - Williams %R: weight=0.10
  - TRIX: weight=0.08
- [ ] Verify in `decision_signals`: these are NOT included (observation-only)

### Pre-Deployment Testing
- [ ] `python3 scripts/v2_smoke.py` — no crashes
- [ ] Run bot for 10 cycles, check log for new signals firing
- [ ] Inspect database: `SELECT COUNT(DISTINCT pair_api) FROM decisions;` → should be same as before

### Deploy
- [ ] Merge code to main branch (or deploy directly)
- [ ] Start bot in shadow mode (TRADE_MODE=DEMO)
- [ ] Monitor for 24 hours: check that signals are firing (not all NULL)

---

## 🟢 PHASE 2: Data Collection (Jun 22–23)

### Monitoring Checkpoint
- [ ] **Jun 22, 9am:** Check trade count
  - Goal: ≥ 500 new resolved trades since code deployment
  - If < 400: wait until Jun 22 5pm, then make decision

- [ ] **Jun 22, 5pm:** Run analysis
  ```bash
  python3 scripts/analyze_signals.py > analysis_jun22.txt
  ```

### Analysis
- [ ] Parse output for:
  ```
  Donchian        agree n     WR   neut n     WR   opp n     WR    lift
  Williams_R      ...
  TRIX            ...
  ```

- [ ] Calculate lift for each (agree WR − neutral WR):
  - Donchian: expect +1.5 to +2.5pp
  - Williams %R: expect +1.5 to +3.0pp
  - TRIX: expect +1.0 to +2.5pp

### Decision Matrix

| Signal | Lift ≥ +3pp | Lift +2 to +3pp | Lift +0.5 to +2pp | Lift < +0.5pp | Action |
|--------|---|---|---|---|---|
| Donchian | PROMOTE | KEEP OBS | KEEP OBS | REMOVE | ___ |
| Williams %R | PROMOTE | KEEP OBS | KEEP OBS | REMOVE | ___ |
| TRIX | PROMOTE | KEEP OBS | KEEP OBS | REMOVE | ___ |

- [ ] Fill in actual lift values from analysis
- [ ] Make decision: promote, keep observation, or remove each signal
- [ ] Update `main_v2.py`:
  - If PROMOTE: add to `decision_signals` set
  - If REMOVE: delete from signals list, remove weight

### Deploy Results
- [ ] If any signal removed: redeploy code, verify no crashes
- [ ] If any signal promoted: leave as-is, monitor in live trading

---

## 🟠 PHASE 3: Gate Hardening (Jun 23–24)

### ADX Percentile Analysis
- [ ] Query database for 30-day ADX history per pair:
  ```sql
  SELECT pair_api, 
         json_extract(data, '$.flip_metrics.adx') as adx,
         COUNT(*) as n
  FROM decisions 
  WHERE ts > datetime('now', '-30 days')
  GROUP BY pair_api
  ORDER BY pair_api;
  ```

- [ ] For each top pair (AUDUSD, CADJPY, #FB), compute:
  - ADX distribution (mean, min, max, 25th, 75th percentile)
  - Does ADX percentile predict WR better than absolute ADX?

### 1m-ADX Gate Testing (Shadow)
- [ ] **Jun 23:** Start collecting 1m candles in parallel
  - Modify data collection to compute 1m OHLC
  - Compute 1m-ADX every 5s (poll, don't wait for update)

- [ ] **Jun 24:** Deploy shadow gate:
  ```python
  if 1m_ADX > 25:
    allow_trade()
  else:
    shadow_skip("1m_adx_low")  # Record as shadow
  ```

- [ ] Collect 500 shadow trades (1m-ADX blocked vs allowed)

- [ ] Measure: Do trades with 1m-ADX > 25 have higher WR?
  ```sql
  SELECT 
    skip_reason,
    outcome,
    COUNT(*) as n,
    ROUND(100.0 * SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) / COUNT(*), 1) as wr
  FROM decisions 
  WHERE skip_reason LIKE '1m_adx%'
    AND outcome IS NOT NULL
    AND ts > datetime('now', '-24 hours')
  GROUP BY skip_reason, outcome;
  ```

### Decision: 1m Gate?
- [ ] If WR(1m-ADX > 25) − WR(1m-ADX ≤ 25) ≥ +1.5pp → enable for live
- [ ] If < +1.5pp → keep shadow-only, re-test after more data
- [ ] If negative → disable, no live deployment

---

## 🟠 PHASE 4: Pair Regime (Jun 24–25)

### Pair Win-Rate Analysis
- [ ] **Jun 24:** Compute WR per pair (last 100+ trades each):
  ```sql
  SELECT pair_api, 
         COUNT(*) as n,
         ROUND(100.0 * SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) / COUNT(*), 1) as wr
  FROM decisions 
  WHERE outcome IS NOT NULL
  GROUP BY pair_api
  ORDER BY wr DESC
  LIMIT 100;
  ```

- [ ] **Identify top 10 pairs** (edge ≥ +3pp above 49.7% base = ≥ 52.7% WR):
  - Expected top pairs: USDARS (69%), #FB (58%), JODCNY (57%), CADJPY (56%), AUDUSD (56%), etc.
  - Verify n ≥ 100 trades per pair (to avoid small-sample anomalies)

- [ ] **Identify bottom 10 pairs** (edge ≤ −5pp below base = ≤ 44.7% WR):
  - Expected worst pairs: EURGBP (40%), GBPUSD (41%), FDX (42%), BNB (42%), LINK (43%), etc.

### Whitelist/Blacklist Deployment
- [ ] Update **.env**:
  ```bash
  PAIR_WHITELIST="AUDUSD_otc,CADJPY_otc,#FB_otc,JODCNY_otc,..."  # Top 10
  PAIR_BLACKLIST="EURGBP_otc,GBPUSD_otc,FDX_otc,BNB-USD_otc,..." # Bottom 10
  ```

- [ ] Update **main_v2.py** (if needed):
  - Gate: skip if pair in BLACKLIST
  - Favor (increase stake 10%): if pair in WHITELIST
  - Expected impact: +2.5pp WR (remove losers, concentrate winners)

- [ ] Deploy to LIVE (not shadow)
- [ ] Monitor for 50+ trades: verify whitelist WR ≥ 54% (vs base 49.7%)

---

## 🟠 PHASE 5: Final Promotion (Jun 26–27)

### Decision Checkpoint
- [ ] **Jun 26, 9am:** Assess all Phases 1–4:

| Phase | Component | Status | Action |
|-------|-----------|--------|--------|
| 0 | Cleanup (RoC removed) | ✓ Done | — |
| 1 | Donchian | ✓/✗ Keep/Remove | ___ |
| 1 | Williams %R | ✓/✗ Keep/Remove | ___ |
| 1 | TRIX | ✓/✗ Keep/Remove | ___ |
| 3 | 1m-ADX gate | ✓/✗ Enable/Disable | ___ |
| 4 | Pair whitelist | ✓ Done | — |

### Final Signal Stack
- [ ] List which signals are decision-level (gate trades):
  - MACD (still yes)
  - EMA_Cross (yes, for now)
  - ADX > 25 (yes, Tier 1)
  - New signal #1 (if ≥ +3pp lift) → yes
  - New signal #2 (if ≥ +3pp lift) → yes
  - Others (observation-only or removed)

- [ ] **Confidence weights:**
  - decision_signals_only = True (gate trades)
  - observation_signals = [remaining 3+ signals for confluence]
  - confluence_threshold = 0.4 (gate trades only if gate signals agree)

### Deploy to Production
- [ ] Merge final config to main
- [ ] Restart bot
- [ ] Monitor for 100 trades: verify no crashes, signals firing
- [ ] Check `our_signal_breakdown`: new signals present, confidence scores reasonable

---

## 📊 MONITORING & REVIEW (Jun 27–Jul 5)

### Daily Checkpoint
- [ ] **Jun 27, EOD:** Verify bot running cleanly with new config
- [ ] **Jun 28, EOD:** Check cumulative WR on new config
  - Target: ≥ 52% (already above break-even)
  - If < 51%: revert changes, investigate

- [ ] **Jun 29–30:** Collect 100+ more trades
  - Re-run `analyze_signals.py`
  - Verify new signals still showing positive correlation

### Weekly Review (Jul 1–5)
- [ ] **Jul 1, 9am:** Generate final report:
  ```bash
  python3 scripts/analyze_signals.py > analysis_final.txt
  ```

- [ ] Measure:
  - Base WR (all trades): target ≥ 52%
  - New signal contribution: target +2–3pp average lift
  - 1m-ADX gate impact: measured in shadow_kind breakdown
  - Pair whitelist impact: isolated by filtering on pair_api

- [ ] **Jul 3:** If WR ≥ 52.5%, declare success and plan next improvement
- [ ] **Jul 5:** Archive final analysis, document what worked/didn't

---

## 📝 DOCUMENTATION

### After Each Phase, Update:
- [ ] **RESEARCH_SUMMARY_MARIE.md** — update findings section
- [ ] **decisions.db** — log analysis notes in a memo table (optional)
- [ ] **MEMORY.md** — log wins/learnings for next agent session

### Final Deliverables (Jun 27):
- [ ] **TIER_PROMOTION_RESEARCH.md** — finalized with actual data
- [ ] **NEXT_SIGNALS_IMPLEMENTATION.md** — code changes documented
- [ ] **analysis_final.txt** — full signal breakdown with new config

---

## 🎯 SUCCESS CRITERIA

| Metric | Current | Target | Date |
|--------|---------|--------|------|
| Base WR | 49.7% | ≥ 52.0% | Jun 27 |
| Break-even threshold | 52.1% | — | — |
| Edge | −2.4pp | +2.5–5pp | Jun 27 |
| New signals tested | 0 | 3 | Jun 22 |
| New signals promoted | 0 | 1–2 | Jun 27 |
| Pair whitelist deployed | No | Yes | Jun 25 |
| 1m-ADX gate deployed | No | Yes (if ≥+1.5pp lift) | Jun 26 |

---

## 🚨 CONTINGENCIES

### If Cleanup (Phase 0) Doesn't Help
- **Symptom:** WR still 49.5% after removing RoC, demoting weak signals
- **Cause:** Gate logic is still selecting bad trades
- **Action:** Skip Phases 1–4, focus on pair whitelist (Phase 4) alone
- **Recovery:** Deploy blacklist immediately, retest

### If New Signals Don't Lift WR
- **Symptom:** All three new signals show < +1pp lift
- **Cause:** OTC synthetic pairs respond differently than live forex
- **Action:** Retire all three signals, revert to previous config
- **Recovery:** Investigate regime-specific patterns (ATR volatility buckets)

### If 1m-ADX Gate Hurts Performance
- **Symptom:** WR(1m-ADX > 25) < WR(all trades)
- **Cause:** 1m timeframe doesn't translate to 5s execution
- **Action:** Disable 1m-ADX gate, keep 5s-only gating
- **Recovery:** Test 15m ADX instead (lower latency)

### If Pair Whitelist Crashes Bot
- **Symptom:** Zero trades placed (all pairs blocked)
- **Cause:** Top 10 whitelist is stale, markets changed
- **Action:** Expand whitelist to top 20 pairs
- **Recovery:** Recompute whitelist daily, not weekly

---

## 📞 QUICK REFERENCE

**Key Files:**
- Bot code: `/Users/kym/code/openclaw/projects/PocketOptionBot/`
- Analysis script: `scripts/analyze_signals.py`
- Database: `data/decisions.db`
- Configuration: `.env`

**Key Queries:**
```bash
# Check last trades
sqlite3 data/decisions.db "SELECT outcome, COUNT(*) FROM decisions WHERE ts > datetime('now', '-1 hour') GROUP BY outcome;"

# Check signal breakdown
sqlite3 data/decisions.db "SELECT data FROM decisions WHERE outcome IS NOT NULL ORDER BY ts DESC LIMIT 1;" | python3 -m json.tool

# Run analysis
python3 scripts/analyze_signals.py
```

**Contact:** Marie (Research Specialist) — findings in TIER_PROMOTION_RESEARCH.md

---

**Created:** 2026-06-19  
**Updated:** [update as you progress]  
**Status:** Ready for deployment
