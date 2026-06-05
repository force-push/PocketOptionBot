# Performance & Trade Frequency Optimization

## Current Bottlenecks

### 1. **Prediction Poll Timeout** (navigator.py:163)
```python
async def wait_for_prediction(self, timeout: float = 30.0, interval: float = 2.0):
```

**Issue:** After each cycle, the bot waits up to **30 seconds** for po_broker_bot to post a prediction.
- Timeout: 30 seconds ← **Too long**
- Poll interval: 2 seconds ← **Could be faster**
- This blocks new pair analysis during this time

**Current flow:**
1. Click "Start Autotrade"
2. Bot posts "AI analysis: Running..." 
3. **WAIT 2-30 SECONDS** for prediction screen
4. Analyze signal & trade
5. Move to menu for next cycle

**Impact:** ~2-5 trade cycles per minute (bottleneck is po_broker_bot response time)

---

### 2. **No Concurrent Analysis**
Currently: Sequential `run_once()` calls (one pair at a time)
```
Cycle 1: Analyze pair A (30-45s)
Cycle 2: Analyze pair B (30-45s)
Cycle 3: Analyze pair C (30-45s)
```

Better: Parallel analysis of multiple pairs
```
Run 1A, 1B, 1C concurrently (30-45s total instead of 90-135s)
```

---

### 3. **Long Polling Intervals**
Navigator.read_latest_text() has hardcoded sleeps:
- `await asyncio.sleep(2)` after start_autotrade (line 101)
- `await asyncio.sleep(3)` after pair selection (line 118)
- `await asyncio.sleep(2.5)` after nag dismiss (line 141)

These add up to **5-8 seconds of built-in delays per cycle**.

---

## Optimization Strategies

### Strategy 1: Reduce Poll Interval (Quick Win)
**File:** `telegram_feed/navigator.py:163`

```python
# Before
async def wait_for_prediction(self, timeout: float = 30.0, interval: float = 2.0):

# After
async def wait_for_prediction(self, timeout: float = 20.0, interval: float = 1.0):
```

**Effect:**
- Reduces prediction wait from avg 15s to avg 10s
- Fails faster on Telegram delays
- **Estimated 1.5-2x faster trade frequency**

**Risk:** Low (only affects poll speed, not accuracy)

---

### Strategy 2: Shorten Navigation Sleeps (Medium Impact)
**Files:** Multiple locations in `navigator.py`

```python
# start_autotrade (line 101)
await asyncio.sleep(2)      # → 1.0
# pair selection (line 118)
await asyncio.sleep(3)      # → 1.5
# nag screen (line 141)
await asyncio.sleep(2.5)    # → 1.0
# back_to_menu (line 198)
await asyncio.sleep(1.5)    # → 0.5
```

**Total time saved per cycle:** ~2-3 seconds
**Effect:** **+30% faster cycles**

**Risk:** Low-medium (sleeps give Telegram UI time to update; too short might cause race conditions)

---

### Strategy 3: Parallel Cycle Execution (High Impact)
**File:** `main_v2.py:169-189`

Change from sequential `await manager.run_once()` to parallel tasks:

```python
# Before: Sequential (one at a time)
while True:
    await manager.run_once()
    await asyncio.sleep(2)

# After: Parallel (run 2 concurrent managers)
async def run_parallel_cycles(manager_count=2):
    managers = [
        StrategyManagerV2(...) for _ in range(manager_count)
    ]
    tasks = [manager.run_once() for manager in managers]
    
    while True:
        await asyncio.gather(*tasks)
        # Reset for next round
        tasks = [manager.run_once() for manager in managers]
        await asyncio.sleep(2)
```

**Effect:**
- Run 2 managers in parallel = **2x trade frequency**
- Each manager analyzes different pairs
- **Estimated: 4-8 trades/minute** (vs 1-2 currently)

**Risk:** High
- Requires multiple Telethon sessions (one per manager)
- Each session needs separate `.session` file
- Increased Telegram bandwidth
- Risk of getting both accounts flagged simultaneously

---

### Strategy 4: Multiple Telegram Sessions (Advanced)
Run completely separate bot instances:
```bash
# Terminal 1
python3 main_v2.py --session session_1

# Terminal 2  
python3 main_v2.py --session session_2

# Terminal 3
python3 main_v2.py --session session_3
```

**Effect:**
- N independent bots = N×trade frequency
- Redundancy (if one session gets FloodWait, others continue)
- Better load distribution across Telegram

**Risk:** Very high
- Requires N accounts
- N times more Telegram API pressure
- Likely to trigger rate limits sooner
- Compliance risk with Telegram ToS

---

## Recommended Approach

### Phase 1: Low-Risk (This Week)
1. **Reduce poll interval** 30.0s→20.0s, 2.0s→1.0s
2. **Shorten sleeps** by 30-50%
3. Test with 20+ trades
4. Monitor: trade frequency, win rate, errors

**Expected:** +50% faster cycles, still safe

### Phase 2: Medium-Risk (Next Week)  
If Phase 1 works:
1. **Implement 2-manager parallelism**
2. Create second Telethon session for same account
3. Run two manager instances concurrently
4. Test for 50+ trades
5. Monitor: signal quality, account flags, FloodWaits

**Expected:** 2x trade frequency, modest flag risk

### Phase 3: High-Reward (Later)
Only if Phase 2 proves stable:
1. Multiple accounts (2-3)
2. Fully parallel execution
3. Expect 3-5x frequency but high compliance risk

---

## Implementation Checklist

### Phase 1 Quick Wins
- [ ] Navigator: Reduce poll interval to 1s, timeout to 20s
- [ ] Navigator: Reduce hardcoded sleeps by 50%
- [ ] Test 20 trades, document results
- [ ] Monitor for Telegram errors or slowdowns

### Phase 2 Parallelism
- [ ] Create second `.session` file
- [ ] Modify config to support multiple sessions
- [ ] Implement 2-manager `run_parallel_cycles()`
- [ ] Test with 50 trades
- [ ] Check account status for flags

### Phase 3 Scale-Out
- [ ] Add support for N accounts
- [ ] Implement manager pool pattern
- [ ] Document Telegram rate limits observed
- [ ] Establish monitoring for account health

---

## Monitoring Metrics

Track these when optimizing:

```
Per cycle:
  - Total cycle time (start → menu)
  - Prediction wait time (part of cycle)
  - Trade latency (API execution)
  - Main loop pause (asyncio overhead)
  
Per session:
  - Trades/minute
  - Win rate (quality check)
  - FloodWait frequency
  - Signal breakdown
```

---

## Notes

- **Do NOT** reduce sleeps below 0.5s without testing
- **Always monitor win rate** when changing timing (faster ≠ better)
- **FloodWait is your friend** — if it kicks in, slow down willingly
- **Telegram WILL throttle you** — expect backoff after heavy optimization
- **Quality > Quantity** — one 70% WR trade beats five 50% WR trades
