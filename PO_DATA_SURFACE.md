# PocketOption Data Surface — Discovery Report
**Date:** 2026-06-12 | **Tools:** `tools/po_probe.py` (4-phase discovery), `tools/po_sentiment_probe.py` (verifier)
**Context:** follow-up to TRADING_EDGE_MAP.md's conclusion that orthogonality must
come from *different information sources*, not more indicator variants.

## What the bot uses today
`get_candles` (150-candle flat-OHLC snapshots), `payout`, `balance`, `buy/sell`,
`check_win`, closed-deal history. That's a fraction of the surface.

## Discoveries (confirmed by probe)

### 1. ⭐ Traders' sentiment stream — per-pair crowd predictions
While a symbol subscription is active, the server pushes `[["SYMBOL", <int>]]`
messages every candle period. Verified properties:
- bounded 0–100, drifts continuously (observed 20–97 on EURUSD_otc)
- does **not** scale with candle period (ratio 1.05 at 5s vs 10s) → a
  **percentage**, not a volume/trade count
- matches the platform's "traders' choice" widget semantics

This is live crowd positioning per pair — the first data source in the project
that is *not derived from the price series*. Candidate uses: contrarian gate
(fade extreme crowd positioning), confirmation gate, or sentiment-change as a
signal. Must be validated against outcomes like everything else.

### 2. ⭐ Real OHLC exists — our candles were degenerate
- `get_candles()` (what every signal consumes today) returns **flat candles**
  (open==high==low==close price snapshots).
- `history(asset, period)` returns **real OHLC** with true wicks.
- `subscribe_symbol_timed/chunked/time_aligned` build **real OHLC live** at any
  period from raw ticks.
Implication: HeikinAshi/candle-anatomy/ATR signals have been running on
degenerate data the whole time. Switching the candle source is a
straight upgrade.

### 3. ⭐ Deep history via paging
`get_candles_advanced(asset, period, offset, time)` pages backwards seamlessly
(verified 3×150 contiguous 5s candles). History depth is no longer capped at
150 candles / 12.5 minutes — full backtesting datasets are fetchable.

### 4. Raw tick stream
`subscribe_symbol` delivers ~2.3 ticks/sec with sub-second timestamps
(`[sym, ts.ms, price]` on the `updateStream` channel). `updateHistoryNewFast`
returns tick-level history on demand. Unlocks tick-scale microstructure
diagnostics (the variance-ratio/autocorrelation tests at their natural scale).

### 5. Other unused surface
- `get_server_time()` (returns an offset, not epoch — handle accordingly)
- `opened_deals()/get_opened_deal()` rich live-deal objects
- `open_pending_order` / `cancel_pending_order(s)` — scheduled entries
- `compile_candles(asset, custom_period, lookback)` — custom candles from
  stored tick history
- raw WS access: `create_raw_handler(Validator.custom(...))` + `wait_next()`
  (NOT an async iterator), `send_raw_message`

## Constraints
- **One WS session per SSID** — collectors can't run beside the bot as separate
  processes; sentiment/tick collection must be integrated into the bot's own
  connection (or run while the bot is paused).
- `subscribe_symbol*` consumes subscription slots (`max_subscriptions()`).
- Asset metadata contains no sentiment field — it only arrives on the stream.

## Proposed build-out (in order of expected value)
1. **Sentiment collector inside the bot loop** — subscribe the top-N scan pairs
   (timed, 30s period), log `{ts, pair, sentiment}` to `data/sentiment.jsonl`,
   and stamp the current sentiment onto every DecisionRow. After ~1 day:
   sentiment-vs-outcome analysis (follow/fade/extremes), the same gate
   discipline as previous experiments.
2. **Switch signal candles to real OHLC** — use `history()` per pair (102+
   real candles) instead of flat `get_candles`; re-baseline the candle-anatomy
   signals on non-degenerate data.
3. **Deep-history fetcher** (`get_candles_advanced` paging) — pull 10k+ candles
   per pair once, rerun the process diagnostics with real statistical power.
4. **Tick-scale diagnostics** — variance ratio + autocorrelation on raw ticks.

## Honest caveat
None of this changes the 52.1% break-even math. Sentiment is worth testing
precisely because it's orthogonal to price — but it gets the same treatment:
shadow-grade evidence, pooled across days, promotion gate before real stakes.
