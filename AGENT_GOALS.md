# PocketOptionBot — Agent Goals & Self-Refinement Charter

> **This document is the north star for autonomous loop agents (local and cloud).
> Read it at session start. Update it after every data-backed conclusion.**

---

## Primary Goal

**Maximize winning trades per hour, then raise stake.**

The objective function is `wins/hour = WR × trades/hour`, NOT WR in isolation.
Break-even is 52.08% at 92% payout — that's the floor, not the target.

**Key constraint:** Only add/keep a filter if it produces a NET increase in wins/hour.
If a filter cuts volume by 50% and only lifts WR by 5pts, it reduces wins/hour — reject it.
Quantify before filtering: compute WR_with × volume_with vs WR_without × volume_without.

**Income target:** $1/min = $60/hr. At 92% payout, 55% WR, $5 stake, 20 trades/hr: $0.55/min.
At 65% WR, $8 stake, 20 trades/hr: $0.88/min. At 70% WR, $8 stake, 25 trades/hr: $1.12/min.
Path: prove 55%+ WR over 200+ trades → raise stake → $1/min becomes achievable at 20-30 trades/hr.

Current state (2026-06-16): 3-6 real trades/hr at 53-70% WR. Volume is the primary bottleneck.
Trend entries: 65% WR all-time (correct). Flip entries: 53% WR bars 1-7 (above break-even).

---

## Strategy Architecture

- **Mode**: `STRATEGY_MODE=flip` — SuperTrend flip-and-continuation on 1s candles, 30s expiry.
- **Entry kinds**:
  - `flip`: SuperTrend direction reversal, wait `flip_confirm_bars` (currently 4), then enter
  - `trend`: Strong established trend — ADX≥30 + rising, price 1-2 ATR from the band
- **Universe**: `ALLOWED_PAIR_REGEX = ^(?!.*GBP).*(USD|CNY|CNH|EUR)` — USD/CNY/CNH/EUR crosses, GBP excluded
- **Shadow track**: `SHADOW_TF5S_ENABLED=true` — 5s candle shadow trades for research at 15s+30s expiry

---

## Proven Winning Zones (data-backed, 2057 flip-strategy rows)

### Trend entries (n=1053)
| Zone | n | WR |
|---|---|---|
| ADX 30-40 + dist 1-2 ATR + PUT | 46 | **65%** ✅ |
| ADX 40+ + dist 1-2 ATR + CALL | 19 | **68%** ✅ |
| ADX 30-40 + dist 1-2 ATR + CALL | 29 | **55%** ✅ |
| ADX 40+ + dist 2-2.5 ATR + CALL | 9 | **67%** ✅ |

**Trend golden rule: dist 1-2 ATR from SuperTrend band. ADX 30-40 is the sweet spot.**

### Flip entries (n=1004)
| Zone | n | WR |
|---|---|---|
| ADX 30-40 + dist 3+ ATR + PUT | 126 | **56%** ✅ |
| ADX 40+ + dist 3+ ATR + CALL | 29 | **59%** ✅ |
| ADX 30-40 + dist 2.5-3 ATR + CALL | 14 | **57%** ✅ |
| ADX 30-40 + dist 2-2.5 ATR + PUT | 10 | **60%** ✅ |

**Flip golden rule: exhaustion reversal (dist 3+ ATR) at ADX 30-40. The prior trend ran far; now reversal has room. ADX 40+ slightly better.**

### Critical asymmetry
- **Trend** optimal dist: **1-2 ATR** (close to band = confirmed direction)
- **Flip** optimal dist: **3+ ATR** (far from band = exhaustion reversal)
- These are OPPOSITE. `atr_distance_min/max` is a shared parameter — setting it wrong kills one to help the other. **Fix needed: `flip_atr_min`/`flip_atr_max` as separate FlipParams fields.**

---

## Proven Losing Zones (hard evidence, block or gate)

| Zone | n | WR | Action |
|---|---|---|---|
| ADX < 25 (all flips) | 500+ | ~47% | `adx_flip_min=25` → requires ≥30 with dead zone |
| ADX 25-30 dead zone | 434 | 47% | `flip_adx_dead_lo/hi=25/30` |
| dist 3+ ATR (trend continuations) | 400+ | 42% | `atr_distance_max` cap for trend path only |
| ADX 30-40 + dist 1-2 ATR + CALL (flip) | 8 | 25% | waiting for n≥30 to gate |
| PUT direction overall vs CALL: both bad | — | CALL 47%, PUT 50% | session regime issue, not a lever |
| USDCHF/YERUSD (5s) | — | <40% | excluded by regex |
| TNDUSD (5s) | — | 20% | excluded by `bb_width_max=25` |
| GBP pairs | — | heavy losses | excluded by regex |

---

## Active Levers (current, 2026-06-16)

### `data/flip_levers.json` (1s candles, real trades)
```json
{
  "adx_flip_min": 25,       // flips need ADX≥25; dead zone 25-30 → effective floor is 30
  "flip_adx_dead_lo": 25,
  "flip_adx_dead_hi": 30,
  "adx_trend_min": 30,
  "flip_confirm_bars": 4,   // wait 4 bars after SuperTrend flip before entry
  "flip_window_bars": 7,    // flip is "fresh" within 7 bars
  "atr_distance_min": 1.0,  // trend floor (don't enter when price hasn't moved from band)
  "atr_distance_max": 999,  // OFF for flips (flip best zone is dist3+; separate param needed)
  "bb_width_min": 2,        // demo sample pass (low volatility Asian session)
  "bb_width_max": 18,       // chop filter
  "cont_macd_gap_min": 0.5, // trend continuation momentum gate
  "cont_rsi_min": 50,       // trend: PUT needs RSI<50, CALL needs RSI>50
  "require_adx_rising": true
}
```

### `data/flip_levers_5s.json` (5s candles, shadow only)
```json
{
  "adx_flip_min": 25,
  "flip_confirm_bars": 5,   // bars 5-6 at 30s expiry = 62.5% WR (5s data)
  "flip_window_bars": 6,
  "atr_distance_min": 2.0,  // 5s data: dist<2 flips bad
  "atr_distance_max": 3.5,
  "bb_width_max": 25        // blocks TNDUSD (avg bbw=26.9, 20% WR)
}
```

---

## Self-Refinement Loop

Run every 30 minutes via cloud routine (or `python3 tools/analyze_failures.py --hours 1`):

### STEP 1 — Health check
```bash
python3 -c "import time; hb=float(open('data/heartbeat').read()); print(f'heartbeat {time.time()-hb:.0f}s ago')"
tail -5 logs/bot.log
```
Bot should heartbeat within 10s. If older → supervisor restart needed.

### STEP 2 — Trade quality scan
```bash
python3 tools/analyze_failures.py --hours 1
```
Look for:
- Overall WR vs 52.08% break-even
- Flip vs trend WR split (trend should be 55%+, flip is the refinement target)
- ADX distribution — are high-ADX entries performing?
- Post-loss window — any <30s trading? (shadow trade false alarm: shadows don't trigger cooldown)
- Blocklist candidates from optimizer section

### STEP 3 — Lever evaluation
Objective: maximize `wins/hour = WR × trades/hour`. Before any change, compute:
- Current: WR_current × volume_current
- Proposed: WR_proposed × volume_proposed
Only change if wins/hour INCREASES.

Hard floor: WR must stay above 52.08% break-even (92% payout).
Change ONE lever at a time. Log the reason in `_comment` field of the lever file.
Lever changes take effect **immediately** (mtime-cached per cycle, no restart needed).

### STEP 4 — Code change candidates
Track in this section. Code changes need bot restart:
```
run_supervised.sh will auto-restart on kill; supervisor at PID is supervisor process.
Bot restart: kill <main_v2 PID> (supervisor restarts within 5s)
```

---

## Open Code Improvements (next iterations)

### HIGH: Separate flip vs trend ATR dist params
- Problem: `atr_distance_min/max` is shared between flip and trend paths
- Flip optimal: dist 3+ ATR (exhaustion reversal)
- Trend optimal: dist 1-2 ATR (confirmed direction)
- Solution: add `flip_atr_min` / `flip_atr_max` to `FlipParams` dataclass
- Use `flip_atr_min/max` in the flip code path; keep `atr_distance_min/max` for trend only
- Then: `flip_atr_min=2.5, flip_atr_max=999` (allow exhaustion flips); `atr_distance_max=2.0` (trend cap)
- Estimated WR lift: ~3-5 pts (removes 25% WR dist1-2 flip zone, keeps 56% dist3+ flip zone)

### MEDIUM: flip_rsi_extreme gate
- Data: rsi65+ + adx30+ + PUT = 58.7% WR (n=121) vs neutral RSI + PUT = 35-40% WR
- Add `flip_rsi_extreme_min` lever (0=off): PUT requires RSI≥60, CALL requires RSI≤40
- Expected: +6-8 pts WR by filtering neutral-RSI flips

### MEDIUM: Pair-specific ADX regime
- EURUSD: 100% WR (4 trades, thin) — validate with more data
- USDEGP/LTCUSD: 36-39% WR, blocklist candidates
- Consider adding per-pair WR floor gate once n≥50 per pair

### LOW: analyze_failures shadow filtering
- Post-loss window analysis includes shadow trade losses as "last loss" reference
- Shadow losses don't trigger cooldown, so the <30s bucket is inflated by shadow→real pairs
- Fix: add `AND json_extract(data,'$.shadow')=0` to the post-loss query

---

## Key Context for Cloud Routines

The cloud agent does NOT have access to local files. Analysis must use:
- `python3 tools/analyze_failures.py --hours N` — primary analysis tool
- `data/flip_levers.json` — read to understand current state
- `logs/bot.log` — last N lines for health check
- `git log --oneline -5` — recent changes

The agent can **edit `data/flip_levers.json` and `data/flip_levers_5s.json`** to tune levers live.
It should NOT edit Python files (those need restart which the cloud agent can't trigger).

---

## What NOT to Do

1. Don't raise trade volume at the expense of WR — demo or not, we're building the live edge
2. Don't tune levers on n<30 — noise dominates, wait for sample
3. Don't add RSI/MACD gates without directional confirmation evidence (both-direction tests)
4. Don't commit `PO_SSID` or any `.env` secrets
5. Don't run two bot instances against the same SSID
