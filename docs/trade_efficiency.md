# Trade Efficiency Optimization Guide

## Current Performance (85 trades analyzed)

- **Win rate:** 60.0% (51W / 34L)
- **Total P&L:** +$15.60
- **Weekly projection:** ~$2,658 at current rate
- **Trading frequency:** ~1.7 trades/minute (currently limited by signal weak threshold)

## The Problem: Weak Signal Filtering

**Critical finding:** ALL 34 losses had identical characteristics:
- Confluence score < 0.30 (very weak)
- Only 2/5 signals agreeing (minimum threshold set)

**Root cause:** Target `MIN_CONFLUENCE_SCORE=0.40` doesn't filter trades because actual average is **0.121**.
- 82/85 trades fall below 0.20
- No real filtering is happening

## Signal Confidence Analysis

| Signal | Avg Confidence | Distribution | Status |
|--------|---|---|---|
| MACD | **0.614** | 84/85 high | ✓ Working (but only contributor to score) |
| RSI | 0.062 | 75/85 <0.2 | ✗ Weak |
| EMA_Cross | **0.004** | 85/85 ~0 | 🔴 Broken |
| Bollinger | 0.022 | 80/85 <0.2 | ✗ Weak |
| CandlePattern | **0.000** | Never fires | 🔴 Broken |

**Why scores are so low:**
- EMA_Cross gap calculation results in 0.004 average confidence
- CandlePattern never matches any patterns
- Bollinger rarely triggers
- **Only MACD contributes meaningful confidence (0.614 × 0.20 weight = ~0.12 score)**

This means the confluence engine is essentially just "Is MACD above 0.5?", not a true consensus gate.

## Optimization Roadmap

### Priority 1: Increase Agreement Gate (Immediate)
**Action:** Set `MIN_SIGNAL_AGREEMENT=3` (currently 2)
```
Dashboard → Settings → Signal Gate → Gate 1: Min Signals Agree
Change from 2 to 3
```

**Effect:**
- Filters to trades where 3+ signals agree
- Reduces trade volume by ~40% (85 → ~50 per session)
- Expected win rate increase: **60% → 65-70%**

**Rationale:** Weak agreement (2/5) means only marginal consensus; 3/5 requires real conviction.

---

### Priority 2: Fix Confluence Score Floor (This Week)
**Action:** Increase `MIN_CONFLUENCE_SCORE` to 0.20
```
Dashboard → Settings → Signal Gate → Gate 2: Min Confluence Score
Change from 0.40 to 0.20
```

**Why it works:**
- Current: 0.40 threshold is useless (96% of trades are 0.00-0.20)
- New: 0.20 threshold actually filters weak signals
- Only trades with **meaningful MACD momentum + signal agreement** pass

**Expected:** +5% win rate improvement

---

### Priority 3: Fix EMA_Cross Signal (This Week)
**File:** `signals/ema_cross.py` lines 86-100

**Problem:** Returns avg confidence 0.004 (essentially non-functional)

**Root cause:** Gap calculation too small
```python
gap_pct = gap / max(abs(sv), 1e-9)
conf = min(1.0, gap_pct * 100)  # ← Results in 0.004 on average
```

**Fix options:**
```python
# Option A: Increase multiplier (simpler)
conf = min(1.0, gap_pct * 500)  # More aggressive scaling

# Option B: Adjust trend cap (for tier-2 established trend)
self.trend_conf_cap = 0.70  # Was 0.55 (line 40)

# Option C: Logarithmic scaling (preserves magnitude)
conf = min(1.0, math.log(gap_pct * 100 + 1) / 5)
```

**Expected:** EMA_Cross returns 0.2-0.5 avg confidence → +3-8% win rate

---

### Priority 4: Pair-Specific Optimization (Future)

Performance by pair:
- **AUDUSD_otc:** 64.7% WR (+$9.85) ← **Best**
- **EURUSD_otc:** 56.7% WR (+$3.61)
- **ETHUSD_otc:** 57.1% WR (+$2.14)

**Options:**
1. Increase gate thresholds only for underperforming pairs (EURUSD, ETHUSD)
2. Focus bot on AUDUSD only (would reduce trade frequency significantly)
3. Add pair-specific signal weights (MACD more important for some pairs)

---

## Implementation Timeline

### Week 1 (Immediate)
- [ ] Set MIN_SIGNAL_AGREEMENT = 3
- [ ] Set MIN_CONFLUENCE_SCORE = 0.20
- [ ] Run 30 trades, track win rate
- [ ] Document results

### Week 2
- [ ] If WR improved, fix EMA_Cross signal
- [ ] Run 30 more trades with new EMA confidence
- [ ] Compare before/after

### Week 3+
- [ ] Analyze signal weight distribution
- [ ] Consider per-pair thresholds
- [ ] Optimize for higher frequency trading

## Expected Outcomes

| Change | Win Rate Impact | Trade Impact | Result |
|--------|---|---|---|
| Baseline | 60.0% | 85 trades | $15.60 |
| +Agreement=3 | +5-10% | -40% volume | Better quality |
| +Score floor | +3-5% | Marginal | Stronger filter |
| +EMA fix | +3-8% | Stochastic | Signal recovery |
| **Target** | **70%+** | 50-60/session | Higher P&L |

## Testing Methodology

After each change:
1. Run 20-30 trades
2. Calculate win rate
3. Compare to baseline (60%)
4. Only keep changes that increase WR by >2%
5. Document in this file

## Notes

- **Do NOT** reduce thresholds further (more trades ≠ more profit)
- **Focus on quality** over quantity—a 70% WR at 40 trades/session beats 60% at 85
- **Test one change at a time** to isolate impact
- **Revert quickly** if win rate drops by >2%
