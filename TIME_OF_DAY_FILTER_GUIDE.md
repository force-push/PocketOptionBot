# Time-of-Day Filter Guide

> ⚠️ **DEPRECATED 2026-06-11.** The hour gating is now **disabled by default**
> (`TIME_OF_DAY_FILTER_ENABLED=false`). Blocked-hour shadow data showed the
> hour win rates below were curve-fit to one day's noise and did not
> replicate (e.g. "90.9%" at 11:00 UTC was n=11; it measured 50.9% at n=228
> the next day). See SHADOW_TRADE_ANALYSIS.md Finding 5 and Addendum 3.
> Kept for historical reference only.

**Local Timezone:** ACST (UTC+9:30) | **Updated:** 2026-06-10

---

## Quick Summary

The bot **only trades during profitable hours**, skipping all other times. This single filter improved win rate from **49.4% → 55-60%** by avoiding low-probability periods.

**Current local time:** 7:38 PM (Jun 10)  
**Next trading window:** 8:30 PM - 6:00 AM (Jun 11)

---

## Trading Schedule (Local Time - ACST)

### Morning Window
| Local Time | UTC | Win Rate | Status | Action |
|---|---|---|---|---|
| 3:30 PM | 06:00 | 75.0% | ✓ Excellent | **TRADE** |
| 4:30 PM | 07:00 | 50.0% | ❌ Below break-even | SKIP |
| 5:30 PM | 08:00 | 58.8% | ✓ Good | **TRADE** |
| 6:30 PM | 09:00 | 70.0% | ✓ Excellent | **TRADE** |
| 7:30 PM | 10:00 | 44.4% | ❌ Below break-even | SKIP |
| **8:30 PM** | **11:00** | **90.9%** | **✓ BEST** | **TRADE** |

### Evening Window
| Local Time | UTC | Win Rate | Status | Action |
|---|---|---|---|---|
| 2:30 AM (Jun 11) | 17:00 | 66.7% | ✓ Good | **TRADE** |
| 3:30 AM (Jun 11) | 18:00 | 53.1% | ✓ Profitable | **TRADE** |
| 4:30 AM (Jun 11) | 19:00 | 43.6% | ❌ Below break-even | SKIP |
| 5:30 AM (Jun 11) | 20:00 | 53.8% | ✓ Profitable | **TRADE** |

### No-Trade Hours
| Local Time | UTC | Win Rate | Status |
|---|---|---|---|
| 12:30 AM - 3:30 PM | 00:00-06:00 | 0-75% | ❌ NEVER TRADE |
| 4:30 PM | 07:00 | 50.0% | ❌ SKIP |
| 7:30 PM | 10:00 | 44.4% | ❌ SKIP |
| 8:30 PM - 2:30 AM | 12:00-17:00 | 39-48% | ❌ NEVER TRADE |
| 4:30 AM | 19:00 | 43.6% | ❌ SKIP |
| 6:30 AM - 12:30 PM | 21:00-03:00 (next day) | Unknown | ❌ SKIP |

---

## Current Status (2026-06-10 @ 7:38 PM ACST)

```
Local time:        19:38 (7:38 PM)
UTC time:          10:08 (10:08 AM)
Current hour:      10:00 UTC
Filter status:     ❌ SKIPPING (hour 10 = 44.4% WR)

Next trading:      ✅ 20:30 ACST (8:30 PM) = 11:00 UTC
Time remaining:    ~50 minutes
Expected WR:       90.9% (best hour)
```

### What You'll See in Logs

```
CYCLE SKIP — time_of_day_insufficient_data (hour 10:00 UTC)
CYCLE SKIP — time_of_day_insufficient_data (hour 10:00 UTC)
CYCLE SKIP — time_of_day_insufficient_data (hour 10:00 UTC)
...every 2 seconds until 8:30 PM...
```

This is **normal and expected**. The bot will resume trading automatically at 8:30 PM.

---

## How the Filter Works

### Code Location
**File:** `strategy/market_filters.py` → `TimeOfDayFilter`  
**Integrated in:** `strategy/manager_v2.py` → `_run_once_signals()`

### Logic
```
At start of each cycle:
1. Get current UTC hour
2. Check if hour in PROFITABLE_HOURS
3. If yes → evaluate all pairs
4. If no → skip entire cycle (no pairs evaluated, no logs)
```

### Skip Reasons
- **`time_of_day_insufficient_data`** — Hour not in profitable list (7, 10, 13, 15, 21-22 UTC)
- **No skip message** — Hour is explicitly blocked as losing (0, 12, 14, 16, 19, 23 UTC)

---

## Why Each Hour Is Classified

### Profitable Hours (Trade)
- **3:30 PM (06:00 UTC):** 75.0% WR — Morning start, good signals
- **5:30 PM (08:00 UTC):** 58.8% WR — Steady performance
- **6:30 PM (09:00 UTC):** 70.0% WR — Strong signals
- **8:30 PM (11:00 UTC):** 90.9% WR — Peak performance, best hour of day
- **2:30 AM (17:00 UTC):** 66.7% WR — Evening start
- **3:30 AM (18:00 UTC):** 53.1% WR — Solid trades
- **5:30 AM (20:00 UTC):** 53.8% WR — End of evening window

### Blocked Hours (Skip)
- **12:30 AM - 3:00 AM UTC (00:00-06:00):** No data or very low WR
- **4:30 PM (07:00 UTC):** 50.0% WR — Right at break-even, too risky
- **7:30 PM (10:00 UTC):** 44.4% WR — Weak signals, below break-even
- **8:30 PM - 2:30 AM (12:00-17:00 UTC):** 39-48% WR — Consistent losses
- **4:30 AM (19:00 UTC):** 43.6% WR — Below break-even
- **6:30 AM - 12:30 PM (21:00-03:00 UTC):** Insufficient data

---

## Sample 24-Hour Schedule

```
12:00 AM  ❌ SKIP   (00:00 UTC, unknown)
 1:00 AM  ❌ SKIP   (01:00 UTC, unknown)
 2:00 AM  ❌ SKIP   (02:00 UTC, unknown)
 3:00 AM  ❌ SKIP   (03:00 UTC, unknown)
 4:00 AM  ❌ SKIP   (04:00 UTC, unknown)
 5:00 AM  ❌ SKIP   (05:00 UTC, unknown)

 3:30 PM  ✅ TRADE  (06:00 UTC, 75.0% WR)
 4:30 PM  ❌ SKIP   (07:00 UTC, 50.0% WR)
 5:30 PM  ✅ TRADE  (08:00 UTC, 58.8% WR)
 6:30 PM  ✅ TRADE  (09:00 UTC, 70.0% WR)
 7:30 PM  ❌ SKIP   (10:00 UTC, 44.4% WR)
 8:30 PM  ✅ TRADE  (11:00 UTC, 90.9% WR) ← PEAK

 9:30 PM  ❌ SKIP   (12:00 UTC, 39.3% WR)
10:30 PM  ❌ SKIP   (13:00 UTC, unknown)
11:30 PM  ❌ SKIP   (14:00 UTC, 47.7% WR)
12:30 AM  ❌ SKIP   (15:00 UTC, unknown)

 2:30 AM  ✅ TRADE  (17:00 UTC, 66.7% WR)
 3:30 AM  ✅ TRADE  (18:00 UTC, 53.1% WR)
 4:30 AM  ❌ SKIP   (19:00 UTC, 43.6% WR)
 5:30 AM  ✅ TRADE  (20:00 UTC, 53.8% WR)

 6:30 AM  ❌ SKIP   (21:00 UTC, unknown)
 7:30 AM  ❌ SKIP   (22:00 UTC, unknown)
 8:30 AM  ❌ SKIP   (23:00 UTC, 31.4% WR) ← WORST
```

---

## Monitoring the Filter

### What to Expect
- **During skip hours:** Logs show `CYCLE SKIP` every 2 seconds (normal)
- **During trade hours:** Logs show `signals scan: X/Y pairs` and trading activity
- **No errors or warnings:** Filter is working as designed

### Red Flags (Something's Wrong)
- ✗ Trading during blocked hours (19:00-03:00 UTC / 4:30 AM - 12:30 PM local)
- ✗ No activity during profitable hours (3:30-8:30 PM local)
- ✗ Bot hung (no logs for >30 seconds during trade hours)

---

## Customizing the Filter

### To Add a New Profitable Hour
1. Open `strategy/market_filters.py`
2. Add entry to `TimeOfDayFilter.PROFITABLE_HOURS`:
   ```python
   PROFITABLE_HOURS = {
       ...
       7: 52.5,  # Add 07:00 UTC if data supports it
   }
   ```
3. Remove from `BLOCKED_HOURS` if present
4. Restart the bot

### To Block a Currently-Profitable Hour
```python
BLOCKED_HOURS = {
    ...
    9: 70.0,  # Block 09:00 UTC (6:30 PM local) if performance drops
}
```
And remove from `PROFITABLE_HOURS`.

---

## Why This Works

**The win-rate swing is massive:**
- Best hour (8:30 PM / 11:00 UTC): 90.9% WR → +$8.20 per 11 trades
- Worst hour (8:30 AM / 23:00 UTC): 31.4% WR → -$13.88 per 35 trades
- **Difference: 59.5% absolute swing**

This single filter matters more than:
- ✓ Signal tuning (all signals were 49-50% WR)
- ✓ Pair selection (even worst pairs were 40-60% WR)
- ✓ Confluence gating (agreement didn't help)

---

## Troubleshooting

### "CYCLE SKIP" all day
**Check:** Is current hour in `PROFITABLE_HOURS`?
```python
from strategy.market_filters import TimeOfDayFilter
from datetime import datetime, timezone

hour = datetime.now(timezone.utc).hour
print(f"Hour: {hour}, Allowed: {TimeOfDayFilter.is_allowed(hour)}")
```

### Trading when shouldn't be
**Check:** Code modification? Restart bot with latest code.
```bash
git status  # See if strategy/market_filters.py was modified
git log --oneline | head -1  # Check last commit
```

### Logs show wrong UTC hour
**Check:** Bot thinks it's a different time. Verify server time:
```bash
date  # Local time
date -u  # UTC time
```

---

## Summary

**The time-of-day filter is the most effective optimization found.** It:
- ✓ Reduces trading volume by 70-80% (fewer, better trades)
- ✓ Improves win rate by 10-15% (55-60% vs 49.4%)
- ✓ Increases daily P&L by ~$120 (from -$104 to +$16)
- ✓ Is simple and deterministic (no randomness or tuning)

**Current status:** Bot is in a skip hour (10:00 UTC / 7:38 PM local). Next trading window opens at 8:30 PM when win rate jumps to 90.9%.
