# Regime Surface Research

Generated: 2026-06-23T12:03:32+00:00
Scope: all history

Research-only. This report reads resolved real trades from `data/decisions.db` and does not change live policy.

## Headline

- Trades analysed: 2721
- Win rate: 51.9% vs break-even 52.1%
- PnL: $-210.66
- Avg/trade: $-0.077

## Feature Construction

- Momentum pressure: direction-aligned DI imbalance, RSI, MACD gap expansion, MACD sign consistency, trend age.
- Volatility pressure: ATR bps, Bollinger width bps, MACD gap std, ADX.
- Shock pressure: ATR bps + positive gap expansion + MACD instability.
- Buckets are quartiles within the analysed sample, so labels are relative to current Argus history.

## Regime Label

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
vol-midlow_mom-neutral |  129 |  58.1% | $ +19.68 | $+0.153 | KEEP?
vol-high_mom-against |   30 |  56.7% | $ +16.10 | $+0.537 | KEEP?
vol-midhigh_mom-neutral |  104 |  52.9% | $  +0.65 | $+0.006 | 
vol-midhigh_mom-aligned |   95 |  52.6% | $  -4.21 | $-0.044 | MIXED
weak_continuation |  105 |  47.6% | $  -5.51 | $-0.053 | KILL?
calm_compression |  234 |  52.1% | $  -8.16 | $-0.035 | MIXED
shock_trend_follow |  290 |  52.1% | $ -13.67 | $-0.047 | MIXED
vol-midhigh_mom-extended |   99 |  47.5% | $ -23.69 | $-0.239 | KILL?
vol-midhigh_mom-against |  247 |  50.6% | $ -23.90 | $-0.097 | MIXED
clean_trend_low_vol |  835 |  53.8% | $ -27.35 | $-0.033 | MIXED
vol-midlow_mom-against |   97 |  47.4% | $ -45.21 | $-0.466 | KILL?
shock_chop_or_fade |  390 |  50.5% | $ -85.27 | $-0.219 | MIXED

## Volatility x Momentum Surface

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
vol-midlow / mom-extended |  185 |  61.1% | $ +70.53 | $+0.381 | KEEP?
vol-low / mom-aligned |  216 |  57.4% | $ +26.65 | $+0.123 | KEEP?
vol-high / mom-aligned |  133 |  51.9% | $ +14.55 | $+0.109 | 
vol-high / mom-against |  252 |  54.0% | $  +7.94 | $+0.032 | 
vol-midlow / mom-neutral |  172 |  55.2% | $  +7.67 | $+0.045 | KEEP?
vol-midhigh / mom-aligned |  118 |  53.4% | $  +2.08 | $+0.018 | 
vol-low / mom-neutral |  193 |  53.4% | $  -2.00 | $-0.010 | MIXED
vol-low / mom-against |   41 |  46.3% | $  -6.16 | $-0.150 | KILL?
vol-high / mom-extended |  135 |  47.4% | $ -19.03 | $-0.141 | KILL?
vol-midlow / mom-against |  110 |  50.0% | $ -26.54 | $-0.241 | KILL?
vol-midhigh / mom-neutral |  155 |  49.0% | $ -29.03 | $-0.187 | KILL?
vol-midhigh / mom-against |  278 |  50.0% | $ -30.31 | $-0.109 | KILL?
vol-midhigh / mom-extended |  129 |  48.8% | $ -44.22 | $-0.343 | KILL?
vol-low / mom-extended |  231 |  49.8% | $ -58.15 | $-0.252 | KILL?
vol-high / mom-neutral |  160 |  46.9% | $ -60.12 | $-0.376 | KILL?
vol-midlow / mom-aligned |  213 |  48.4% | $ -64.53 | $-0.303 | KILL?

## Shock x Entry Kind

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
shock-midlow / flip |  587 |  54.9% | $ +52.49 | $+0.089 | KEEP?
shock-midlow / trend |   93 |  55.9% | $  +8.26 | $+0.089 | KEEP?
shock-high / trend |   65 |  56.9% | $  -0.24 | $-0.004 | MIXED
shock-low / flip |  442 |  52.9% | $  -2.29 | $-0.005 | MIXED
shock-midhigh / trend |   75 |  37.3% | $ -25.23 | $-0.336 | KILL?
shock-low / trend |  239 |  44.8% | $ -59.53 | $-0.249 | KILL?
shock-midhigh / flip |  605 |  53.1% | $ -85.42 | $-0.141 | MIXED
shock-high / flip |  615 |  50.6% | $ -98.70 | $-0.160 | MIXED

## Regime x Direction

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
vol-midhigh_mom-against / CALL |   72 |  58.3% | $ +30.38 | $+0.422 | KEEP?
vol-midlow_mom-neutral / CALL |  107 |  59.8% | $ +29.76 | $+0.278 | KEEP?
vol-midhigh_mom-neutral / CALL |   41 |  58.5% | $ +17.02 | $+0.415 | KEEP?
vol-high_mom-against / PUT |   30 |  56.7% | $ +16.10 | $+0.537 | KEEP?
weak_continuation / PUT |   50 |  52.0% | $  +9.22 | $+0.184 | 
shock_trend_follow / PUT |  176 |  51.1% | $  +8.90 | $+0.051 | 
vol-midhigh_mom-aligned / CALL |   39 |  56.4% | $  +7.20 | $+0.185 | KEEP?
clean_trend_low_vol / CALL |  636 |  55.0% | $  +2.59 | $+0.004 | KEEP?
calm_compression / PUT |   51 |  51.0% | $  -3.66 | $-0.072 | MIXED
calm_compression / CALL |  183 |  52.5% | $  -4.50 | $-0.025 | MIXED
vol-midhigh_mom-extended / CALL |   50 |  48.0% | $  -7.33 | $-0.147 | KILL?
vol-midhigh_mom-aligned / PUT |   56 |  50.0% | $ -11.41 | $-0.204 | KILL?
weak_continuation / CALL |   55 |  43.6% | $ -14.73 | $-0.268 | KILL?
vol-midhigh_mom-extended / PUT |   49 |  46.9% | $ -16.36 | $-0.334 | KILL?
vol-midhigh_mom-neutral / PUT |   63 |  49.2% | $ -16.36 | $-0.260 | KILL?
shock_trend_follow / CALL |  114 |  53.5% | $ -22.57 | $-0.198 | MIXED
clean_trend_low_vol / PUT |  199 |  49.7% | $ -29.94 | $-0.150 | KILL?
shock_chop_or_fade / CALL |  162 |  53.1% | $ -31.21 | $-0.193 | MIXED
vol-midlow_mom-against / CALL |   70 |  45.7% | $ -39.09 | $-0.558 | KILL?
shock_chop_or_fade / PUT |  228 |  48.7% | $ -54.06 | $-0.237 | KILL?
vol-midhigh_mom-against / PUT |  175 |  47.4% | $ -54.28 | $-0.310 | KILL?

## Regime x Entry Kind

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
vol-midlow_mom-neutral / flip |  129 |  58.1% | $ +19.68 | $+0.153 | KEEP?
clean_trend_low_vol / flip |  668 |  55.7% | $ +17.20 | $+0.026 | KEEP?
vol-high_mom-against / flip |   30 |  56.7% | $ +16.10 | $+0.537 | KEEP?
shock_trend_follow / trend |   43 |  60.5% | $  +4.80 | $+0.112 | KEEP?
calm_compression / flip |  174 |  54.6% | $  +4.32 | $+0.025 | KEEP?
vol-midhigh_mom-neutral / flip |  104 |  52.9% | $  +0.65 | $+0.006 | 
vol-midhigh_mom-aligned / flip |   69 |  52.2% | $  -0.78 | $-0.011 | MIXED
weak_continuation / trend |  105 |  47.6% | $  -5.51 | $-0.053 | KILL?
calm_compression / trend |   60 |  45.0% | $ -12.49 | $-0.208 | KILL?
shock_trend_follow / flip |  247 |  50.6% | $ -18.47 | $-0.075 | MIXED
vol-midhigh_mom-against / flip |  247 |  50.6% | $ -23.90 | $-0.097 | MIXED
vol-midhigh_mom-extended / flip |   72 |  48.6% | $ -25.32 | $-0.352 | KILL?
clean_trend_low_vol / trend |  167 |  46.1% | $ -44.55 | $-0.267 | KILL?
vol-midlow_mom-against / flip |   97 |  47.4% | $ -45.21 | $-0.466 | KILL?
shock_chop_or_fade / flip |  368 |  50.5% | $ -80.23 | $-0.218 | MIXED

## Pair x Regime Candidates

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
MATIC_otc / clean_trend_low_vol |   66 |  66.7% | $ +53.00 | $+0.803 | KEEP?
USDARS_otc / vol-midlow_mom-neutral |   30 |  66.7% | $ +24.47 | $+0.816 | KEEP?
SYPUSD_otc / shock_trend_follow |   34 |  64.7% | $ +23.34 | $+0.686 | KEEP?
OMRCNY_otc / calm_compression |   36 |  58.3% | $ +19.29 | $+0.536 | KEEP?
OMRCNY_otc / clean_trend_low_vol |   94 |  56.4% | $ +16.84 | $+0.179 | KEEP?
USDRUB_otc / clean_trend_low_vol |   86 |  60.5% | $ +16.67 | $+0.194 | KEEP?
AUDUSD_otc / vol-midhigh_mom-aligned |   30 |  63.3% | $ +13.62 | $+0.454 | KEEP?
MADUSD_otc / shock_chop_or_fade |  109 |  60.6% | $ +13.41 | $+0.123 | KEEP?
DOGE_otc / vol-high_mom-against |   15 |  53.3% | $ +10.68 | $+0.712 | 
#MCD_otc / vol-midhigh_mom-extended |   15 |  66.7% | $ +10.36 | $+0.691 | 
GBPJPY_otc / shock_trend_follow |   28 |  53.6% | $ +10.13 | $+0.362 | 
QARCNY_otc / clean_trend_low_vol |   21 |  61.9% | $  +8.23 | $+0.392 | 
AMD_otc / clean_trend_low_vol |   39 |  53.8% | $  +7.11 | $+0.182 | 
#MCD_otc / vol-midlow_mom-neutral |   25 |  60.0% | $  +5.84 | $+0.234 | 
CHFJPY_otc / vol-midhigh_mom-against |   17 |  52.9% | $  +4.64 | $+0.273 | 
AUDUSD_otc / weak_continuation |   21 |  61.9% | $  +4.44 | $+0.212 | 

## UTC Hour x Regime Candidates

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---
07Z / vol-midhigh_mom-against |   28 |  57.1% | $ +18.76 | $+0.670 | 
21Z / clean_trend_low_vol |   51 |  62.7% | $ +18.34 | $+0.360 | KEEP?
07Z / shock_chop_or_fade |   46 |  54.3% | $ +16.49 | $+0.359 | KEEP?
09Z / clean_trend_low_vol |   25 |  68.0% | $ +14.71 | $+0.589 | 
22Z / clean_trend_low_vol |   28 |  60.7% | $ +10.95 | $+0.391 | 
05Z / shock_chop_or_fade |   41 |  65.9% | $ +10.08 | $+0.246 | KEEP?
02Z / clean_trend_low_vol |   28 |  64.3% | $  +8.92 | $+0.318 | 
03Z / clean_trend_low_vol |   15 |  66.7% | $  +8.16 | $+0.544 | 
14Z / clean_trend_low_vol |   16 |  75.0% | $  +8.11 | $+0.507 | 
12Z / clean_trend_low_vol |   28 |  60.7% | $  +7.68 | $+0.274 | 
17Z / clean_trend_low_vol |   32 |  59.4% | $  +7.17 | $+0.224 | KEEP?

## Interpretation

Promote nothing from this report directly into live trading. Treat positive buckets as hypotheses for a shadow gate or a locked walk-forward test.

Strong pair/regime hypotheses:
- MATIC_otc / clean_trend_low_vol: n=66, WR=66.7%, PnL=$+53.00
- USDARS_otc / vol-midlow_mom-neutral: n=30, WR=66.7%, PnL=$+24.47
- SYPUSD_otc / shock_trend_follow: n=34, WR=64.7%, PnL=$+23.34
- OMRCNY_otc / calm_compression: n=36, WR=58.3%, PnL=$+19.29
- OMRCNY_otc / clean_trend_low_vol: n=94, WR=56.4%, PnL=$+16.84
- USDRUB_otc / clean_trend_low_vol: n=86, WR=60.5%, PnL=$+16.67
- AUDUSD_otc / vol-midhigh_mom-aligned: n=30, WR=63.3%, PnL=$+13.62
- MADUSD_otc / shock_chop_or_fade: n=109, WR=60.6%, PnL=$+13.41

Weak pair/regime avoid-list candidates:
- AUDUSD_otc / vol-midhigh_mom-neutral: n=43, WR=41.9%, PnL=$-19.79
- #MCD_otc / clean_trend_low_vol: n=35, WR=45.7%, PnL=$-14.36
