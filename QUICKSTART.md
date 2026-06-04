# PocketOptionBot v2 — Quick Start

## Prerequisites

Before your first run you need three things:

1. **Telethon session** — run `python3 tools/gen_telegram_session.py` once if not already done. The session file lives at `~/.telebot/telegram.session` (or wherever `TELEGRAM_SESSION` points).
2. **PocketOption SSID** — log in to pocketoption.com in Chrome, open DevTools → Network, filter for WS, find the `42["auth",{...}]` message and copy the full string.
3. **`.env` configured** — `cp .env.example .env` and fill in your credentials.

> ⚠️ Only one process may use the Telethon session at a time. **Stop any running `pocket_robot_trader.py` (Telebot) before starting PocketOptionBot v2.**

---

## Setup (one-time)

```bash
cd ~/code/openclaw/projects/PocketOptionBot

# Install dependencies
pip3 install -r requirements.txt

# Copy and fill in config
cp .env.example .env
# Edit .env: set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION, PO_SSID
```

**Minimum `.env` for testing:**

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=abc123def456
TELEGRAM_SESSION=~/.telebot/telegram.session

PO_SSID=42["auth",{"session":"your_session","isDemo":1,"uid":123456}]

# Safety defaults — do not change until you understand the implications
TRADE_MODE=DEMO
DRY_RUN=true
STAKE_AMOUNT=1.50
PAIR_SELECT_MIN_WIN_RATE=0.0   # 0.0 disables the gate; set 0.82 for real runs
```

---

## Step 1: Smoke test

Verifies the full pipeline without placing any trade.

```bash
python3 tools/v2_smoke.py
```

Expected: one cycle completes, you see a `TRADE` or `SKIP` decision in `data/decisions.jsonl`.

```bash
# Check the log
tail -1 data/decisions.jsonl | python3 -m json.tool
```

If you see a `decision` field set to `"TRADE"` or `"SKIP"` with a valid `pair_api`, the pipeline is working.

---

## Step 2: Capture mode (all signals, no gate, no trades)

Run a few cycles with gates off and DRY_RUN on to see what the bot produces:

```bash
# .env: PAIR_SELECT_MIN_WIN_RATE=0.0, DRY_RUN=true
python3 main_v2.py --cycles 5
```

Review the decisions log:

```bash
cat data/decisions.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line)
    print(f\"{r['ts'][:19]}  {r['pair_api']:12}  bot={r['bot_direction']}  our={r['our_direction']}  agree={r['agreement']}  dec={r['decision']}  prob={r.get('combined_probability',0):.2f}\")
"
```

---

## Step 3: Gated testing (with win-rate gate, still DRY_RUN)

Enable the 82% pair gate:

```env
PAIR_SELECT_MIN_WIN_RATE=0.82
DRY_RUN=true
```

```bash
python3 main_v2.py
```

Now the bot only evaluates pairs where `po_broker_bot` has stated ≥ 82% win rate. Signals that don't pass the confluence check will be logged as `SKIP`.

---

## Step 4: Demo live trading

Once you're happy with the signal quality from the log:

```env
TRADE_MODE=DEMO
DRY_RUN=false
PAIR_SELECT_MIN_WIN_RATE=0.82
```

```bash
python3 main_v2.py
```

Real trades on your PocketOption **demo** account. No real money. Outcomes are tracked and backfilled into `data/decisions.jsonl`.

Watch outcomes live:

```bash
tail -f logs/bot.log
```

---

## Step 5: Analyse results

After running for a day or more:

```bash
# Win rate by pair
python3 -c "
import json, collections
rows = [json.loads(l) for l in open('data/decisions.jsonl')]
trades = [r for r in rows if r['decision'] == 'TRADE' and r.get('outcome')]
by_pair = collections.defaultdict(lambda: {'wins':0,'total':0,'pnl':0.0})
for r in trades:
    p = by_pair[r['pair_api']]
    p['total'] += 1
    p['wins'] += 1 if r['outcome'].upper() == 'WIN' else 0
    p['pnl'] += r.get('pnl', 0) or 0
for pair, s in sorted(by_pair.items()):
    wr = s['wins']/s['total'] if s['total'] else 0
    print(f\"{pair:14}  {s['total']:3} trades  win={wr:.0%}  pnl={s['pnl']:+.2f}\")
"
```

---

## Common Issues

### "Session locked" / Telethon error on startup
→ Another process is using the Telegram session. Stop it first:
```bash
pkill -f pocket_robot_trader
```

### Bot predicts but direction screen never shows
→ The pair selection step may have failed silently. Run with a single cycle and check logs:
```bash
python3 main_v2.py --cycles 1
tail -20 logs/bot.log
```

### All signals are SKIP with `ta_disagree`
→ The bot direction and our TA direction are consistently disagreeing. This is expected if TA indicators don't have enough data or the market is volatile. Let it run — it will agree when confluence is strong.

### `ABORT: TRADE_MODE=DEMO but SSID has isDemo=0`
→ Your SSID was copied from a live account session. Log in to your **demo** account on PocketOption, copy the SSID again, and update `.env`.

### Nag screen keeps blocking
→ `CLICK_TRADE_ANYWAY=true` (the default) handles this. If it persists, check logs for `FloodWaitError` — the bot may be clicking too quickly and Telegram is rate-limiting it.

---

## Emergency Stop

- **Graceful:** `Ctrl+C` — completes the current cycle then exits
- **Immediate:** `kill <pid>` — stops mid-cycle (any open trade continues until expiry via API)

---

## Files to Monitor

| File | What to watch for |
|---|---|
| `logs/bot.log` | Live events, errors, decision reasons |
| `data/decisions.jsonl` | Full structured log of every cycle |
| `data/win_rates.json` | Per-pair win rate accumulation |

---

**Next:** once demo P&L is consistently positive over a week, consider setting `TRADE_MODE=LIVE`. Start with the minimum stake and monitor closely.
