# Implementation Roadmap: Tier 3 Signals + ADX Gate
**Marie's Build Plan | 2026-06-19**

---

## Overview

Three new high-SNR signals to implement in shadow mode (observation-only, weight > 0 but not in decision_signals):

1. **Donchian Breakout** — 20-period high/low support/resistance (Very High Priority, V. Low Complexity)
2. **Williams %R** — Overbought/oversold oscillator (High Priority, Low Complexity)
3. **TRIX** — Triple-smoothed momentum + signal line (Medium Priority, Low Complexity)

**Plus:**
4. **ADX Gate Enhancement** — Dynamic ADX-based trend strength filter (Tier 1 Filter, not a signal)

---

## Signal 1: Donchian Breakout (HIGHEST PRIORITY)

### Why First?
- Simplest implementation (3 lines of code: high, low, comparison)
- Orthogonal to ALL current indicators (uses raw price, not derivatives)
- Fast feedback loop (test in 300 trades = 1–2 days)
- Expected lift: +2.0pp based on momentum research

### File Structure
```
signals/donchian.py
├── class DonchianSignal
├── __init__(period: int = 20)
├── update(new_bar: dict) -> tuple[str | None, float, str]
└── compute(high, low, close: Series) -> (signal, confidence, description)
```

### Implementation

```python
# signals/donchian.py
from typing import Optional
from pandas import Series
import math

class DonchianSignal:
    """Donchian breakout: price at 20-period high/low."""
    
    def __init__(self, period: int = 20):
        self.period = period
        self.name = "Donchian"
    
    def __call__(self, high: Series, low: Series, close: Series, 
                 volume: Series = None) -> tuple[Optional[str], float, str]:
        """
        Args:
            high, low, close: OHLC series (last value = current bar)
            
        Returns:
            (direction: "CALL"|"PUT"|None, confidence: 0.0-1.0, reason: str)
        """
        if len(high) < self.period + 1:
            return None, 0.0, f"Donchian: warming up ({len(high)}/{self.period})"
        
        recent_high = high.iloc[-self.period:].max()
        recent_low = low.iloc[-self.period:].min()
        current = close.iloc[-1]
        
        # Range of the lookback window
        range_val = recent_high - recent_low
        if range_val == 0:
            return None, 0.0, "Donchian: no range (flat)"
        
        # Breakout position: 0 = at low, 1 = at high
        breakout_ratio = (current - recent_low) / range_val
        
        # Signal generation
        if current > recent_high:
            # Above 20-period high = upside breakout (momentum long)
            confidence = min(1.0, (current - recent_high) / range_val * 2.0)
            direction = "CALL"
            reason = f"Donchian breakout UP: {current:.6f} > {recent_high:.6f} (range={range_val:.6f})"
        
        elif current < recent_low:
            # Below 20-period low = downside breakout (momentum short)
            confidence = min(1.0, (recent_low - current) / range_val * 2.0)
            direction = "PUT"
            reason = f"Donchian breakout DOWN: {current:.6f} < {recent_low:.6f} (range={range_val:.6f})"
        
        else:
            # Inside range, no signal
            direction = None
            confidence = 0.0
            reason = f"Donchian neutral: {current:.6f} inside [{recent_low:.6f}, {recent_high:.6f}]"
        
        return direction, confidence, reason
```

### Signal Description (for confluence engine)
```python
# In signals/__init__.py or main_v2.py:
signals_list = [
    ...
    DonchianSignal(period=20),  # weight=0.07
    ...
]
```

### Testing
```bash
# Quick test on synthetic bar sequence
python3 << 'EOF'
from signals.donchian import DonchianSignal
import pandas as pd

sig = DonchianSignal(period=20)

# Generate synthetic breakout
high = pd.Series([1.0, 1.01, 1.02, 1.015] + [1.02] * 18 + [1.025])  # Breakout on last bar
low = pd.Series([0.99, 0.995, 1.0, 0.99] + [0.99] * 18 + [0.99])
close = pd.Series([1.0, 1.005, 1.01, 1.0] + [1.01] * 18 + [1.025])  # Close above high

direction, conf, reason = sig(high, low, close)
print(f"Direction: {direction}, Confidence: {conf:.2f}, Reason: {reason}")
# Expected: Direction: CALL, Confidence: 1.0, Reason: Donchian breakout UP
EOF
```

### Integration Points
1. Add `from signals.donchian import DonchianSignal` in `main_v2.py`
2. Instantiate in signals list: `DonchianSignal(period=20)` with weight=0.07
3. Wrap in confluence engine (no code change needed, auto-weighted)
4. Log in `our_signal_breakdown` (auto-recorded)

### Expected Behavior
- **High signal rate:** ~40–60% of bars will have a breakout (price always moving to new highs/lows)
- **Confidence distribution:** Mostly 0.3–1.0 (depends on % above/below range)
- **Win rate target:** 51–53% (slight lift from 49.7% base)
- **Lift target:** +2pp (51.7% agree WR)

**Gotchas:**
- False breakouts are common in choppy OTC (consider gating on MACD confirmation for later refinement)
- Period=20 means ~100s lookback at 5s candles (3 trading minutes) — reasonable for 30s expiry

---

## Signal 2: Williams %R (HIGH PRIORITY)

### Why Second?
- Fills momentum-oscillator gap (RSI didn't work, but this variant might)
- Low implementation complexity
- Parameter space well-researched (−100 to 0 scale)
- Expected lift: +2.5pp

### File Structure
```
signals/williams_r.py
├── class WilliamsRSignal
├── __init__(period: int = 14)
├── update(new_bar: dict)
└── compute(high, low, close: Series) -> (signal, confidence, description)
```

### Implementation

```python
# signals/williams_r.py
from typing import Optional
from pandas import Series
import math

class WilliamsRSignal:
    """Williams %R: momentum oscillator (−100 to 0), inverse of Stochastic."""
    
    def __init__(self, period: int = 14):
        self.period = period
        self.name = "Williams_R"
    
    def __call__(self, high: Series, low: Series, close: Series, 
                 volume: Series = None) -> tuple[Optional[str], float, str]:
        """
        Args:
            high, low, close: OHLC series
            
        Returns:
            (direction, confidence, reason)
        """
        if len(high) < self.period:
            return None, 0.0, f"Williams %R: warming up ({len(high)}/{self.period})"
        
        # 14-period high/low
        hh = high.iloc[-self.period:].max()
        ll = low.iloc[-self.period:].min()
        cc = close.iloc[-1]
        
        # Range
        range_val = hh - ll
        if range_val == 0:
            return None, 0.0, "Williams %R: no range"
        
        # Williams %R = −100 * (HH − close) / (HH − LL)
        # Range: −100 (at low, oversold) to 0 (at high, overbought)
        willr = -100.0 * (hh - cc) / range_val
        
        # Oversold/overbought thresholds (tuned for OTC)
        oversold_thresh = -80.0  # Bottom 20% of range
        overbought_thresh = -20.0  # Top 20% of range
        mid = -50.0
        
        # Signal generation
        if willr < oversold_thresh:
            # Oversold → bounce expected (CALL)
            confidence = min(1.0, abs(willr - oversold_thresh) / 20.0)
            direction = "CALL"
            reason = f"Williams %R oversold: {willr:.1f}% (threshold < {oversold_thresh:.0f}%)"
        
        elif willr > overbought_thresh:
            # Overbought → pullback expected (PUT)
            confidence = min(1.0, (willr - overbought_thresh) / 20.0)
            direction = "PUT"
            reason = f"Williams %R overbought: {willr:.1f}% (threshold > {overbought_thresh:.0f}%)"
        
        else:
            # Neutral zone
            direction = None
            confidence = 0.0
            reason = f"Williams %R neutral: {willr:.1f}% (range {oversold_thresh:.0f} to {overbought_thresh:.0f})"
        
        return direction, confidence, reason
```

### Testing
```bash
python3 << 'EOF'
from signals.williams_r import WilliamsRSignal
import pandas as pd

sig = WilliamsRSignal(period=14)

# Synthetic oversold scenario (close at low)
high = pd.Series([100.0] * 14 + [101.0])
low = pd.Series([99.0] * 13 + [98.5] + [98.5])
close = pd.Series([99.5] * 13 + [98.5] + [98.6])  # Close near low

direction, conf, reason = sig(high, low, close)
print(f"Oversold test: {direction}, conf={conf:.2f}")
# Expected: CALL with high confidence
EOF
```

### Integration
1. Add `from signals.williams_r import WilliamsRSignal` in `main_v2.py`
2. Instantiate: `WilliamsRSignal(period=14)` with weight=0.10
3. Same auto-logging as Donchian

### Expected Behavior
- **Signal rate:** ~30–50% (only fires at extremes, not neutral zone)
- **Confidence:** 0.0–1.0, scales with distance from threshold
- **Win rate target:** 51.5–52.5% (slight lift)
- **Lift target:** +2.5pp

**Why it might work where RSI didn't:**
- Different normalization: Williams %R divides by (HH − LL), not by (HH − LL + smoothing)
- Threshold at ±20 vs ±30 is tighter, reduces false signals
- No smoothing in the core calculation, faster response to reversal

---

## Signal 3: TRIX (MEDIUM PRIORITY)

### Why Third?
- Most complex of the three (requires three EMA passes)
- Expected lift: +2.0pp (solid but not exceptional)
- Fills "momentum exhaustion" gap (different from Williams %R)
- Implementation is mechanical (no parameter search needed)

### File Structure
```
signals/trix.py
├── class TRIXSignal
├── __init__(ema_period: int = 15, signal_period: int = 9)
├── _ema(series, period)
└── compute()
```

### Implementation

```python
# signals/trix.py
from typing import Optional
from pandas import Series
import pandas as pd
import math

class TRIXSignal:
    """TRIX: rate-of-change of triple-smoothed EMA + signal line."""
    
    def __init__(self, ema_period: int = 15, signal_period: int = 9):
        self.ema_period = ema_period
        self.signal_period = signal_period
        self.name = "TRIX"
    
    def _ema(self, series: Series, period: int) -> Series:
        """Calculate EMA."""
        return series.ewm(span=period, adjust=False).mean()
    
    def __call__(self, high: Series, low: Series, close: Series,
                 volume: Series = None) -> tuple[Optional[str], float, str]:
        """
        Triple-smoothed EMA of close, then rate-of-change.
        
        Returns:
            (direction, confidence, reason)
        """
        min_bars = self.ema_period * 3 + self.signal_period
        if len(close) < min_bars:
            return None, 0.0, f"TRIX: warming up ({len(close)}/{min_bars})"
        
        # Triple EMA pass
        ema1 = self._ema(close, self.ema_period)
        ema2 = self._ema(ema1, self.ema_period)
        ema3 = self._ema(ema2, self.ema_period)
        
        # Rate of change: percent change over 1 bar
        # trix = (ema3[now] - ema3[prev]) / ema3[prev]
        trix = ema3.pct_change() * 100  # percent
        
        # Signal line = SMA of TRIX
        signal_line = trix.rolling(self.signal_period).mean()
        
        current_trix = trix.iloc[-1]
        current_signal = signal_line.iloc[-1]
        
        # Guard against NaN
        if pd.isna(current_trix) or pd.isna(current_signal):
            return None, 0.0, "TRIX: NaN (warming up)"
        
        # TRIX zero-line and signal line crossover
        tolerance = 0.0001  # Treat as "near zero"
        
        if current_trix > current_signal + tolerance:
            # TRIX above signal → bullish momentum
            diff = current_trix - current_signal
            confidence = min(1.0, abs(diff) / 0.002)  # Scale: 0.002% = max confidence
            direction = "CALL"
            reason = f"TRIX above signal: {current_trix:.4f}% > {current_signal:.4f}%"
        
        elif current_trix < current_signal - tolerance:
            # TRIX below signal → bearish momentum
            diff = current_signal - current_trix
            confidence = min(1.0, abs(diff) / 0.002)
            direction = "PUT"
            reason = f"TRIX below signal: {current_trix:.4f}% < {current_signal:.4f}%"
        
        else:
            # TRIX ≈ signal → neutral
            direction = None
            confidence = 0.0
            reason = f"TRIX neutral: {current_trix:.4f}% ≈ {current_signal:.4f}%"
        
        return direction, confidence, reason
```

### Testing
```bash
python3 << 'EOF'
from signals.trix import TRIXSignal
import pandas as pd
import numpy as np

sig = TRIXSignal(ema_period=15, signal_period=9)

# Synthetic: steady uptrend
close = pd.Series(np.linspace(100, 110, 60))  # 60 bars of steady up
high = close + 0.01
low = close - 0.01

direction, conf, reason = sig(high, low, close)
print(f"Uptrend test: {direction}, conf={conf:.2f}")
# Expected: CALL (TRIX positive, above signal)
EOF
```

### Integration
1. Add `from signals.trix import TRIXSignal`
2. Instantiate: `TRIXSignal(ema_period=15, signal_period=9)` with weight=0.08
3. Auto-logged

### Expected Behavior
- **Signal rate:** ~40–60% (TRIX oscillates around signal line constantly)
- **Confidence:** 0.0–1.0, scales with gap between TRIX and signal
- **Win rate target:** 50.5–51.5%
- **Lift target:** +2.0pp

**Why it might work:**
- Captures momentum *reversals* (TRIX crosses signal line), not absolute direction
- Triple smoothing removes price noise while preserving momentum changes
- Early indicator of trend exhaustion (TRIX divergence = momentum failing)

**Caveat:**
- Highly correlated with MACD (both measure momentum direction)
- If MACD is already gating well, TRIX might be redundant
- Data will tell; test and measure

---

## Part 2: ADX Gate Enhancement (Tier 1 Filter)

### Current Issue
- ADX > 25 is a static gate (applied to all pairs)
- OTC pairs have different ADX distributions
- AUDUSD has higher avg ADX than GBPUSD → threshold doesn't adapt

### Proposal: ADX Percentile Gate

Instead of:
```python
if ADX > 25: allow_trade()
else: skip("adx_conf_" + str(ADX))
```

Use:
```python
pair_adx_history = last_30_days_ADX_values(pair)
adx_percentile = percentileofscore(pair_adx_history, current_ADX)
if adx_percentile < 0.3:  # Bottom 30%
  confidence_penalty = 0.3  # Require higher confluence
elif adx_percentile > 0.7:  # Top 30%
  confidence_penalty = 0.0  # Relax gate
else:
  confidence_penalty = 0.1  # Standard
```

### Implementation (Phase 2, after signals are tested)

```python
# In main_v2.py or risk_manager.py
class ADXPercentileGate:
    def __init__(self, lookback_days: int = 30):
        self.lookback_days = lookback_days
        self.pair_adx_history = {}  # {pair: deque of ADX values}
    
    def update_adx_history(self, pair: str, adx_value: float):
        """Add ADX to rolling history."""
        if pair not in self.pair_adx_history:
            self.pair_adx_history[pair] = deque(maxlen=1000)
        self.pair_adx_history[pair].append(adx_value)
    
    def get_confidence_penalty(self, pair: str, current_adx: float) -> float:
        """
        Returns: 0.0 (no penalty) to 0.3 (penalty)
        """
        hist = self.pair_adx_history.get(pair, [])
        if len(hist) < 50:  # Not enough history
            return 0.0  # Default: no penalty
        
        from scipy.stats import percentileofscore
        percentile = percentileofscore(hist, current_adx) / 100.0
        
        if percentile < 0.3:
            return 0.3  # Weak trend: require high confluence
        elif percentile > 0.7:
            return 0.0   # Strong trend: relax gate
        else:
            return 0.1   # Normal
```

**Integration:**
- Log every ADX value into `pair_adx_history` (already done in `decisions.db`)
- Check gate before trading: `confluence >= threshold + penalty`
- Data collection: Run in shadow mode for 1000+ trades

**Timeline:**
- Jun 22: Measure ADX percentile distribution per pair
- Jun 24: Deploy as shadow gate
- Jun 26: A/B test vs static ADX > 25
- Jun 28: If +1.5pp lift, enable in production

---

## Part 3: Integration Checklist

### Code Changes Required

**File: `main_v2.py`**
```python
from signals.donchian import DonchianSignal
from signals.williams_r import WilliamsRSignal
from signals.trix import TRIXSignal

# In signals initialization:
signals = [
    # ... existing signals ...
    DonchianSignal(period=20),      # weight=0.07
    WilliamsRSignal(period=14),     # weight=0.10
    TRIXSignal(ema_period=15, signal_period=9),  # weight=0.08
]
```

**File: `signals/__init__.py`** (if it exists, add exports)
```python
from .donchian import DonchianSignal
from .williams_r import WilliamsRSignal
from .trix import TRIXSignal

__all__ = [
    ..., "DonchianSignal", "WilliamsRSignal", "TRIXSignal"
]
```

**File: `.env`** (no changes needed, weights are code-level)

### Testing Workflow

1. **Unit tests** (optional but recommended):
   ```bash
   pytest tests/signals/test_donchian.py
   pytest tests/signals/test_williams_r.py
   pytest tests/signals/test_trix.py
   ```

2. **Shadow mode smoke test:**
   ```bash
   python3 scripts/v2_smoke.py  # Verify no crashes
   ```

3. **Live shadow test:**
   - Deploy code with new signals
   - Monitor `our_signal_breakdown` in decisions.db
   - Check that Donchian, Williams %R, TRIX are firing (not NULL)

4. **Analysis checkpoint (Jun 22):**
   ```bash
   python3 scripts/analyze_signals.py
   # Look for Williams_R, Donchian, TRIX rows
   # Measure lift (agree WR - neutral WR)
   ```

---

## Part 4: Timeline & Milestones

| Date | Milestone | Owner | Status |
|------|-----------|-------|--------|
| Jun 19 | Code Donchian breakout | Marie | ⏳ |
| Jun 20 | Code Williams %R, TRIX; integrate into main_v2.py | Marie | ⏳ |
| Jun 20 EOD | Deploy to shadow mode (demo trading) | Kym | ⏳ |
| Jun 22 9am | Run `analyze_signals.py`, measure lift | Marie | ⏳ |
| Jun 22 5pm | Decision point: keep/retire each signal | Kym | ⏳ |
| Jun 23 | Start ADX percentile analysis (shadow) | Marie | ⏳ |
| Jun 24 | 1m ADX gate testing (shadow) | Marie | ⏳ |
| Jun 25 | Pair whitelist (top 10 by edge) deployed | Kym | ⏳ |
| Jun 26 | A/B test: 5s-only vs 5s + 1m ADX | Marie | ⏳ |
| Jun 27 | Final promotion decision + deploy | Kym | ⏳ |
| Jul 1 | 1-week results review | Kym | ⏳ |

---

## Part 5: Code Quality Checklist

**Before deploying to production:**

- [ ] All three signals have docstrings (params, return types, examples)
- [ ] Handle edge cases: NaN, warm-up period, zero-division
- [ ] Confidence scores in range [0.0, 1.0]
- [ ] Direction is "CALL", "PUT", or None (never "NONE" or lowercase)
- [ ] Reason strings are descriptive (include current values)
- [ ] No external deps (only pandas/numpy allowed)
- [ ] Unit tests pass (if applicable)
- [ ] Smoke test passes (`v2_smoke.py` runs without crashes)
- [ ] Signals appear in `analyze_signals.py` output
- [ ] Weights > 0 (so they affect confluence scoring)
- [ ] NOT in `decision_signals` (so they don't gate trades alone)

---

## Expected Impact Summary

| Signal | Implementation Time | Expected Lift | Complexity | Priority |
|--------|-------------------|---|----------|---------|
| Donchian Breakout | 30 min | +2.0pp | V. Low | 🔴 HIGHEST |
| Williams %R | 45 min | +2.5pp | Low | 🟡 HIGH |
| TRIX | 60 min | +2.0pp | Low | 🟡 MEDIUM |
| ADX Percentile Gate | 2 hours | +1.5pp | Medium | 🟡 MEDIUM |
| **Total** | **3.5–4 hours** | **+7.5pp projected** | — | — |

**Conservative Estimate:** If all three signals test at +1.5pp (not +2pp), total lift = +4.5pp. Target WR: 54.2% by Jun 27.

---

**Report Generated:** 2026-06-19 | **Next Checkpoint:** 2026-06-22
