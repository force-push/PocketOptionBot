# Signal Strategy Research & Changes

**Status:** Active — changes applied 2026-06-09, validating live in demo.
**Goal:** raise win rate from ~45% toward 60% (break-even is 52.1% at 92% payout).

This document records the data analysis behind the strategy changes made on 2026-06-09,
the reasoning for each change, the honest caveats, and candidate signals to test next.

---

## 1. Method

The decision log (`data/decisions.jsonl`) was **censored**: outcomes only existed for
trades that passed every gate, so we never saw what happened on the trades we skipped.
`SHADOW_RECORD_MODE` (DEMO only) was enabled 2026-06-08 to trade-and-record the
would-be-skipped cases and build an uncensored dataset. Analysis below is over **411
resolved (win/loss) trades** collected to 2026-06-09 00:48 ACST, via
`scripts/analyze_signals.py` plus ad-hoc filter intersection tests.

Break-even reference: at 92% payout, win rate must exceed **1/(1+0.92) = 52.1%**.

---

## 2. Findings

### 2.1 The bot has no edge as it was running
- Base win rate **45.1%** (n=411), i.e. **−7 points** below break-even. Unprofitable.

### 2.2 Our TA confluence was *anti*-predictive (the key discovery)
- **More agreement was worse:** 3 signals agreeing → **32.5%** WR vs 2 agreeing → 46.5%.
- `our_confluence` score correlated **−0.27** with wins (earlier calibrator run).
- **`ta_disagree` shadow trades won 54.5%** (n=33): when our TA disagreed with the bot
  and we traded the bot's direction anyway, we *won above break-even*. Our TA disagreement
  was a signal that **the bot was right** — our confluence layer was destroying the bot's edge.

### 2.3 Per-signal attribution (win rate when the signal agrees with the trade)
| Signal | Verdict |
|---|---|
| **MACD** | Workhorse — agrees ~86%; opposing → 33% (so its agreement matters) |
| **EMA_Cross** | Workhorse — same profile as MACD |
| **RSI** | Noise — ~45% regardless of agree/neutral/oppose |
| **Bollinger** | Weak / possibly inverted — opposing (50%) ≥ agreeing (50%) > neutral (44%) |
| **CandlePattern** | **Dead** — produced a direction in 0/411 trades |

Only **MACD + EMA** carry a positive edge.

### 2.4 The bot's own signal *is* the edge
- **`bot_win_rate ≥ 0.80` → 54.3%** (n=116) vs 0.7–0.8 → 41.7%, 0.6–0.7 → 40%.
  The broker bot's stated win rate is genuinely predictive at the top end.
- **`bot_is_top_pick` → 48.7%** vs 39.9% (but redundant once `bot_win_rate ≥ 0.8`).

### 2.5 Pair selection is a huge lever
| Pair | WR | n |
|---|---|---|
| USDCOP_otc | 61.5% | 13 |
| AUDUSD_otc | 53.0% | 181 |
| USDMXN_otc | 50.0% | 10 |
| EURUSD_otc | 36.7% | 30 |
| AUDCHF_otc | 33.3% | 18 |
| USDARS_otc | 18.2% | 11 |

### 2.6 The skips that were *correct*
- `no_direction` shadow trades won only **29.5%** (n=44) → keep skipping when our decision
  signals give no direction.

### 2.7 Stacking the supported filters → clears 60%
| Strategy | WR | n |
|---|---|---|
| Base (all trades) | 45.0% | 411 |
| `bot_win_rate ≥ 0.8` | 54.3% | 116 |
| good pair + `bwr≥0.8` | 58.4% | 89 |
| **good pair + `bwr≥0.8` + MACD&EMA agree** | **62.3%** | **77** |

---

## 3. Changes applied (2026-06-09)

| # | Change | File | Reason |
|---|---|---|---|
| 1 | `PAIR_SELECT_MIN_WIN_RATE` 0.0 → **0.80** | `.env` | §2.4 — single biggest lever (45→54%). The validated "82% rule". |
| 2 | `BLOCKED_PAIRS` expanded to add AUDCHF, USDARS, EURTRY, USDPHP, CHFNOK | `.env` | §2.5 — empirical losers even when bot-rated highly. |
| 3 | Confluence gate decides on **MACD + EMA only** (`decision_signals`) | `signals/confluence.py`, `main_v2.py` | §2.2–2.3 — RSI/Bollinger/CandlePattern are noise/negative; 3-agree < 2-agree. Others still **recorded** in the breakdown for research. |
| 4 | Keep the `no_direction` skip | (unchanged) | §2.6 — confirmed correct (29.5%). |

`SHADOW_RECORD_MODE` stays **on** so we keep collecting validation data *within* the
high-quality pair set and can confirm the live filtered win rate tracks the ~60% estimate.

### Caveats (read before trusting)
- **Sample size:** the 62.3% cell is n=77 → 95% CI ≈ **51–72%**. Treat as "high-50s to
  low-60s", not a guarantee. The robust components are AUDUSD (n=181), `bwr≥0.8` (n=116),
  and MACD+EMA. The small-n pairs (USDMXN n=10, USDCOP n=13) and the pair blacklist are
  the most overfit-prone.
- **Volume tradeoff:** the filtered strategy trades ~19% as often. Acceptable for binary
  options (quality ≫ quantity), but win-rate must be re-checked on fresh post-change data,
  not the data it was derived from.
- **OTC pairs are broker-synthetic** — these results are specific to PocketOption's OTC feed
  and may not transfer to real forex.

---

## 4. Candidate TA signals to test next

MACD + EMA are both **trend-following** and correlated, so they fail together in choppy
markets — which is likely why even the workhorses only win ~47% unfiltered. The highest-value
additions are *orthogonal*: trend-strength and volatility **filters**, plus one or two
direction confirmers that are not just another moving-average cross.

Discipline: add each as an **observation-only signal first** (recorded in the breakdown but
NOT in `decision_signals`), let shadow mode collect ~1 week, then `analyze_signals.py` to
measure its real correlation with win rate on *our* data. Promote to a decision signal only
if it shows positive lift. Measure before trusting — same as everything above.

### Tier 1 — filters (orthogonal to MACD/EMA, highest expected value)
- **ADX / DMI (trend strength).** MACD+EMA only work when a trend exists. Gate trades on
  `ADX > 25`. Directly targets the choppy-market losses. *Recommended first.*
- **ATR (volatility regime).** Skip dead/flat OTC periods and extreme-whipsaw periods;
  trade only inside a healthy normalized-ATR band.

### Tier 2 — direction confirmers (could become decision signals)
- **Supertrend (ATR-based).** Clean CALL/PUT, popular for short expiries, bakes in volatility
  via ATR. Strong complement to MACD/EMA; the canonical "Supertrend + ADX" short-term stack.
- **Parabolic SAR.** Trend direction + early reversal flag; responsive on short timeframes.
- **Heikin-Ashi trend.** Smoothed candles cut OTC noise; consecutive HA colour = persistence.

### Tier 3 — momentum/exhaustion (use cautiously alongside a trend core)
- **Stochastic / Stoch-RSI.** Better than plain RSI for short-term entries (our RSI was noise,
  but a fast Stochastic catches momentum shifts differently).
- **Rate of Change / Momentum.** Simple, fast, directional.

### Not recommended
- **VWAP** — needs reliable volume; OTC synthetic volume is untrustworthy.
- **Ichimoku** — comprehensive but too laggy for 30s expiry.

The infrastructure for this is already in place: `decision_signals` lets a signal be recorded
without affecting trades, and `analyze_signals.py` reports per-signal agree/neutral/oppose win
rates — so each candidate can be A/B-measured cheaply before it ever gates a real trade.

---
*See also: `docs/probability-calibration.md`, `scripts/analyze_signals.py`,
second-brain `[[2026-06-08-pocketoptionbot-signal-calibration]]`.*
