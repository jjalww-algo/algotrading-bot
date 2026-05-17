# ForexAI Bot — Setup & Usage Guide

A fully automated Python AI trading bot using LightGBM, Oanda API, and news filtering.
Configured for paper trading on EUR/USD and XAU/USD (gold).

---

## Folder Structure

```
ForexAI_Bot/
├── main.py              # Live trading loop (run this to start the bot)
├── model_training.py    # Train LightGBM models (run once before main.py)
├── backtest.py          # Test strategy on historical data
├── features.py          # Technical indicators
├── data_feed.py         # Pulls candle data from Oanda
├── news_filter.py       # Volatility + news halt logic
├── risk_manager.py      # Position sizing, drawdown, order execution
├── alerts.py            # Telegram notifications (optional)
├── logger.py            # Logging to file + terminal
├── config.json          # YOUR API KEYS AND SETTINGS
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

---

## Step 1 — Install Python

Download Python 3.10 or later from: https://www.python.org/downloads/
During install, check "Add Python to PATH"

---

## Step 2 — Install Dependencies

Open a terminal (Command Prompt or PowerShell on Windows), navigate to the ForexAI_Bot folder, then run:

```
pip install -r requirements.txt
```

---

## Step 3 — Fill in Your API Keys

Open config.json and replace:

```json
"API_KEY": "YOUR_NEW_API_KEY_HERE"
```

With your actual Oanda demo API key (generate a new one after revoking the old one).

Your Account ID is already pre-filled: 101-003-38613871-001

---

## Step 4 — Train the Models (First Time Only)

```
python model_training.py
```

This will:
- Download 5000 candles of historical data for each symbol from Oanda
- Train a LightGBM model with walk-forward cross-validation
- Save models to the /models folder

Re-run this weekly or monthly to keep the model updated.

---

## Step 5 — (Optional) Run Backtest

```
python backtest.py
```

This shows you estimated win rate, total return, and max drawdown before going live.

---

## Step 6 — Start the Bot

```
python main.py
```

The bot will:
- Check signals every 5 minutes
- Only trade during London + New York sessions (08:00–22:00 UTC)
- Halt on volatility spikes, wick anomalies, volume spikes
- Risk max 2% per trade
- Halt all trading if drawdown reaches 6%
- Log everything to /logs folder

Press CTRL+C to stop.

---

## Optional: Enable Telegram Alerts

1. Open Telegram and search for @BotFather
2. Send /newbot and follow the steps to get a BOT_TOKEN
3. Message your bot once, then visit:
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   to find your CHAT_ID
4. In config.json, set:
   - "BOT_TOKEN": your token
   - "CHAT_ID": your chat id
   - "enabled": true

---

## Optional: Enable Finnhub Live News

1. Sign up free at https://finnhub.io
2. Copy your API key
3. In config.json, set:
   - "API_KEY": your finnhub key
   - "enabled": true

---

## Risk Settings (config.json)

| Setting | Default | Description |
|--------|---------|-------------|
| max_trade_risk_pct | 0.02 | Max 2% of equity risked per trade |
| max_drawdown_pct | 0.06 | Bot halts at 6% drawdown |
| trailing_atr_multiplier | 2.0 | Stop loss distance in ATR units |
| score_threshold | 0.55 | Minimum ML confidence to take a trade |

---

## Important Notes

- This bot is for PAPER TRADING / demo accounts only until you are satisfied it works
- No bot guarantees profit — always monitor it
- Past backtest results do not guarantee future performance
- Never risk money you cannot afford to lose
