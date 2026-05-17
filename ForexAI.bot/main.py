"""
main.py — Structural Strategy Edition
--------------------------------------
NO MACHINE LEARNING. Pure structural pattern recognition.
 
HOW IT WORKS:
1. Every new M5 candle, check market regime (trending or ranging)
2. Get D1 and H1 trend bias
3. Look for one of 3 setups: pullback, breakout, mean reversion
4. If setup found, check all 7 rules + spread guard
5. If clean, place trade with structure-based SL/TP
 
HOW TO RUN:
  python main.py
 
NO model_training.py NEEDED. There is no model.
 
CTRL+C to stop. Trade summary prints automatically.
"""
 
import json
import time
import os
from datetime import datetime, timezone, date
 
from data_feed import get_candles
from features import compute_features, FEATURE_COLS
from news_filter import should_halt_trading
from strategy import find_setup
from rules import (
    check_all_rules_before_entry,
    should_close_before_financing,
    should_force_close_friday,
    record_trade_outcome,
)
from risk_manager import (
    get_account_balance,
    calculate_units,
    check_drawdown,
    get_open_trades,
    close_all_trades,
    place_order,
    manage_open_trade_stops
)
from alerts import Alerts
from logger import log_info, log_warning, log_error, log_trade
from trade_logger import log_trade_open, log_trade_close, log_rule_block, print_summary
 
# ─────────────────────────────────────────
with open("config.json") as f:
    config = json.load(f)
 
ACCOUNT_CFG  = config["oanda"]
RISK_CFG     = config["risk"]
TRADE_CFG    = config["trading"]
RULES_CFG    = TRADE_CFG.get("rules", {})
FINNHUB_CFG  = config["finnhub"]
TELEGRAM_CFG = config["telegram"]
 
SYMBOLS       = TRADE_CFG["symbols"]
TIMEFRAME     = TRADE_CFG["timeframe"]
LOOKBACK      = TRADE_CFG["lookback_candles"]
SLEEP_SECONDS = TRADE_CFG["sleep_seconds"]
 
MAX_RISK_PCT       = RISK_CFG["max_trade_risk_pct"]
MAX_DRAWDOWN_PCT   = RISK_CFG["max_drawdown_pct"]
MAX_DAILY_LOSS_PCT = RISK_CFG.get("max_daily_loss_pct", 0.03)
STARTING_BALANCE   = RISK_CFG["starting_balance"]
 
TRADE_COOLDOWN_SECONDS = TRADE_CFG.get("trade_cooldown_seconds", 300)
 
REGIME_CFG = TRADE_CFG.get("regime", {})
ADX_TRENDING = REGIME_CFG.get("adx_trending_threshold", 25)
ADX_RANGING  = REGIME_CFG.get("adx_ranging_threshold", 20)
 
alerts = Alerts(TELEGRAM_CFG)
 
_, initial_equity = get_account_balance(ACCOUNT_CFG)
equity_peak = initial_equity if initial_equity else STARTING_BALANCE
 
daily_start_equity = initial_equity if initial_equity else STARTING_BALANCE
daily_loss_halt    = False
last_reset_date    = date.today()
 
loss_streak_state = {sym: {"count": 0, "halt_until": None} for sym in SYMBOLS}
daily_trade_count = 0
 
log_info("=" * 55)
log_info("ForexAI Bot — STRUCTURAL STRATEGY (no ML)")
log_info(f"Symbols:         {SYMBOLS}")
log_info(f"Timeframe:       {TIMEFRAME}")
log_info(f"Starting equity: ${equity_peak:,.2f}")
log_info("=" * 55)
alerts.startup_alert(SYMBOLS)
 
 
def check_daily_reset(current_equity):
    global daily_start_equity, daily_loss_halt, last_reset_date, daily_trade_count
    today = date.today()
    if today != last_reset_date:
        log_info(f"New day — resetting. Start equity: ${current_equity:,.2f}")
        daily_start_equity = current_equity
        daily_loss_halt    = False
        daily_trade_count  = 0
        last_reset_date    = today
        alerts.notify(f"🌅 New trading day\n💰 Start: ${current_equity:,.2f}")
 
 
def check_daily_loss(current_equity):
    global daily_loss_halt
    if daily_loss_halt: return True
    if daily_start_equity <= 0: return False
    daily_loss = (daily_start_equity - current_equity) / daily_start_equity
    if daily_loss >= MAX_DAILY_LOSS_PCT:
        log_warning(f"Daily loss limit hit: {daily_loss:.2%}")
        daily_loss_halt = True
        alerts.notify(f"🚨 Daily loss limit\nLost: {daily_loss:.2%}\nStart ${daily_start_equity:,.2f} → Now ${current_equity:,.2f}")
        return True
    return False
 
 
# Trend caches
h1_cache = {sym: None for sym in SYMBOLS}
h1_cache_hour = {sym: -1 for sym in SYMBOLS}
daily_cache = {sym: None for sym in SYMBOLS}
daily_cache_day = {sym: None for sym in SYMBOLS}
 
 
def get_h1_trend(symbol):
    current_hour = datetime.now(timezone.utc).hour
    if h1_cache_hour[symbol] == current_hour and h1_cache[symbol] is not None:
        return h1_cache[symbol]
    df_h1 = get_candles(ACCOUNT_CFG, symbol, timeframe="H1", count=60)
    if df_h1 is None or len(df_h1) < 52:
        return "neutral"
    ema20 = df_h1["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = df_h1["Close"].ewm(span=50, adjust=False).mean().iloc[-1]
    price = df_h1["Close"].iloc[-1]
    if ema20 > ema50 and price > ema50: trend = "bullish"
    elif ema20 < ema50 and price < ema50: trend = "bearish"
    else: trend = "neutral"
    h1_cache[symbol] = trend
    h1_cache_hour[symbol] = current_hour
    log_info(f"H1 [{symbol}]: {trend.upper()}")
    return trend
 
 
def get_daily_trend(symbol):
    today = datetime.now(timezone.utc).date()
    if daily_cache_day[symbol] == today and daily_cache[symbol] is not None:
        return daily_cache[symbol]
    df_d = get_candles(ACCOUNT_CFG, symbol, timeframe="D", count=60)
    if df_d is None or len(df_d) < 52:
        return "neutral"
    ema20 = df_d["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = df_d["Close"].ewm(span=50, adjust=False).mean().iloc[-1]
    price = df_d["Close"].iloc[-1]
    if ema20 > ema50 and price > ema50: trend = "bullish"
    elif ema20 < ema50 and price < ema50: trend = "bearish"
    else: trend = "neutral"
    daily_cache[symbol] = trend
    daily_cache_day[symbol] = today
    log_info(f"D1 [{symbol}]: {trend.upper()}")
    return trend
 
 
def detect_regime(df):
    adx = df["adx"].iloc[-1]
    if adx >= ADX_TRENDING: return "trending", adx
    elif adx <= ADX_RANGING: return "ranging", adx
    else: return "transition", adx
 
 
last_trade_close_time = {sym: 0.0 for sym in SYMBOLS}
 
 
def run_symbol(symbol):
    """One full decision cycle for a symbol — STRUCTURAL VERSION."""
    global daily_trade_count, equity_peak
 
    log_info(f"--- {symbol} ---")
 
    # 1. Fetch candles
    df = get_candles(ACCOUNT_CFG, symbol, timeframe=TIMEFRAME, count=LOOKBACK)
    if df is None or len(df) < 60:
        return
 
    # 2. Compute features (we still need ATR, ADX, RSI, BB etc — just no ML)
    df = compute_features(df)
    if len(df) < 30:
        return
 
    # 3. News/session/spread filter
    halt, reason = should_halt_trading(df, FINNHUB_CFG, TRADE_CFG.get("sessions"), symbol=symbol)
    if halt:
        log_info(f"Halt [{symbol}]: {reason}")
        return
 
    # 4. Regime, daily, H1
    regime, adx_val = detect_regime(df)
    daily_trend = get_daily_trend(symbol)
    h1_trend    = get_h1_trend(symbol)
    log_info(f"[{symbol}] Regime={regime} ADX={adx_val:.1f} D1={daily_trend} H1={h1_trend}")
 
    # 5. Find a setup (NEW — replaces ML signal)
    setup = find_setup(df, regime, daily_trend, h1_trend)
    if setup is None:
        log_info(f"[{symbol}] No setup found this candle.")
        return
 
    # 6. 7-rules gate
    state = {"loss_streak_state": loss_streak_state, "daily_trade_count": daily_trade_count}
    blocked, block_reason = check_all_rules_before_entry(symbol, RULES_CFG, state)
    if blocked:
        log_info(f"Rule block [{symbol}]: {block_reason}")
        log_rule_block(symbol, block_reason, regime=regime, confidence=0)
        return
 
    # 7. Account checks
    _, equity = get_account_balance(ACCOUNT_CFG)
    if equity is None: return
    if equity > equity_peak: equity_peak = equity
    if check_drawdown(equity, equity_peak, MAX_DRAWDOWN_PCT):
        alerts.drawdown_alert((equity_peak - equity) / equity_peak)
        return
    if check_daily_loss(equity): return
 
    # 8. Cooldown
    seconds_since = time.time() - last_trade_close_time[symbol]
    if 0 < last_trade_close_time[symbol] and seconds_since < TRADE_COOLDOWN_SECONDS:
        log_info(f"Cooldown [{symbol}]: {int(TRADE_COOLDOWN_SECONDS - seconds_since)}s")
        return
 
    # 9. Position size based on structural risk
    # Setup gives us risk_price (distance from entry to SL)
    # We size so loss = MAX_RISK_PCT of equity
    is_forex = (symbol != "XAU_USD")
    risk_price = setup["risk_price"]
    entry = setup["entry"]
 
    # Risk in account currency:
    # For XAU: 1 unit = 1 ounce, price moves 1 = $1 per unit
    # For EUR: 3000 units, pip = 0.0001, $0.30 per pip
    # We use the existing calculate_units which handles this
    # but pass the structural sl_dist instead of ATR*multiplier
    # Hack: compute equivalent SL multiplier
    # risk_price = atr * sl_mult → sl_mult = risk_price / atr
    atr = df["atr"].iloc[-1]
    sl_mult = risk_price / atr if atr > 0 else 2.0
 
    units = calculate_units(
        equity, atr, MAX_RISK_PCT, entry,
        is_forex=is_forex,
        sl_multiplier=sl_mult,
        sgd_to_usd=RISK_CFG.get("sgd_to_usd_rate", 0.74),
        account_currency=RISK_CFG.get("account_currency", "SGD"),
        simulated_capital_usd=RISK_CFG.get("simulated_capital_usd", None)
    )
    if units <= 0:
        log_warning(f"[{symbol}] Calculated 0 units. Skip.")
        return
 
    # 10. Handle reversed positions
    open_trades = get_open_trades(ACCOUNT_CFG, symbol)
    if open_trades:
        existing_side = "buy" if float(open_trades[0]["currentUnits"]) > 0 else "sell"
        new_side = setup["side"].lower()
        if existing_side == new_side:
            log_info(f"[{symbol}] Already in {existing_side.upper()}, hold")
            return
        else:
            log_info(f"[{symbol}] Reversal — closing {existing_side}")
            close_all_trades(ACCOUNT_CFG, symbol)
            last_trade_close_time[symbol] = time.time()
            return
 
    # 11. Place order — calculate tp_mult for compatibility with place_order
    tp_dist = abs(setup["tp"] - setup["entry"])
    tp_mult = tp_dist / atr if atr > 0 else 2.0
 
    side = setup["side"].lower()
    success = place_order(
        account_cfg=ACCOUNT_CFG,
        symbol=symbol,
        units=units,
        side=side,
        atr=atr,
        current_price=entry,
        trail_multiplier=RISK_CFG["trailing_atr_multiplier"],
        sl_multiplier=sl_mult,
        tp_multiplier=tp_mult,
    )
 
    if success:
        daily_trade_count += 1
        max_per_day = RULES_CFG.get("max_daily_trades", {}).get("max_trades", 15)
        log_trade(side.upper(), symbol, units, entry,
                  f"Setup={setup['setup']} Regime={regime} D1={daily_trend} H1={h1_trend} "
                  f"Trade#{daily_trade_count}/{max_per_day}")
 
        log_trade_open(symbol=symbol, side=side, units=units,
                       entry_price=entry, regime=regime,
                       h1_trend=h1_trend, confidence=1.0)
 
        alerts.trade_entry_alert(side.upper(), symbol, units, entry,
                                 setup["sl"], setup["tp"], 1.0)
        alerts.notify(
            f"📊 *{setup['setup']} setup*\n"
            f"Symbol: `{symbol}` | Side: `{side.upper()}`\n"
            f"Regime: `{regime}` | D1: `{daily_trend}` | H1: `{h1_trend}`\n"
            f"Reason: {setup['reason']}"
        )
 
 
# ─────────────────────────────────────────
# Candle tracker
# ─────────────────────────────────────────
last_candle_time = {sym: None for sym in SYMBOLS}
 
 
def is_new_candle(symbol, df):
    global last_candle_time
    latest = df.index[-1]
    if last_candle_time[symbol] is None or latest > last_candle_time[symbol]:
        last_candle_time[symbol] = latest
        return True
    return False
 
 
# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────
while True:
    try:
        now = datetime.now(timezone.utc)
        log_info(f"\n{'='*55}")
        log_info(f"Cycle: {now.strftime('%Y-%m-%d %H:%M UTC')}")
 
        _, cycle_equity = get_account_balance(ACCOUNT_CFG)
        if cycle_equity:
            check_daily_reset(cycle_equity)
            if daily_loss_halt:
                time.sleep(SLEEP_SECONDS)
                continue
 
        # Forced close windows
        if should_close_before_financing(RULES_CFG):
            for sym in SYMBOLS:
                if get_open_trades(ACCOUNT_CFG, sym):
                    log_warning(f"Pre-financing close [{sym}]")
                    close_all_trades(ACCOUNT_CFG, sym)
                    last_trade_close_time[sym] = time.time()
                    alerts.notify(f"🌙 Pre-financing close `{sym}`")
 
        if should_force_close_friday(RULES_CFG):
            for sym in SYMBOLS:
                if get_open_trades(ACCOUNT_CFG, sym):
                    log_warning(f"Friday close [{sym}]")
                    close_all_trades(ACCOUNT_CFG, sym)
                    last_trade_close_time[sym] = time.time()
                    alerts.notify(f"📅 Friday close `{sym}` flat for weekend")
 
        for symbol in SYMBOLS:
            df_check = get_candles(ACCOUNT_CFG, symbol, timeframe=TIMEFRAME, count=LOOKBACK)
            if df_check is None or len(df_check) < 50: continue
            df_check = compute_features(df_check)
            if len(df_check) < 2: continue
            if not is_new_candle(symbol, df_check):
                log_info(f"[{symbol}] no new candle")
                continue
 
            log_info(f"[{symbol}] NEW CANDLE {df_check.index[-1]}")
 
            pre_trades = get_open_trades(ACCOUNT_CFG, symbol)
            pre_trade_ids = {t["id"]: float(t.get("unrealizedPL", 0)) for t in pre_trades}
            had_open = bool(pre_trades)
 
            manage_open_trade_stops(ACCOUNT_CFG, symbol, alerts, rules_cfg=RULES_CFG)
 
            post_trades = get_open_trades(ACCOUNT_CFG, symbol)
            post_trade_ids = {t["id"] for t in post_trades}
            now_open = bool(post_trades)
 
            for tid, last_pnl in pre_trade_ids.items():
                if tid not in post_trade_ids:
                    record_trade_outcome(symbol, last_pnl, RULES_CFG, loss_streak_state)
                    log_trade_close(symbol, exit_price=0, pnl_sgd=last_pnl)
 
            if had_open and not now_open:
                last_trade_close_time[symbol] = time.time()
 
            run_symbol(symbol)
 
        log_info(f"Sleeping {SLEEP_SECONDS}s")
        time.sleep(SLEEP_SECONDS)
 
    except KeyboardInterrupt:
        log_info("Bot stopped.")
        print("\nGenerating trade summary...")
        print_summary(days=7)
        break
    except Exception as e:
        log_error(f"Loop error: {e}")
        alerts.error_alert(str(e))
        time.sleep(60)