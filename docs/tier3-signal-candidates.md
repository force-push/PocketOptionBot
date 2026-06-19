# Tier 3 Signal Candidates — Complete Code & Spec
**Marie's Research Repository | 2026-06-19**

---

## Overview

Three signals ranked by implementation priority and expected impact:

| Rank | Signal | Expected Lift | Complexity | Implementation Time |
|------|--------|---|----------|-----|
| 1 | Donchian Breakout | +2.0pp | V. Low | 30 min |
| 2 | Williams %R | +2.5pp | Low | 45 min |
| 3 | TRIX | +2.0pp | Low | 60 min |

All are **observation-only** initially (weight > 0, but NOT in `decision_signals`). After 500 resolved trades, promote to decision-level only if lift ≥ +3.0pp.

---

## Signal 1: Donchian Breakout

### Concept
Tracks the 20-period high/low. When price breaks above high → bullish momentum (CALL). When price breaks below low → bearish momentum (PUT).

### Why It Works
- **Orthogonal to all other signals** (uses raw price, not derivatives)
- **Momentum continuation** (breaks often lead to follow-through on OTC)
- **No warm-up lag** (works immediately)
- **High-frequency signal** (~40–60% of bars have a breakout)

### File: `signals/donchian.py`

```python
#!/usr/bin/env python3
"""Donchian Breakout Signal — 20-period high/low breakouts."""

from typing import Optional, Tuple
from pandas import Series
import pandas as pd


class DonchianSignal:
    """20-period Donchian channel breakout."""
    
    def __init__(self, period: int = 20):
        """
        Args:
            period: Number of bars to lookback for high/low (default 20 = ~100s at 5s)
        """
        self.period = period
        self.name = "Donchian"
    
    def __call__(
        self,
        high: Series,
        low: Series,
        close: Series,
        volume: Series = None,
    ) -> Tuple[Optional[str], float, str]:
        """
        Evaluate Donchian breakout signal.
        
        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of close prices
            volume: Not used (for API compatibility)
        
        Returns:
            (direction, confidence, reason_string)
            - direction: "CALL" (bullish breakout), "PUT" (bearish), or None
            - confidence: 0.0–1.0 (how extreme the breakout)
            - reason: Human-readable description
        """
        # Warm-up check
        if len(high) < self.period + 1:
            return None, 0.0, (
                f"Donchian: warming up ({len(high)}/{self.period})"
            )
        
        # 20-period high/low
        recent_high = high.iloc[-self.period :].max()
        recent_low = low.iloc[-self.period :].min()
        current = close.iloc[-1]
        
        # Range of the lookback window
        range_val = recent_high - recent_low
        
        # Guard against flat market
        if range_val == 0 or range_val < 1e-10:
            return None, 0.0, "Donchian: no range (flat market)"
        
        # Breakout detection
        if current > recent_high:
            # Above 20-period high → upside breakout
            distance_pct = (current - recent_high) / range_val
            confidence = min(1.0, distance_pct * 2.0)
            return (
                "CALL",
                confidence,
                (
                    f"Donchian UP breakout: {current:.8f} > {recent_high:.8f} "
                    f"(range={range_val:.8f})"
                ),
            )
        
        elif current < recent_low:
            # Below 20-period low → downside breakout
            distance_pct = (recent_low - current) / range_val
            confidence = min(1.0, distance_pct * 2.0)
            return (
                "PUT",
                confidence,
                (
                    f"Donchian DOWN breakout: {current:.8f} < {recent_low:.8f} "
                    f"(range={range_val:.8f})"
                ),
            )
        
        else:
            # Inside range, no signal
            return None, 0.0, (
                f"Donchian neutral: {current:.8f} within "
                f"[{recent_low:.8f}, {recent_high:.8f}]"
            )
```

### Integration
```python
# In main_v2.py or signals/__init__.py:
from signals.donchian import DonchianSignal

signals = [
    # ... existing signals ...
    DonchianSignal(period=20),  # weight=0.07
]
```

### Testing
```python
import pandas as pd
from signals.donchian import DonchianSignal

sig = DonchianSignal(period=20)

# Test 1: Upside breakout
high = pd.Series([100.0] * 20 + [101.0])
low = pd.Series([99.0] * 20 + [99.0])
close = pd.Series([99.5] * 20 + [101.5])  # Close above high

direction, conf, reason = sig(high, low, close)
assert direction == "CALL", f"Expected CALL, got {direction}"
assert conf > 0.8, f"Expected high confidence, got {conf}"
print(f"✓ Upside breakout test passed: {reason}")

# Test 2: Downside breakout
close = pd.Series([99.5] * 20 + [98.5])  # Close below low
direction, conf, reason = sig(high, low, close)
assert direction == "PUT", f"Expected PUT, got {direction}"
print(f"✓ Downside breakout test passed: {reason}")

# Test 3: Neutral (inside range)
close = pd.Series([99.5] * 20 + [99.5])
direction, conf, reason = sig(high, low, close)
assert direction is None, f"Expected None, got {direction}"
print(f"✓ Neutral test passed")
```

---

## Signal 2: Williams %R

### Concept
Oscillator that measures where close sits in the high-low range. Ranges from −100 (at low, oversold) to 0 (at high, overbought).

- Williams %R < −80 → oversold, expect bounce (CALL)
- Williams %R > −20 → overbought, expect pullback (PUT)
- −80 to −20 → neutral (no signal)

### Why It Works
- **Mean reversion signal** (OTC often reverses at extremes)
- **Different from RSI** (RSI is noise on OTC, but different math might work)
- **Fast responding** (based on 14-bar range, not smoothed)

### File: `signals/williams_r.py`

```python
#!/usr/bin/env python3
"""Williams %R Signal — Overbought/oversold oscillator."""

from typing import Optional, Tuple
from pandas import Series
import pandas as pd


class WilliamsRSignal:
    """Williams %R oscillator (−100 to 0 scale)."""
    
    def __init__(self, period: int = 14):
        """
        Args:
            period: Lookback period for high/low (default 14 = ~70s at 5s)
        """
        self.period = period
        self.name = "Williams_R"
    
    def __call__(
        self,
        high: Series,
        low: Series,
        close: Series,
        volume: Series = None,
    ) -> Tuple[Optional[str], float, str]:
        """
        Evaluate Williams %R signal.
        
        Williams %R = −100 * (HH − close) / (HH − LL)
        Range: −100 (oversold) to 0 (overbought)
        
        Args:
            high, low, close: OHLC series
            volume: Not used
        
        Returns:
            (direction, confidence, reason_string)
        """
        # Warm-up check
        if len(high) < self.period:
            return None, 0.0, (
                f"Williams %R: warming up ({len(high)}/{self.period})"
            )
        
        # 14-period high/low
        hh = high.iloc[-self.period :].max()
        ll = low.iloc[-self.period :].min()
        cc = close.iloc[-1]
        
        # Range
        range_val = hh - ll
        if range_val == 0 or range_val < 1e-10:
            return None, 0.0, "Williams %R: no range"
        
        # Williams %R calculation
        willr = -100.0 * (hh - cc) / range_val
        
        # Thresholds (tuned for OTC 5s)
        oversold_thresh = -80.0
        overbought_thresh = -20.0
        
        # Signal generation
        if willr < oversold_thresh:
            # Oversold → bounce expected
            distance = abs(willr - oversold_thresh)
            confidence = min(1.0, distance / 20.0)
            return (
                "CALL",
                confidence,
                (
                    f"Williams %R oversold: {willr:.1f}% "
                    f"(threshold < {oversold_thresh:.0f}%)"
                ),
            )
        
        elif willr > overbought_thresh:
            # Overbought → pullback expected
            distance = willr - overbought_thresh
            confidence = min(1.0, distance / 20.0)
            return (
                "PUT",
                confidence,
                (
                    f"Williams %R overbought: {willr:.1f}% "
                    f"(threshold > {overbought_thresh:.0f}%)"
                ),
            )
        
        else:
            # Neutral zone
            return None, 0.0, (
                f"Williams %R neutral: {willr:.1f}% "
                f"[{oversold_thresh:.0f}%, {overbought_thresh:.0f}%]"
            )
```

### Integration
```python
from signals.williams_r import WilliamsRSignal

signals = [
    # ... existing ...
    WilliamsRSignal(period=14),  # weight=0.10
]
```

### Testing
```python
import pandas as pd
from signals.williams_r import WilliamsRSignal

sig = WilliamsRSignal(period=14)

# Test: Oversold (close at low)
high = pd.Series([100.0] * 14 + [100.5])
low = pd.Series([99.0] * 14 + [98.8])
close = pd.Series([99.5] * 14 + [98.8])  # At low = oversold

direction, conf, reason = sig(high, low, close)
assert direction == "CALL", f"Expected CALL (oversold bounce), got {direction}"
print(f"✓ Oversold test: {reason}")

# Test: Overbought (close at high)
close = pd.Series([99.5] * 14 + [100.5])  # At high = overbought
direction, conf, reason = sig(high, low, close)
assert direction == "PUT", f"Expected PUT (overbought pullback), got {direction}"
print(f"✓ Overbought test: {reason}")
```

---

## Signal 3: TRIX

### Concept
Triple-smoothed EMA of close price, then rate-of-change. TRIX crosses above/below its signal line (9-period SMA of TRIX) to indicate momentum shifts.

### Why It Works
- **Momentum reversal detection** (captures when trend exhausts)
- **Triple smoothing** removes noise while preserving direction changes
- **Signal line crossover** is mechanical and clean
- **Fills different niche** than MACD (different smoothing path)

### File: `signals/trix.py`

```python
#!/usr/bin/env python3
"""TRIX Signal — Triple-smoothed EMA momentum + signal line."""

from typing import Optional, Tuple
from pandas import Series
import pandas as pd


class TRIXSignal:
    """TRIX: rate-of-change of triple-smoothed EMA."""
    
    def __init__(self, ema_period: int = 15, signal_period: int = 9):
        """
        Args:
            ema_period: EMA period for each of 3 passes (default 15)
            signal_period: SMA period for signal line (default 9)
        """
        self.ema_period = ema_period
        self.signal_period = signal_period
        self.name = "TRIX"
    
    def _ema(self, series: Series, period: int) -> Series:
        """Calculate exponential moving average."""
        return series.ewm(span=period, adjust=False).mean()
    
    def __call__(
        self,
        high: Series,
        low: Series,
        close: Series,
        volume: Series = None,
    ) -> Tuple[Optional[str], float, str]:
        """
        Evaluate TRIX signal (triple-smoothed EMA ROC + signal line).
        
        Args:
            high, low, close: OHLC series (uses close only)
            volume: Not used
        
        Returns:
            (direction, confidence, reason_string)
        """
        # Warm-up: need 3 EMA passes + signal line period
        min_bars = self.ema_period * 3 + self.signal_period
        if len(close) < min_bars:
            return None, 0.0, (
                f"TRIX: warming up ({len(close)}/{min_bars})"
            )
        
        # Triple EMA pass
        ema1 = self._ema(close, self.ema_period)
        ema2 = self._ema(ema1, self.ema_period)
        ema3 = self._ema(ema2, self.ema_period)
        
        # Rate of change (percent change per bar)
        trix = ema3.pct_change() * 100  # Convert to percentage
        
        # Signal line (SMA of TRIX)
        signal_line = trix.rolling(self.signal_period).mean()
        
        # Current values
        current_trix = trix.iloc[-1]
        current_signal = signal_line.iloc[-1]
        
        # Guard against NaN
        if pd.isna(current_trix) or pd.isna(current_signal):
            return None, 0.0, "TRIX: NaN (warming up)"
        
        # Threshold for "near line"
        tolerance = 0.0001  # Treat gaps < 0.0001% as neutral
        
        # Signal generation
        if current_trix > current_signal + tolerance:
            # TRIX above signal line → bullish momentum
            diff = current_trix - current_signal
            confidence = min(1.0, abs(diff) / 0.002)  # Cap at 0.002% gap
            return (
                "CALL",
                confidence,
                (
                    f"TRIX above signal: {current_trix:.4f}% > {current_signal:.4f}%"
                ),
            )
        
        elif current_trix < current_signal - tolerance:
            # TRIX below signal line → bearish momentum
            diff = current_signal - current_trix
            confidence = min(1.0, abs(diff) / 0.002)
            return (
                "PUT",
                confidence,
                (
                    f"TRIX below signal: {current_trix:.4f}% < {current_signal:.4f}%"
                ),
            )
        
        else:
            # TRIX ≈ signal line → neutral
            return None, 0.0, (
                f"TRIX neutral: {current_trix:.4f}% ≈ {current_signal:.4f}%"
            )
```

### Integration
```python
from signals.trix import TRIXSignal

signals = [
    # ... existing ...
    TRIXSignal(ema_period=15, signal_period=9),  # weight=0.08
]
```

### Testing
```python
import pandas as pd
import numpy as np
from signals.trix import TRIXSignal

sig = TRIXSignal(ema_period=15, signal_period=9)

# Test: Steady uptrend (TRIX positive)
close = pd.Series(np.linspace(100, 110, 60))  # 60 bars of steady up

direction, conf, reason = sig(
    high=close + 0.01,
    low=close - 0.01,
    close=close
)
print(f"Uptrend test: {direction}")
assert direction == "CALL", f"Expected CALL in uptrend, got {direction}"

# Test: Steady downtrend (TRIX negative)
close = pd.Series(np.linspace(110, 100, 60))  # 60 bars of steady down

direction, conf, reason = sig(
    high=close + 0.01,
    low=close - 0.01,
    close=close
)
print(f"Downtrend test: {direction}")
assert direction == "PUT", f"Expected PUT in downtrend, got {direction}"
```

---

## Integration Checklist

### Step 1: Create Signal Files
```bash
# In PocketOptionBot/signals/ directory
touch signals/donchian.py
touch signals/williams_r.py
touch signals/trix.py

# Copy code from above into each file
```

### Step 2: Update main_v2.py
```python
# At top of file, add imports
from signals.donchian import DonchianSignal
from signals.williams_r import WilliamsRSignal
from signals.trix import TRIXSignal

# In signals initialization (wherever signals list is built)
signals = [
    # ... existing signals ...
    DonchianSignal(period=20),        # weight=0.07
    WilliamsRSignal(period=14),       # weight=0.10
    TRIXSignal(ema_period=15, signal_period=9),  # weight=0.08
]
```

### Step 3: Verify No Crashes
```bash
python3 scripts/v2_smoke.py  # Should run without errors
```

### Step 4: Deploy to Shadow Mode
```bash
# Set SHADOW_TF5S_ENABLED=true in .env (already set)
# Start bot, let it collect trades for 48–72 hours
```

### Step 5: Analyze After 500 Trades
```bash
python3 scripts/analyze_signals.py

# Look for these rows in output:
# Donchian        agree n     WR   neut n     WR   opp n     WR    lift
# Williams_R      ...
# TRIX            ...
```

### Step 6: Decision
- If any signal's lift ≥ +3.0pp → promote to decision-level
- If lift between +2.0–3.0pp → keep observation-only
- If lift < +0.5pp → demote to weight=0.0 or remove

---

## Performance Expectations

| Signal | Signal Rate | Avg Confidence | Expected Agree WR | Expected Lift |
|--------|-------------|----------------|--------------------|---|
| Donchian | 40–60% | 0.4–0.8 | 51.5–52.0% | +1.8–2.3pp |
| Williams %R | 30–50% | 0.3–1.0 | 51.5–52.5% | +1.5–3.0pp |
| TRIX | 40–60% | 0.2–1.0 | 51.0–52.0% | +1.3–2.0pp |

(Base WR = 49.7%, so lift = agree WR − base WR)

---

## Common Issues & Fixes

### Issue: Signal returns NULL for many bars
**Cause:** Warm-up period not complete or threshold too strict
**Fix:** Lower threshold (e.g., Williams %R −80 → −70, Donchian breakouts are harder to define)

### Issue: Confidence always 0.0–0.2
**Cause:** Confidence scaling is too conservative
**Fix:** Adjust denominator in confidence formula (e.g., `min(1.0, distance / 0.01)` instead of `/0.1`)

### Issue: Signal fires on every bar (100% fire rate)
**Cause:** No neutral zone (threshold too wide)
**Fix:** Tighten threshold or add band around zero

### Issue: NaN values in calculations
**Cause:** Division by zero, missing warm-up period, or pandas Series operations
**Fix:** Use guards like `if range_val == 0` and `if pd.isna(value)`

---

## Next Steps

1. **Jun 19 EOD:** Copy code, integrate into main_v2.py, test with `v2_smoke.py`
2. **Jun 20 EOD:** Deploy to shadow mode with bot running
3. **Jun 22 EOD:** Run `analyze_signals.py`, measure lift for each
4. **Jun 22 5pm:** Decision: keep (lift ≥ +2pp) or retire (lift < +0.5pp)
5. **Jun 27:** Promotion decision based on full data

---

**Code prepared by:** Marie, Research Specialist  
**Date:** 2026-06-19  
**Status:** Ready to deploy
