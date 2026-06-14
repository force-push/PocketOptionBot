# Feature Request: Raw Tick Accumulator for Sub-Second Flip Detection

## Background

**Current state (FlipStreamer, as of 2026-06-14):**  
`strategy/flip_streamer.py` subscribes to 1s candle streams via `api.create_timed_stream(pair, seconds)` (`subscribe_symbol_timed` in the library). It evaluates `evaluate_flip()` each time a 1s bar closes. Entry lag: ~1s after the bar closes — so typically 1–2s from the actual price move.

**The problem with 1s bar close:**  
The flip (SuperTrend crossing) happens at a tick inside the bar. Waiting for the bar to close means the entry is 0–1s late. On a 5s expiry, 1s is 20% of the trade duration — meaningful slippage against a sharp reversal.

**The browser's data source:**  
PocketOption's WebSocket emits raw price ticks as binary frames at ~500ms cadence:
```
[["EURNZD_otc", 1781433175.294, 0.61749]]
```
Format: `[["SYMBOL", server_epoch_plus_7200, price]]`

These ticks are what the chart's SuperTrend line computes on in real time. The user sees the SuperTrend flip the instant the tick causes a band cross — they enter immediately. The bot's 1s bar close adds lag.

**Proof of concept:**  
Captured and validated during session 2026-06-14:
- 1,913 GBPUSD ticks over 14.9 min via browser WS hook
- Computed SuperTrend(10,3) on tick-by-tick flat series: 155 flips/14.9min (too noisy)
- Computed on 1s-flat (close-of-each-second): 64 flips/14.9min ✓ matches chart
- Proves the chart SuperTrend runs on ~1s aggregation, not raw ticks

**Key insight:** The optimal approach is NOT tick-by-tick SuperTrend (too noisy — flips every 2–5s in chop) but rather:  
> **Accumulate ticks into 1s bars in real time, evaluate SuperTrend the instant the bar closes** — same as the chart.  
> The FlipStreamer already does this via `subscribe_symbol_timed`, but raw ticks would let us close each 1s bar at the *exact* tick that crosses the second boundary rather than waiting for the library's callback.

---

## The Raw Tick Accumulator — Proposed Architecture

### Data source
The bot's WS connection already receives the same tick stream as the browser.  
The `SentimentCollector` uses `create_raw_handler()` + `send_raw_message()` to access raw frames.  
During the session, string frames matching `[["SYMBOL",epoch,price]]` are observed — these ARE the ticks.

### Implementation plan

**1. `broker/tick_stream.py` — TickAccumulator**
```
TickAccumulator:
  - attach(api): register raw WS handler alongside SentimentCollector
  - subscribe(pair): send changeSymbol (or equivalent) to get ticks for a pair
  - on_tick(frame): parse [["SYM", epoch, price]], dispatch to pair buffers
  - get_bar(pair, sec): returns completed 1s OHLC bar once second boundary passes
  - get_partial(pair): returns current-second incomplete bar (for early detection)
```

**2. Integration with FlipStreamer**  
Replace `api.create_timed_stream(pair, seconds)` with TickAccumulator:
- Each tick lands in the buffer for that pair
- When `epoch` crosses a second boundary (floor(epoch) > floor(prev_epoch)), emit the completed 1s bar
- Call `evaluate_flip(df)` immediately on bar close — no library callback delay

**3. Early-detection variant (future)**  
Once enough ticks accumulate mid-bar (e.g. 3+ ticks, 0.3s into the second):
- Run `evaluate_flip` on a partial bar (treating the last tick as the close)
- If the signal is strong AND the bar is > 0.5s in, place speculatively
- Risk: bar not closed yet, final close may flip back. Mitigated by MACD gap gate (needs momentum, not noise)

### Subscribe mechanism
The WS `changeSymbol` message triggers the server to start pushing ticks for a pair. Equivalent to what the chart does when you switch to a pair. The raw WS handler is already available. Need to:
1. Identify the exact message format for subscription (was working for the SentimentCollector's `subscribe_pair()`)
2. Confirm tick push continues as long as pair is subscribed (not just on `changeSymbol`)

### Concurrency
Same ≤4 pair cap as FlipStreamer (WS subscription limit). One TickAccumulator instance, multiple pair buffers.

---

## Expected improvement

| Method | Entry lag after flip | Notes |
|---|---|---|
| Poll (`history()`) | ~3–6s | misses most 1s flips entirely |
| FlipStreamer (current) | ~1–2s | waits for 1s bar close via library callback |
| Raw tick accumulator | ~0–500ms | emits on second boundary from raw tick |
| Partial-bar early detection | ~0ms (speculative) | risks false signal if bar reverses |

At 5s expiry, cutting lag from 3–6s to <1s recovers ~50–100% of the timing edge.

---

## Status
- FlipStreamer: **LIVE** as of 2026-06-14 19:16 on EURNZD, NZDUSD, AUDUSD, AUDNZD
- Raw tick accumulator: **NOT STARTED** — this document is the spec
- Prerequisites: confirm subscribe message format for raw tick stream (SentimentCollector groundwork already done)

## Risk notes
- Raw WS handler shares the bot's single WS session. Handler errors must not propagate to the trade loop (same fail-soft pattern as SentimentCollector)
- Tick ordering: server epoch is not guaranteed monotonic across symbols; buffer per-pair, sort by epoch
- Memory: cap tick buffer at last N seconds per pair (e.g. 120s rolling window)
