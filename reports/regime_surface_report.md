# Regime Surface Research

Generated: 2026-06-23T12:03:31+00:00
Scope: last 48h

Research-only. This report reads resolved real trades from `data/decisions.db` and does not change live policy.

## Headline

- Trades analysed: 970
- Win rate: 52.9% vs break-even 52.1%
- PnL: $+6.45
- Avg/trade: $+0.007

## Feature Construction

- Momentum pressure: direction-aligned DI imbalance, RSI, MACD gap expansion, MACD sign consistency, trend age.
- Volatility pressure: ATR bps, Bollinger width bps, MACD gap std, ADX.
- Shock pressure: ATR bps + positive gap expansion + MACD instability.
- Buckets are quartiles within the analysed sample, so labels are relative to current Argus history.

## Regime Label

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
clean_trend_low_vol |  289 |  56.4% | $ +50.50 | $+0.175 | KEEP?
vol-midhigh_mom-extended |   32 |  59.4% | $ +18.46 | $+0.577 | KEEP?
calm_compression |   71 |  54.9% | $ +13.33 | $+0.188 | KEEP?
vol-midhigh_mom-neutral |   49 |  51.0% | $  -2.15 | $-0.044 | MIXED
vol-midlow_mom-neutral |   50 |  50.0% | $  -8.45 | $-0.169 | KILL?
weak_continuation |   34 |  35.3% | $ -12.89 | $-0.379 | KILL?
vol-midlow_mom-against |   51 |  52.9% | $ -15.50 | $-0.304 | MIXED
shock_trend_follow |  114 |  52.6% | $ -23.10 | $-0.203 | MIXED
vol-midhigh_mom-against |   76 |  47.4% | $ -25.03 | $-0.329 | KILL?
shock_chop_or_fade |  129 |  48.1% | $ -27.64 | $-0.214 | KILL?

## Volatility x Momentum Surface

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
vol-high / mom-against |   90 |  58.9% | $ +48.68 | $+0.541 | KEEP?
vol-low / mom-extended |   80 |  61.3% | $ +39.05 | $+0.488 | KEEP?
vol-midhigh / mom-aligned |   46 |  65.2% | $ +17.62 | $+0.383 | KEEP?
vol-midlow / mom-extended |   67 |  49.3% | $ +10.28 | $+0.153 | MIXED
vol-low / mom-aligned |   92 |  56.5% | $  +6.05 | $+0.066 | KEEP?
vol-high / mom-aligned |   46 |  54.3% | $  +1.89 | $+0.041 | KEEP?
vol-midhigh / mom-extended |   42 |  54.8% | $  -1.71 | $-0.041 | MIXED
vol-low / mom-neutral |   59 |  50.8% | $  -4.27 | $-0.072 | MIXED
vol-high / mom-extended |   54 |  46.3% | $  -5.93 | $-0.110 | KILL?
vol-midlow / mom-aligned |   58 |  56.9% | $  -6.73 | $-0.116 | MIXED
vol-midlow / mom-against |   53 |  52.8% | $ -10.32 | $-0.195 | MIXED
vol-midhigh / mom-neutral |   66 |  47.0% | $ -11.67 | $-0.177 | KILL?
vol-midlow / mom-neutral |   64 |  46.9% | $ -15.69 | $-0.245 | KILL?
vol-high / mom-neutral |   53 |  43.4% | $ -36.39 | $-0.687 | KILL?
vol-midhigh / mom-against |   88 |  44.3% | $ -41.99 | $-0.477 | KILL?

## Shock x Entry Kind

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
shock-low / flip |  160 |  58.8% | $ +75.69 | $+0.473 | KEEP?
shock-midlow / trend |   31 |  64.5% | $ +15.68 | $+0.506 | KEEP?
shock-midhigh / trend |   30 |  43.3% | $  +3.72 | $+0.124 | MIXED
shock-midhigh / flip |  212 |  56.1% | $  -6.57 | $-0.031 | MIXED
shock-midlow / flip |  211 |  49.8% | $ -15.56 | $-0.074 | KILL?
shock-low / trend |   83 |  48.2% | $ -15.77 | $-0.190 | KILL?
shock-high / flip |  227 |  50.2% | $ -47.64 | $-0.210 | MIXED

## Regime x Direction

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
clean_trend_low_vol / CALL |  271 |  56.8% | $ +56.81 | $+0.210 | KEEP?
calm_compression / CALL |   69 |  55.1% | $ +10.28 | $+0.149 | KEEP?
shock_chop_or_fade / CALL |   64 |  56.2% | $  +7.69 | $+0.120 | KEEP?
shock_trend_follow / PUT |   66 |  53.0% | $  -1.73 | $-0.026 | MIXED
vol-midlow_mom-neutral / CALL |   43 |  48.8% | $  -3.57 | $-0.083 | KILL?
vol-midhigh_mom-neutral / PUT |   39 |  43.6% | $ -12.29 | $-0.315 | KILL?
vol-midlow_mom-against / CALL |   33 |  51.5% | $ -17.76 | $-0.538 | MIXED
shock_trend_follow / CALL |   48 |  52.1% | $ -21.37 | $-0.445 | MIXED
vol-midhigh_mom-against / PUT |   63 |  46.0% | $ -31.04 | $-0.493 | KILL?
shock_chop_or_fade / PUT |   65 |  40.0% | $ -35.33 | $-0.544 | KILL?

## Regime x Entry Kind

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
clean_trend_low_vol / flip |  230 |  57.0% | $ +52.73 | $+0.229 | KEEP?
calm_compression / flip |   51 |  58.8% | $ +21.10 | $+0.414 | KEEP?
vol-midhigh_mom-neutral / flip |   49 |  51.0% | $  -2.15 | $-0.044 | MIXED
clean_trend_low_vol / trend |   59 |  54.2% | $  -2.23 | $-0.038 | MIXED
vol-midlow_mom-neutral / flip |   50 |  50.0% | $  -8.45 | $-0.169 | KILL?
weak_continuation / trend |   34 |  35.3% | $ -12.89 | $-0.379 | KILL?
vol-midlow_mom-against / flip |   51 |  52.9% | $ -15.50 | $-0.304 | MIXED
shock_trend_follow / flip |  104 |  51.9% | $ -23.24 | $-0.223 | MIXED
shock_chop_or_fade / flip |  123 |  48.8% | $ -24.40 | $-0.198 | KILL?
vol-midhigh_mom-against / flip |   76 |  47.4% | $ -25.03 | $-0.329 | KILL?

## Pair x Regime Candidates

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
MATIC_otc / clean_trend_low_vol |   52 |  67.3% | $ +51.57 | $+0.992 | KEEP?
USDRUB_otc / clean_trend_low_vol |   53 |  62.3% | $ +22.85 | $+0.431 | KEEP?
OMRCNY_otc / calm_compression |   21 |  66.7% | $ +22.22 | $+1.058 | 
OMRCNY_otc / clean_trend_low_vol |   69 |  59.4% | $ +19.54 | $+0.283 | KEEP?
MADUSD_otc / shock_chop_or_fade |   56 |  57.1% | $ +12.81 | $+0.229 | KEEP?
AUDUSD_otc / vol-midhigh_mom-aligned |   17 |  64.7% | $  +7.68 | $+0.452 | 
MATIC_otc / calm_compression |   18 |  66.7% | $  +5.58 | $+0.310 | 
DOGE_otc / shock_trend_follow |   22 |  59.1% | $  +4.47 | $+0.203 | 
USDARS_otc / vol-midlow_mom-neutral |   19 |  52.6% | $  +1.67 | $+0.088 | 

## UTC Hour x Regime Candidates

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
14Z / clean_trend_low_vol |   21 |  76.2% | $ +13.64 | $+0.650 | 
12Z / clean_trend_low_vol |   18 |  66.7% | $ +11.61 | $+0.645 | 
21Z / clean_trend_low_vol |   15 |  66.7% | $ +11.54 | $+0.770 | 
06Z / clean_trend_low_vol |   17 |  58.8% | $ +11.32 | $+0.666 | 
05Z / shock_trend_follow |   17 |  64.7% | $  +8.30 | $+0.488 | 
10Z / clean_trend_low_vol |   24 |  62.5% | $  +7.01 | $+0.292 | 
09Z / clean_trend_low_vol |   20 |  65.0% | $  +6.65 | $+0.333 | 

## Interpretation

Promote nothing from this report directly into live trading. Treat positive buckets as hypotheses for a shadow gate or a locked walk-forward test.

Strong pair/regime hypotheses:
- MATIC_otc / clean_trend_low_vol: n=52, WR=67.3%, PnL=$+51.57
- USDRUB_otc / clean_trend_low_vol: n=53, WR=62.3%, PnL=$+22.85
- OMRCNY_otc / clean_trend_low_vol: n=69, WR=59.4%, PnL=$+19.54
- MADUSD_otc / shock_chop_or_fade: n=56, WR=57.1%, PnL=$+12.81

Weak pair/regime avoid-list candidates:
- AUDUSD_otc / vol-midhigh_mom-neutral: n=30, WR=46.7%, PnL=$-7.36
