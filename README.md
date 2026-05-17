# ForexAI Bot — Automated Forex Trading System

A production-grade algorithmic trading bot for forex markets, built in Python with OANDA integration. Trades XAU/USD (gold) and EUR/USD on the 5-minute timeframe.

The project went through two complete iterations: an initial ML-based approach using LightGBM, followed by a rebuild around structural pattern recognition based on insights from live trading data.

---

## Highlights

- **Regime-aware execution** — adapts to trending vs ranging markets via ADX classification
- **Multi-timeframe trend alignment** — D1 + H1 + M5 confluence required for entries
- **3 deterministic setup patterns** — pullback continuation, breakout, mean reversion
- **Comprehensive risk management** — position sizing, drawdown halts, daily loss limits
- **7 trading discipline rules** — financing avoidance, weekend lockouts, news blackouts, consecutive loss cooldowns
- **Real-time alerting** — Telegram notifications for every trade, blocked entry, and rule activation
- **Production logging** — CSV trade logs, weekly summary generation, comprehensive error handling
- **OANDA integration** — live and demo account support via v20 API

---

## Architecture

```
ForexAI_Bot/
├── main.py              # Main trading loop, decision orchestration
├── strategy.py          # Structural pattern detection (3 setups)
├── features.py          # Technical indicators (18 features: ADX, RSI, MACD, BB, etc.)
├── rules.py             # 7 trading discipline rules
├── risk_manager.py      # Position sizing, drawdown tracking, order execution
├── news_filter.py       # Session checks, spread guard, volatility halts
├── data_feed.py         # OANDA API wrapper
├── alerts.py            # Telegram notifications
├── trade_logger.py      # CSV logging + weekly summary
├── logger.py            # Application logging
├── analyze_oanda_log.py # Post-hoc performance analyzer
├── model_training.py    # (Legacy) LightGBM training script
├── backtest.py          # Backtesting framework
├── config.json          # Configuration
└── requirements.txt
```

---

## How It Works

Every 60 seconds the bot evaluates each symbol through a decision pipeline:

1. **Fetch M5 candle data** from OANDA
2. **Compute features** — 18 technical indicators including ADX, RSI, Stochastic, Bollinger Bands, ATR
3. **News & spread filter** — block trading during high-impact events or abnormal spreads
4. **Detect market regime** — trending (ADX > 25), ranging (ADX < 20), or transition
5. **Get D1 + H1 trend bias** — cached for performance
6. **Find a setup** — one of three structural patterns
7. **Apply 7 rules** — financing window, weekend, daily limits, news blackout, etc.
8. **Risk checks** — drawdown, daily loss limit, position correlation
9. **Calculate position size** — based on structural stop distance
10. **Place order** with SL/TP at structurally significant levels

---

## The 3 Trading Setups

### 1. Pullback Continuation (highest priority)
Buy the dip in confirmed uptrends, sell the rally in confirmed downtrends.
- D1 and H1 trends must agree
- Price within 0.5% of EMA21
- Rejection candle with appropriate wick
- RSI cooled but not exhausted (35–55 for buys)
- SL: below recent swing low | TP: 2× risk

### 2. Breakout
Trade momentum out of consolidation.
- Close beyond 20-bar swing high/low
- Strong body candle (>60% of range)
- Volume 1.2× above 20-bar average
- Bollinger Band expansion (increasing volatility)
- D1 trend alignment required
- SL: at broken level | TP: 1.5× risk

### 3. Mean Reversion
Fade exhaustion at range extremes (ranging regime only).
- Price tags Bollinger Band extreme
- RSI confirms exhaustion (>70 or <30)
- Prior candle shows wick rejection
- SL: beyond rejection wick | TP: 1× risk

---

## The 7 Discipline Rules

| Rule | Purpose |
|------|---------|
| Pre-financing close | Flatten before 5 AM UTC daily financing |
| No weekend holds | Close all positions Friday before market close |
| Max consecutive losses | 2-hour cooldown after 3 losses on a symbol |
| Max daily trades | Hard cap of 15 trades per UTC day |
| News blackout | Block trading 15 min before/30 min after scheduled events |
| Partial profit taking | Close half at 50% to TP, move stop to breakeven |
| Session open skip | Skip first 30 min of London/NY opens (high spreads) |

---

## Risk Management

- 0.75% account risk per trade
- 3% daily loss limit (auto-halt)
- 10% drawdown halt (system-wide stop)
- Trailing stops on winning positions
- Spread guard (halts entries when spread > 2.5× ATR baseline)
- Multi-timeframe trend filter (prevents counter-trend entries)

---

## Setup

```bash
# Clone
git clone <your-repo-url>
cd ForexAI_Bot

# Install
pip install -r requirements.txt

# Configure (fill in API keys)
cp config.json.example config.json
# Edit: OANDA API_KEY, ACCOUNT_ID, ENVIRONMENT (practice or live)
# Optional: Telegram BOT_TOKEN, CHAT_IDS, Finnhub API_KEY

# Run
python main.py
```

For the legacy ML version:
```bash
python model_training.py   # train models on historical data
python main.py             # uses ML predictions
```

For the structural version:
```bash
python main.py             # uses strategy.py, no model needed
```

---

## Performance Analysis

The bot logs every trade to `trade_log.csv`. For post-hoc analysis using OANDA's transaction export:

```bash
# Export OANDA transaction history as CSV, save as oanda_export.csv
python analyze_oanda_log.py
```

Outputs: win rate, R:R ratio, edge calculation, per-symbol breakdown, daily P&L, top wins/losses.

---

## Project Journey & Lessons Learned

This project went through two complete iterations:

**v1 — ML-based (LightGBM)**
- 18 technical features fed to a gradient boosting classifier
- Time-weighted training on 5000 historical candles
- Regime-specific confidence thresholds
- **Result:** ~54% win rate, but at 0.65:1 R:R it remained mathematically unprofitable (~10% below break-even)

**Key insights from v1:**
- M5 ML achieves a hard ceiling around 50–57% accuracy regardless of feature engineering
- Spread cost on a small account eats 10–15% of every win
- Partial profit taking lowered avg win below avg loss
- Multi-timeframe filters dramatically reduced wrong-direction trades

**v2 — Structural patterns (current)**
- Removed the ML model entirely
- Replaced black-box predictions with three deterministic chart patterns
- Trades 5–15 times per week instead of 60–100
- Each entry has a clear, written justification
- Lower trade frequency → less spread cost bleed → better unit economics

---

## Technologies

- **Python 3.9+**
- **OANDA v20 API** (oandapyV20)
- **pandas / numpy** — data handling
- **ta** — technical indicators
- **LightGBM** (v1 only) — ML classifier
- **scikit-learn** — model evaluation
- **python-telegram-bot** — alerts
- **Finnhub API** — economic news

---

## Disclaimer

This is an educational project. Algorithmic forex trading carries substantial risk of loss. This code is provided as-is with no warranty. Do not run with real money you cannot afford to lose. Past performance does not guarantee future results.

---

## License

MIT
