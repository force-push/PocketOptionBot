# PocketOptionBot — Quick Start Guide

## 🎯 5-Minute Setup

### Step 1: Launch Chrome with Remote Debugging

```bash
# Kill any existing Chrome instances
pkill -f "chrome.*remote-debugging" || true

# Start Chrome with debugging enabled
google-chrome --remote-debugging-port=9222 &

# Verify it's listening
curl http://localhost:9222/json/version
```

You should see JSON output. If not, Chrome didn't start properly.

### Step 2: Install Python Dependencies

```bash
cd ~/code/openclaw/projects/PocketOptionBot

# Install from requirements.txt
pip3 install -r requirements.txt

# Or use Poetry
poetry install
poetry shell
```

### Step 3: Verify Selectors Work

**Open PocketOption in Chrome** (in the Chrome instance with debugging enabled).

Then run:

```bash
python3 verify_selectors.py
```

Expected output:
```
[3] Testing selectors...
─────────────────────────────────────
✓ price           = 1.06325
✓ timer           = 45
✓ balance         = $1000.00
✓ asset           = EURUSD
✓ last_result     = None
✓ is_demo         = True
─────────────────────────────────────
✓ All selectors working!
```

If any fail, selectors need updating. Let me know.

### Step 4: Run in Dry-Run Mode (Test)

This runs the bot but **never clicks buttons** — just logs what it would trade.

```bash
python3 main.py
```

Watch the logs. You should see:
- Price ticks and candles building
- Signals being evaluated
- Trades being simulated

**Let this run for 5-10 minutes** to verify signals are working.

### Step 5: Review Logs

```bash
# View live logs
tail -f logs/bot.log

# View all trades (JSON)
cat data/trades.jsonl | python3 -m json.tool | head -50
```

---

## 🔧 Tuning the Bot

All settings are in `.env`. Don't edit `main.py` or signal code.

### Conservative Settings (Low Risk)

```env
MIN_CONFLUENCE_SCORE=0.80        # Require higher signal agreement
MAX_TRADES_PER_HOUR=5            # Fewer trades
MAX_DAILY_LOSS_USD=10.0          # Tighter loss limit
TRADE_AMOUNT=0.5                 # Smaller size
COOLDOWN_AFTER_LOSS_SECONDS=300  # Longer cooldown
```

### Aggressive Settings (Higher Risk)

```env
MIN_CONFLUENCE_SCORE=0.60
MAX_TRADES_PER_HOUR=20
MAX_DAILY_LOSS_USD=50.0
TRADE_AMOUNT=5.0
COOLDOWN_AFTER_LOSS_SECONDS=60
```

### Signal Weights (in `signals/confluence.py`)

Each signal contributes a weighted vote. Currently:
- RSI: 20%
- MACD: 20%
- Bollinger: 20%
- EMA: 15%
- Patterns: 25%

To adjust, edit `ConfluenceEngine` in `signals/confluence.py` or contact me.

---

## ✅ Safe Progression Path

### Phase 1: Dry Run (Days 1-3)
```env
TRADE_MODE=DEMO
DRY_RUN=true
```
✓ Signals validate correctly  
✓ No real clicks, 100% safe  
✓ Review P&L logs  

### Phase 2: Demo Mode (Days 3-7)
```env
TRADE_MODE=DEMO
DRY_RUN=false
```
✓ Real clicks on demo account  
✓ See actual trade outcomes  
✓ Refine parameters  

### Phase 3: Live (After 1+ week of consistent demo profit)
```env
TRADE_MODE=LIVE
DRY_RUN=false
```
⚠️ **Only after Phase 2 proves profitable**  
⚠️ Start with 1/10th of your max size  
⚠️ Monitor closely  

---

## 🐛 Troubleshooting

### "Failed to connect"
```
✗ Connection failed: ...
   Start Chrome with: google-chrome --remote-debugging-port=9222
```
→ Chrome isn't listening. Restart it:
```bash
pkill -f "chrome.*remote-debugging"
google-chrome --remote-debugging-port=9222 &
sleep 2
curl http://localhost:9222/json/version
```

### "No active PocketOption page"
→ PocketOption tab must be open in the Chrome instance with debugging enabled.

### "Trade blocked by risk manager"
→ Check the reason in logs. Common ones:
- `Balance too low` — Need more demo/live funds
- `Max trades/hour` — You've hit your limit
- `Cooling down` — After a loss, waiting before next trade

### Selectors returning None
→ DOM changed. Run `verify_selectors.py` to confirm, then update selectors:

```bash
python3 verify_selectors.py
# If any fail, update SELECTORS in broker/scraper.py
```

---

## 📊 Monitoring

### Live Dashboard (Optional)

```python
# In main.py, uncomment dashboard code to see live stats
dashboard.update(...)
```

### Logs Directory

```
logs/
├── bot.log           # All events, rotates daily
└── (older)           # 7-day retention

data/
└── trades.jsonl      # All trades, one per line
```

### Parse Trades

```bash
# Count trades by direction
python3 << 'EOF'
import json
calls = 0
puts = 0
with open('data/trades.jsonl') as f:
    for line in f:
        trade = json.loads(line)
        if trade['direction'] == 'CALL':
            calls += 1
        else:
            puts += 1
print(f"CALL: {calls}, PUT: {puts}")
EOF
```

---

## 🛑 Emergency Stop

**Ctrl+C** stops the bot gracefully.

To force-kill all Chrome instances:
```bash
pkill -9 -f chrome
```

---

## 📞 Next Steps

Once you've verified Phase 1 (dry run working):

1. **Share 10 trades from `data/trades.jsonl`** — I can analyze signal quality
2. **Run Phase 2 (demo mode)** for 1 week — See real outcomes
3. **Tune parameters** based on results
4. **Only then** consider live trading

Good luck! 🚀

---

**Remember:**
- Binary options = extreme risk
- This bot is educational
- Never risk money you can't lose
- Past performance ≠ future results
