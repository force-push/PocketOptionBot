# Trading Edge Map — Where the Bot Trades Best
**Date:** 2026-06-11 | **Method:** all signal combos discussed to date, evaluated
uniformly on 1,622 deduplicated resolved setups (real + all shadow kinds, one
per cycle+pair) since the modern config (2026-06-10 14:54 UTC), scored against
the actual market direction. Day-split shown for stability.
**Companion docs:** SHADOW_TRADE_ANALYSIS.md (full history), tools/unanimity_checkpoint.py (live gate).

---

## The one table that matters

| Rule | Accuracy | n | Day 1 / Day 2 | Verdict |
|---|---|---|---|---|
| follow majority (any margin) | 49.6% | 1,174 | 49% / 57% | dead |
| follow ≥5 agree | 49.5% | 925 | 48% / 59% | dead |
| follow ≥6 agree | 49.7% | 717 | 49% / 59% | dead |
| **follow ≥7 agree** | **53.2%** | 468 | 52% / 60% | marginal — above break-even |
| **follow ≥8 agree** | **61.4%** | 70 | 57% / (n=7) | **the edge — rare but strong** |
| fade ≥7 agree | 46.8% | 468 | 48% / 40% | dead (formally failed its gate) |
| follow ADX conf ≥0.4 | 51.2% | 365 | 50% / 60% | noise |
| follow ADX conf ≥0.6 | 46.8% | 109 | 46% / · | **dead — retrospective 57% was a mirage** |
| trend-bloc ≥6, NO oscillator joined | 47.3% | 529 | 47% / 54% | below water |
| **trend-bloc ≥6 + ≥1 oscillator joined** | **55.5%** | 110 | 53% / · | **the mechanism behind ≥8** |
| trend-bloc ≥6, ≥2 oscillators opposing | 47.2% | 496 | 46% / 56% | below water |

**The agreement gradient is monotone and sharp:** 50% flat through ≥6, then
53.2% at ≥7, 61.4% at ≥8. Nothing gradual — the edge only exists at extreme
depth.

**The mechanism (from the bloc decomposition):** the 11 signals are two
anti-correlated factors — a 7-signal trend bloc and a 3-signal oscillator bloc
that normally opposes it. A strong trend reading alone (trend-bloc ≥6, no
oscillator) wins only 47.3%. The same trend reading **with the oscillator bloc
flipped to agree** wins 55.5%. Reaching 8+ total agreement *requires* that
flip, which is why ≥8 is the best cell. Interpretation: oscillator capitulation
into a strong trend marks continuation on this feed — the opposite of the
exhaustion story the (now-failed) fade experiment assumed.

## Context cuts

| Cut | Result |
|---|---|
| **Pair class** | **crypto 54.6% (240)** · fx/exotic 49.2% (1,157) · stocks 46.2% (225) |
| Best pairs (n≥40) | BITB 60%, NGNUSD 55%, DOTUSD 55%, BTCUSD 54% — 3 of 4 crypto |
| Worst pairs (n≥40) | TNDUSD 38%, USDBRL 40%, AUDNZD 41%, #FB 41% |
| Direction | CALL 48.7% vs PUT 50.5% — noise |
| Confluence score | 0.4-bucket (46%) WORSE than 0.0-bucket (51%) — score is anti-predictive, ignore it |
| Hours | 43–63% scatter, no stable structure (filter already disabled) |
| Expiry | 216s ~52%, 300s ~48% — no longer-horizon edge confirmed |

**Crypto hypothesis:** PO's crypto OTC feeds appear anchored to real 24/7
exchange prices (BTC/DOGE/DOT track real markets), unlike synthetic exotic-FX
feeds. Real markets carry real short-term momentum — which would explain why
the trend-confirmation edge concentrates there. Stocks OTC (synthetic outside
market hours) are the worst class, consistent with this.

## What is conclusively dead (do not revisit without new data)

1. Signal weighting / reweighting (tested out-of-sample: 48.9%)
2. Fade-unanimity (gate failed: 46.8% at n=468; the 06-09 "edge" inverted)
3. ADX-regime (monotone wrong: higher conf = worse)
4. Time-of-day hour tables (don't replicate day to day)
5. Confluence score as a quality gate (anti-predictive)
6. Expiry > 30s (no improvement at 216/300s)
7. Linear price-history strategies generally (feed is a random walk; ceiling ~51.3%)

## Where the bot trades best — the profile

> **Follow the signal direction only when ≥8 of 11 signals agree (i.e. the
> oscillator bloc has capitulated into a strong trend), preferentially on
> crypto OTC pairs. Ignore ADX, the confluence score, the hour, and expiry
> variations — trade 30s.**

Measured performance of the components: ≥8-agree 61.4% (n=70, three
independent measurements at 60–61%); crypto class +5pts over baseline.
At 60% WR and 92% payout, EV ≈ +15% of stake per trade. Fire rate ~4% of
evaluated setups (~40–70 opportunities/day at current scan volume).

## Caveats (read before promoting)

- **n=70 on the core rule.** The same feed flipped the unanimity edge once
  already. The promotion gate stands: ≥55% over ≥400 resolved spanning ≥3 UTC
  days each ≥52% (tools/unanimity_checkpoint.py tracks it live).
- Day 2 is young; day-3 data lands 2026-06-12/13.
- The crypto cut and the ≥8 cut overlap on only a handful of trades so far —
  the combined cell is promising but unmeasured at scale.
- Non-stationarity is the house's weapon: re-run this map weekly.
