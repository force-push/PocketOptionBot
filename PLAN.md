# PLAN — Telegram-sourced, win-rate-filtered PocketOption bot

**Status: ✅ IMPLEMENTED** (all 13 tasks complete as of 2026-06-05)  
See `PROJECT_STATUS.md` for a full summary of what was built.  
See `docs/superpowers/plans/2026-06-04-telebot-evolution.md` for the original detailed plan.

---

## Architecture (as implemented)

```
po_broker_bot (Telegram)
        │  Telethon user session (MTProto)
        │
        ▼  telegram_feed/navigator.py
  Navigator drives bot menus
        │  → Start Autotrade → top pair (win rate) → pair screen (direction)
        │  → handles "Trade Anyway" nag automatically
        │
        ▼  telegram_feed/prediction_parser.py + pair_norm.py
  PredictionScreen → top PairPrediction (pair_raw, win_rate, is_top)
        │  Gate: win_rate ≥ PAIR_SELECT_MIN_WIN_RATE
        │
        ▼  telegram_feed/direction_parser.py
  DirectionScreen → direction ("CALL"/"PUT"), setup, indicators_raw
        │
        ▼  broker/po_api.py → data/candles.py → signals/confluence.py
  5-signal TA engine (RSI, MACD, Bollinger, EMA Cross, Candle Patterns)
        │  ≥3 signals same direction + score ≥ MIN_CONFLUENCE_SCORE
        │
        ▼  strategy/decision.py
  Decision(trade, combined_probability, skip_reason)
        │  combined_probability = (bot_win_rate + confluence_score) / 2
        │
        ▼  strategy/trade_logger.py
  Write DecisionRow to data/decisions.jsonl
        │
        ├─ SKIP: log + back_to_menu
        │
        └─ TRADE:
              │  strategy/risk.py: is_allowed(balance)?
              │
              ▼  broker/po_api.py
          buy/sell(pair, stake, expiry)   ← SSID demo guard + DRY_RUN gate
              │
              ▼  navigator.back_to_menu (don't block UI)
              │
              ▼  await check_win(trade_id)
              │
              ▼  strategy/trade_logger.py: backfill_outcome()
              │
              ▼  strategy/win_rate.py + strategy/risk.py
          WinRateTracker.record() + RiskManager.record_trade()
```

---

## Completed implementation tasks

1. `telegram_feed/prediction_parser.py` — `PredictionScreen`, `PairPrediction`
2. `telegram_feed/direction_parser.py` — `DirectionScreen`
3. `telegram_feed/pair_norm.py` — `normalize_pair()`
4. `strategy/expiry.py` — `select_expiry()`
5. `strategy/decision.py` — `Decision`, `decide()`
6. `strategy/trade_logger.py` — `DecisionRow`, `write_decision()`, `backfill_outcome()`
7. `config/settings.py` — v2 fields: stake, expiry, win gate, nag toggle, decisions log path
8. `telegram_feed/navigator.py` — `Navigator` class
9. `strategy/manager_v2.py` — `StrategyManagerV2.run_once()`
10. `main_v2.py` — entrypoint, `--cycles N` arg
11. `tools/v2_smoke.py` — one dry-run cycle against live bot
12. `broker/po_api.py` — upgraded demo guard with API-native `is_demo()`
13. `strategy/signal_gate.py` — log format fix; full suite 100 tests green

---

## Next: planned v2.1+ work

### Dashboard (UI)
Web interface over `data/decisions.jsonl`:
- Cycle history table (pair, direction, agreement, probability, outcome, P&L)
- Per-pair performance chart (win rate, cumulative P&L)
- Signal breakdown per cycle
- Real-time tail of the log

### Dynamic stakes
- Kelly-derived stake based on `combined_probability`
- Cap at configured `STAKE_AMOUNT` maximum

### Blocked-pair list
- Carry forward `telebot/config/pair_learnings.json` blocked pairs
- Auto-block new pairs if rolling P&L goes negative

### Multi-pair evaluation
- Score all pairs in the prediction screen, not just the top pick
- Select highest combined_probability across all qualifying pairs

---

## Unchanged from v0.1 (kept but unwired)

- `broker/connector.py`, `broker/scraper.py`, `broker/executor.py` — legacy CDP modules
- `data/feed.py` — legacy price feed
- `strategy/manager.py` — legacy event-driven manager
- `strategy/signal_gate.py` — legacy 3-gate filter
- `telegram_feed/client.py`, `telegram_feed/parser.py` — legacy Telegram listener + parser
- `main.py` — legacy entrypoint

These are candidates for removal once v2 proves stable.
