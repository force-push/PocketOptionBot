# Feature Possibility: Martingale Stake Management

**Status:** Proposed — not implemented  
**Priority:** Low (high risk; requires careful guardrails before activation)

---

## What Is It?

Martingale is a stake progression strategy where the trade amount is multiplied by a factor (≥2x) after each loss, then reset to the base stake after a win. The goal is that a single win recovers all prior losses plus a small profit equal to the original base stake.

**Classic Martingale example (base = $1, 2x multiplier):**

| Trade | Stake | Result | Cumulative P&L |
|-------|-------|--------|----------------|
| 1     | $1    | Loss   | −$1            |
| 2     | $2    | Loss   | −$3            |
| 3     | $4    | Loss   | −$7            |
| 4     | $8    | Win    | +$1            |

---

## Variants

| Variant | Mechanic | Notes |
|---------|----------|-------|
| Classic Martingale | Stake × 2 after each loss | Most common |
| Grand Martingale | Stake × 2 + 1 base unit after each loss | Slightly higher recovery profit per cycle |
| Anti-Martingale | Stake × 2 after each *win*, reset after loss | Trend-riding; less catastrophic blowup risk |
| Capped Martingale | Classic with hard max stake limit | Safer; loses recovery guarantee above cap |
| Fibonacci | Follow Fibonacci sequence for stake sizes | Slower escalation than 2x |

---

## Why It's Appealing

- Theoretically recovers all losses in a single win
- Simple to implement and reason about
- Works well in short losing streak environments with high win rates

---

## Why It's Dangerous

**The exponential blowup problem:**

A modest 10-loss streak requires a 1024x base stake. With binary options payout rates (~80–90%), the math is worse than casino games:

| Consecutive Losses | Multiplier (2x) | Stake at Loss N |
|--------------------|-----------------|-----------------|
| 3                  | 8×              | $8 on $1 base   |
| 5                  | 32×             | $32             |
| 7                  | 128×            | $128            |
| 10                 | 1024×           | $1,024          |

- **Account limits:** PocketOption has minimum/maximum trade sizes; a Martingale series hits the max quickly
- **Not a genuine edge:** Expected value remains the same (or negative with spread/payout < 100%). Martingale converts frequent small wins into rare catastrophic losses — it doesn't change the underlying win rate
- **Signal quality noise:** A bad signal streak (e.g. sideways market) can produce 8–12 consecutive losses, which classic Martingale cannot survive on a normal account

---

## Proposed Safe Implementation (when built)

If this is ever implemented, it should be a **Capped Martingale** mode with hard limits — not a pure Martingale:

```python
# Conceptual config
martingale:
  enabled: false                  # off by default
  multiplier: 2.0                 # stake × this on each loss
  max_steps: 4                    # hard cap: max 4 doublings (16x base)
  reset_on_win: true
  reset_on_step_cap: true         # reset rather than continue above cap
  base_amount: null               # if null, use account default_amount
```

**Guardrails:**
- `max_steps` cap prevents exponential blowup (4 steps = max 16x base)
- When `max_steps` is reached, reset to base (accept the loss series, don't chase)
- Integrate with existing risk manager: respect `max_daily_loss` and `max_open_trades`
- Only activate within a **trade series** (same asset/direction), not across unrelated signals
- Require explicit opt-in: `enabled: false` by default, never auto-enabled

---

## Integration Points

- **`src/risk_manager.py`** — stake calculation logic lives here; Martingale would be a new stake mode
- **`src/trade_executor.py`** — needs to track per-series loss count and pass adjusted stake to executor
- **`src/models.py`** — add `MartingaleState` dataclass to track current step, series stake, series result
- **`config/`** — new config block (see above)

---

## Open Questions Before Implementation

1. What defines a "trade series"? Same asset only? Same signal? Time window?
2. Does Anti-Martingale (doubling on wins) fit better given our signal quality (win rate ~55–65%)?
3. Should Martingale steps be per-signal-source, or global across all concurrent trades?
4. How does it interact with the 6-concurrent-trade cap? (A series in progress + 5 others = full)
5. Is there a win-rate threshold below which Martingale should auto-disable?

---

## Verdict (current)

**Do not implement yet.** The signal stack needs more resolved trade data (~500+) before layering in stake management complexity. Martingale amplifies both wins and losses — introducing it before the signal quality is validated risks blowing up the account before the bots have proven their edge.

**Revisit after:** Signal analysis (`scripts/analyze_signals.py`) confirms ≥3% positive edge on the decision signal set.
