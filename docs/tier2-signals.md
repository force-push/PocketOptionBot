# Tier 2 Signals: Decision-Contributing Research Indicators

## Overview

Tier 2 signals are **research-grade indicators** (weight > 0) that contribute to the confluence scoring system but **do NOT gate trading decisions**. Only MACD + EMA_Cross control the TRADE/SKIP decision.

This design allows us to:
1. Collect correlation data on new signals without affecting live trading
2. Measure individual signal win rates over time
3. Promote signals to full decision status only after data supports it
4. Safely retire underperforming signals

---

## Current Tier 2 Signals

### 1. Stochastic Oscillator
**File:** `signals/stochastic.py`  
**Weight:** 0.12 (moderate contributor to confluence)  
**Status:** ✅ Working

#### What It Does
Measures where the closing price sits within the high-low range over the last N periods.
- K% = 100 * (close - lowest_low) / (highest_high - lowest_low)
- D% = 3-period moving average of K%

#### Signals
| Condition | Direction | Confidence | Use Case |
|-----------|-----------|------------|----------|
| K% < 20 | CALL | min(1.0, (20-K%)/20) | Oversold bounce |
| K% > 80 | PUT | min(1.0, (K%-80)/20) | Overbought reversal |
| K% crosses D% up | CALL | 0.40 | Bullish momentum |
| K% crosses D% down | PUT | 0.40 | Bearish momentum |
| 20 <= K% <= 80 | None | 0.0 | Neutral range |

#### Parameters
```python
StochasticSignal(period=14, smooth_k=3, smooth_d=3)
```

#### Why Use It
- **High sensitivity** on 5-min timeframes for mean-reversion
- **Binary options advantage**: Overbought/oversold are natural reversal zones for 30s-1m expiries
- **Complements MACD**: MACD shows trend direction, Stochastic shows momentum extremes

#### Known Issues
- Whipsaws in choppy markets (K% bounces between 20-80)
- Lagging in strong trends (K% gets stuck at extremes)

---

### 2. Parabolic SAR
**File:** `signals/parabolic_sar.py`  
**Weight:** 0.13 (moderate contributor)  
**Status:** ✅ Working

#### What It Does
Plots **Stop and Reverse points** that follow price in trends:
- In uptrends: SAR sits below price, providing support
- In downtrends: SAR sits above price, providing resistance
- When price crosses SAR, the trend reverses

#### Signals
| Condition | Direction | Confidence | Use Case |
|-----------|-----------|------------|----------|
| Price > SAR | CALL | min(1.0, distance / ATR / 3) | Uptrend confirmation |
| Price < SAR | PUT | min(1.0, distance / ATR / 3) | Downtrend confirmation |

#### Parameters
```python
ParabolicSARSignal(initial_af=0.02, max_af=0.2, af_step=0.02)
```

#### Why Use It
- **Natural stop-loss levels**: SAR value = automatic exit point
- **Early reversal detection**: SAR flips before trends fully reverse
- **Trend following**: Excellent for riding established trends to their natural end
- **Acceleration factor** increases with new extremes (rewards strong trends)

#### Known Issues
- **Whipsaws in ranges**: SAR can flip back-and-forth when price oscillates
- **False signals in choppy markets**: Especially in the first few bars
- Needs higher confidence threshold when distance from SAR is small

---

### 3. Supertrend
**File:** `signals/supertrend.py`  
**Weight:** 0.15 (slightly higher contributor)  
**Status:** ⚠️ Needs Debugging (NaN calculation issue)

#### What It Does
Uses ATR-based dynamic bands to determine trend strength and direction:
- Bands tighten/loosen based on volatility
- Price above band = uptrend (CALL)
- Price below band = downtrend (PUT)
- More responsive than moving averages, similar to Supertrend on TradingView

#### Signals
| Condition | Direction | Confidence | Use Case |
|-----------|-----------|------------|----------|
| Price > band | CALL | min(1.0, distance / (3 * ATR)) | Strong uptrend |
| Price < band | PUT | min(1.0, distance / (3 * ATR)) | Strong downtrend |

#### Parameters
```python
SupertrendSignal(period=10, multiplier=3.0)
```

#### Why Use It
- **Volatility-aware**: Bands widen in volatile markets, narrow in quiet ones
- **Less lag than moving averages**: Reacts faster to trend changes
- **Clear visual signal**: Price crossing band = trend change
- **High quality for binary options**: Great for 30s-2m expiries

#### Current Issue
Band calculation returns NaN due to early ATR values. Forward-fill approach partially worked but needs refinement.

#### Fix Needed
1. Use exponential ATR instead of simple moving average (smoother early values)
2. Or: Use alternative ATR smoothing (Wilder's method)
3. Or: Initialize bands from first N bars directly

---

## Tier 2 vs Other Tiers

| Tier | Count | Weight > 0? | In decision_signals? | Affects TRADE? | Purpose |
|------|-------|----------|---------------------|----------------|---------|
| Tier 0 | 5 | Yes | Selective (MACD+EMA) | Only MACD+EMA | Core strategy |
| Tier 1 | 2 | No (0.0) | No | Never | Pure research |
| Tier 2 | 3 | Yes | No | Never (yet) | Research + confluence |

---

## How to Promote Tier 2 → Full Decision Signal

Once we have ~500+ resolved trades with Tier 2 signals:

1. **Run analysis**:
   ```bash
   python3 scripts/analyze_signals.py
   ```

2. **Look for**:
   - Win rate when signal agrees: > base (44.5%) by 3%+ points
   - Lift (agree vs neutral): consistently positive
   - No "opposing > base" flag (signal not inverted)

3. **If promising**:
   ```python
   # In main_v2.py, change:
   decision_signals={"MACD", "EMA_Cross"}
   # To:
   decision_signals={"MACD", "EMA_Cross", "Stochastic"}
   ```

4. **If underperforming**:
   - Remove from signals list entirely (clean up)
   - Or reduce weight and keep as research signal

---

## Collection Timeline

**Current state** (2026-06-09 07:33):
- Fresh restart with 10-signal engine
- Tier 2 signals just activated
- 0 trades with new signals yet

**Target milestones**:
- **100 resolved trades**: Early patterns emerge
- **300 resolved trades**: Statistical confidence (3%+ lift is meaningful)
- **500+ resolved trades**: Ready to promote or retire signals

---

## Testing Tier 2 Signals

### Test Individual Signal
```python
import asyncio
from signals.stochastic import StochasticSignal
import pandas as pd
import numpy as np

async def test():
    signal = StochasticSignal()
    # Create sample OHLCV data
    df = pd.DataFrame({...})
    result = await signal.evaluate(df)
    print(f"{result.direction} ({result.confidence:.1%}): {result.reason}")

asyncio.run(test())
```

### Test All Signals Together
```bash
python3 tools/v2_smoke.py --pair AUDUSD_otc
```

---

## Notes

- **Confluence scoring**: Tier 2 signals contribute to final `our_confluence_score` via weighted average of agreeing signals
- **Breakdown logging**: All signals (Tier 0/1/2) appear in `our_signal_breakdown` in decisions.jsonl
- **Research gates**: Even though Tier 2 doesn't gate trades, watching per-signal win rates guides future tuning
- **Weight tuning**: If a Tier 2 signal has 60% WR (vs 44.5% base), we might increase its weight or promote it to decision_signals

