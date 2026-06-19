# PocketOptionBot Validation Run — Jun 19-26, 2026

## Hypothesis
**Pair selection >> signal quality.** Whitelisting 5 profitable pairs (AUDUSD, DOGE, EURNZD, OMRCNY, #PFE) + extending cooldown from 120s to 300s will push WR from 47.7% to 53%+ (target: sustainable 54%).

## Configuration Deployed
```bash
ALLOWED_PAIRS=["AUDUSD_otc","DOGE_otc","EURNZD_otc","OMRCNY_otc","#PFE_otc"]
POST_LOSS_PAIR_COOLDOWN_SECONDS=300      # Extended from 120s
SHADOW_RECORD_MODE=true
SHADOW_FLIP_SKIP_ENABLED=true
SHADOW_TF5S_ENABLED=true
STAKE_AMOUNT=1.00                        # Conservative
```

## Success Criteria

| Checkpoint | Target | Status |
|-----------|--------|--------|
| **Day 1-2** | Whitelist active (only 5 pairs evaluated) | 🔄 Monitoring |
| **Day 3-5** | Win rate trend emerging (track daily WR) | 🔄 Pending |
| **Day 7** | 500+ new trades collected | 🔄 Pending |
| **Day 7** | WR ≥ 53% sustained | 🔄 DECISION GATE |
| **Day 14** | 1,000+ trades; signal analysis complete | 🔄 Pending |

## Daily Monitoring Tasks

### Morning (every day at 07:00 ACST)
```bash
# Check overnight activity
sqlite3 data/decisions.db \
  "SELECT COUNT(*) as trades, \
          ROUND(100.0*SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END)/COUNT(*),1) as wr \
   FROM decisions WHERE outcome IS NOT NULL AND ts > datetime('now', '-24 hours');"

# Check pair distribution
sqlite3 data/decisions.db \
  "SELECT pair, COUNT(*) as n, ROUND(100.0*SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END)/COUNT(*),1) as wr \
   FROM decisions WHERE outcome IS NOT NULL AND ts > datetime('now', '-24 hours') \
   GROUP BY pair ORDER BY n DESC LIMIT 10;"
```

### Evening (every day at 20:00 ACST)
```bash
# Full-run WR on whitelisted pairs
sqlite3 data/decisions.db \
  "SELECT 'AUDUSD_otc' as pair, COUNT(*) as n, ROUND(100.0*SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END)/COUNT(*),1) as wr FROM decisions WHERE pair='AUDUSD_otc' AND outcome IS NOT NULL \
   UNION ALL
   SELECT pair, COUNT(*), ROUND(100.0*SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END)/COUNT(*),1) FROM decisions WHERE pair IN ('DOGE_otc','EURNZD_otc','OMRCNY_otc','#PFE_otc') AND outcome IS NOT NULL GROUP BY pair \
   ORDER BY n DESC;"
```

## Analysis Checkpoints

### After 500 trades (Day 7)
```bash
# Refresh signal attribution
python3 scripts/analyze_signals.py --data data/decisions.db

# Gate effectiveness
python3 tools/analyze_failures.py --all --min-n 30

# Shadow flip skip validation
sqlite3 data/decisions.db \
  "SELECT would_skip_reason, \
          COUNT(*) as shadow_count, \
          ROUND(100.0*SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END)/COUNT(*),1) as wr \
   FROM decisions WHERE shadow_kind='flip_skip' AND outcome IS NOT NULL \
   GROUP BY would_skip_reason ORDER BY wr DESC;"
```

### After 1,000 trades (Day 14)
```bash
# Per-pair leverage snapshot
python3 tools/analyze_failures.py --all --min-n 50

# Per-config epoch analysis (did lever changes help?)
# Extract 3 most recent flip_levers snapshots and compare outcomes

# Tier 3 signal readiness
# How many HeikinAshi, RoC, StochRSI resolved trades collected?
# Can we promote any to decision-level yet?
```

## Decision Tree

```
Day 7: Have we hit 500 trades?
├─ NO: Continue collecting (may be holiday, low vol, or whitelist too tight)
└─ YES: Check WR on whitelisted pairs
    ├─ WR ≥ 53%: ✅ PROCEED TO DAY 14
    │   └─ Objective: Confirm hold at 53%+ over full 1K trades
    │   └─ Consider: Increase stake to $1.50 after 750 trades if WR stays 53%+
    │
    └─ WR 50-53%: ⚠️ MARGINAL
        └─ Continue 7 more days (day 14 decision point)
        └─ Investigate: Which pair is dragging (DOGE at 52%, EURNZD at 52.8%)?
        └─ Option A: Re-rank pairs, remove lower WR pair, add next-best (CHFJPY 55.1%)
        └─ Option B: Loosen cooldown threshold (300s → 180s), tighten gates (bb_width_min 2→3)
    
    └─ WR < 50%: 🔴 HYPOTHESIS FAILED
        └─ Return to research mode
        └─ Investigate: Did whitelist pairs degrade? New market regime?
        └─ Re-run analyze_failures.py: which gates are over-aggressive?
        └─ Option: Revert to confluence mode + pair selection (old setup was 45.3%)
```

## Log File Locations
- **Main log**: `logs/bot.log` (tail for real-time)
- **Database**: `data/decisions.db` (sqlite3 queries)
- **Config**: `.env` (currently whitelisted pairs + 300s cooldown)

## Escalation Contacts
- **Ada (Code)**: If gates are miscalibrated or decisions don't match expected logic
- **Marie (Research)**: If we need to understand market regime shifts or new signal candidates
- **Midas (Finance)**: If P&L variance exceeds expectations or risk limits need adjustment

## References
- Deployment summary: `~/memory/2026-06-19-deploy-summary.md`
- Shadow data audit: `~/memory/2026-06-19-shadow-data-audit.md`
- Signal analysis: `~/second-brain/01-Session-Logs/2026-06-19-pocketoptionbot-flip-analysis.md`
