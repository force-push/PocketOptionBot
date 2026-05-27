# PocketOption Trading Bot

Modular, production-grade trading bot for PocketOption with technical analysis, risk management, and browser automation via Chrome DevTools Protocol.

## ⚠️ Risk Disclaimer

**Binary options carry extreme risk of capital loss.** This bot is for **educational and research purposes only**.

- Always test in DEMO mode before any live use
- Never risk money you cannot afford to lose
- Past performance does not guarantee future results
- Verify regulatory compliance in your jurisdiction

## 🏗️ Architecture

```
pocketoption-bot/
├── broker/               # CDP connection, scraping, execution
│   ├── connector.py      # Playwright CDP manager
│   ├── scraper.py        # DOM data extraction
│   └── executor.py       # Trade placement (with demo guard)
├── data/                 # Price feed & candle management
│   └── feed.py           # OHLCV builder, tick aggregation
├── signals/              # Technical analysis
│   ├── base.py           # Abstract Signal class
│   ├── rsi.py            # RSI (oversold/overbought)
│   ├── macd.py           # MACD crossover
│   ├── bollinger.py      # Bollinger Bands mean reversion
│   ├── ema_cross.py      # EMA golden/death cross
│   ├── candle_pattern.py # Candlestick patterns
│   └── confluence.py     # Signal aggregator & scoring
├── strategy/             # Decision-making
│   ├── risk.py           # Risk manager (limits, cooldowns, guards)
│   └── manager.py        # Main trading loop
├── config/
│   └── settings.py       # Pydantic config from .env
├── utils/
│   ├── logger.py         # Loguru setup + trades.jsonl
│   └── dashboard.py      # Rich terminal UI
└── main.py               # Entry point
```

## 🚀 Quick Start

### 1. Launch Chrome with Remote Debugging

```bash
# macOS / Linux
google-chrome --remote-debugging-port=9222 &

# Or use existing instance:
# The bot will auto-connect to the first PocketOption tab
```

### 2. Setup Python Environment

```bash
cd ~/code/openclaw/projects/PocketOptionBot

# Install dependencies
pip3 install -r requirements.txt

# Or use Poetry:
poetry install
poetry shell
```

### 3. Configure

Copy `.env.example` to `.env` and adjust:

```bash
cp .env.example .env
```

**Critical settings:**

```env
CDP_URL=http://localhost:9222
TRADE_MODE=DEMO              # MUST be DEMO initially!
ASSET=EURUSD
TRADE_AMOUNT=1.0
DRY_RUN=true                 # Test without clicking buttons
MIN_CONFLUENCE_SCORE=0.75    # Require 3+ signals + score >= 0.75
```

### 4. Run the Bot

```bash
python3 main.py
```

**Output:**

```
2026-05-25 12:34:56 | INFO | main | Strategy Manager started
2026-05-25 12:35:02 | INFO | strategy.manager | Placing trade: CALL (score=0.82)
2026-05-25 12:35:03 | INFO | broker.executor | Trade executed: TradeResult(id='trade_1', status='PENDING')
```

Trades are logged to `data/trades.jsonl` for post-mortem analysis.

## 📊 Signals

### 1. **RSI** (Weight: 0.20)
- **CALL** if RSI < 30 (oversold)
- **PUT** if RSI > 70 (overbought)
- Confidence scales with distance from midpoint

### 2. **MACD** (Weight: 0.20)
- **CALL** on golden cross (MACD > Signal line)
- **PUT** on death cross (MACD < Signal line)
- Confidence boosted if histogram accelerating

### 3. **Bollinger Bands** (Weight: 0.20)
- **CALL** if price at lower band + reverting up
- **PUT** if price at upper band + reverting down
- Confidence: how far from bands

### 4. **EMA Cross** (Weight: 0.15)
- **CALL** on golden cross (fast EMA > slow EMA)
- **PUT** on death cross (fast EMA < slow EMA)
- Sustaining positions have lower confidence

### 5. **Candlestick Patterns** (Weight: 0.25)
- Bullish Engulfing → CALL
- Bearish Engulfing → PUT
- Hammer (long wick) → CALL
- Shooting Star → PUT
- Doji → Indecision

**Confluence Rule:** Trade only if ≥3 signals agree AND score ≥ `MIN_CONFLUENCE_SCORE`.

## 🛡️ Risk Management

**Hard Guards:**

1. **Max Trades/Hour**: Prevents over-trading
2. **Daily Loss Limit**: Halts if cumulative loss exceeds threshold
3. **Cooldown After Loss**: Blocks trades for N seconds after a loss
4. **Min Balance**: Requires balance ≥ 5× trade amount
5. **Demo Mode Guard**: Refuses to trade if page shows LIVE and `TRADE_MODE=DEMO`

**Trade Limits** (from `.env`):

```env
MAX_TRADES_PER_HOUR=10
MAX_DAILY_LOSS_USD=20.0
COOLDOWN_AFTER_LOSS_SECONDS=120
MIN_BALANCE_MULTIPLIER=5.0
```

## 🔍 Selector Discovery

If DOM selectors are outdated, run this in **DevTools Console** on the PocketOption page:

```javascript
// Test each selector
const selectors = {
  price: document.querySelector('[class*="price"]')?.textContent,
  timer: document.querySelector('[class*="timer"], [class*="countdown"]')?.textContent,
  balance: document.querySelector('[class*="balance"]')?.textContent,
  asset: document.querySelector('[class*="asset"], [class*="symbol"]')?.textContent,
};
console.log(JSON.stringify(selectors, null, 2));
```

If these fail, update `broker/scraper.py` > `SELECTORS` dict with working selectors. Selectors are centralized for easy updates.

## 📝 Logs & Data

- **Logs**: `logs/bot.log` (rolling, 7-day retention)
- **Trades**: `data/trades.jsonl` (one JSON per trade for easy analysis)

Example trade record:

```json
{
  "id": "trade_1",
  "direction": "CALL",
  "amount": 1.0,
  "expiry": 60,
  "timestamp": "2026-05-25T12:35:03.123456",
  "status": "PENDING"
}
```

## 🧪 Testing

### Dry Run (No Clicks)

```env
DRY_RUN=true
```

All trades are logged but buttons are never clicked. Perfect for debugging signal logic.

### Demo Mode (Safe)

```env
TRADE_MODE=DEMO
DRY_RUN=false
```

Trades are executed on the demo account. Safe for validation.

### Live Mode (Production)

```env
TRADE_MODE=LIVE
DRY_RUN=false
```

⚠️ **Only after extensive testing in DEMO.**

## 🐛 Troubleshooting

### Chrome won't connect

```bash
# Check if CDP is listening
curl http://localhost:9222/json/version

# If not, restart Chrome:
pkill -f "chrome.*remote-debugging"
google-chrome --remote-debugging-port=9222 &
```

### Selectors not working

1. Inspect the page: Open DevTools on PocketOption
2. Test selectors manually in Console
3. Update `SELECTORS` in `broker/scraper.py`

### Trades not being placed

Check logs for:
- `"Trade blocked by risk manager"` — Risk constraints active
- `"ERROR: TRADE_MODE=DEMO but page shows LIVE"` — Demo guard triggered
- `"Button not found"` — Selector issue

## 📚 References

- [Playwright Docs](https://playwright.dev/python/)
- [Pandas-ta Docs](https://github.com/twopirllc/pandas-ta)
- [PocketOption](https://pocketoption.com)

---

**Built with:** Python 3.11+ | Playwright | Pandas-ta | Pydantic | Loguru | Rich
