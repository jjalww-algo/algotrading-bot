"""
risk_manager.py
---------------
Handles all risk logic:
- Position sizing (max 2% risk per trade)
- Drawdown tracking (halt at 6%)
- Trailing stop management
"""
 
from logger import log_info, log_warning, log_error
from oandapyV20 import API
from oandapyV20.endpoints.accounts import AccountDetails
from oandapyV20.endpoints.orders import OrderCreate
from oandapyV20.endpoints.trades import TradesList, TradeClose
from oandapyV20.endpoints.positions import PositionClose
import oandapyV20.endpoints.orders as orders
import json
 
 
def get_account_balance(account_cfg):
    """Fetch current account balance and equity from Oanda."""
    try:
        client = API(
            access_token=account_cfg["API_KEY"],
            environment=account_cfg["ENVIRONMENT"]
        )
        r = AccountDetails(accountID=account_cfg["ACCOUNT_ID"])
        client.request(r)
        balance = float(r.response["account"]["balance"])
        equity = float(r.response["account"]["NAV"])
        return balance, equity
    except Exception as e:
        log_error(f"Failed to get account balance: {e}")
        return None, None
 
 
def calculate_units(equity, atr, max_risk_pct, price, is_forex=True,
                    sl_multiplier=1.5, sgd_to_usd=0.74, account_currency="SGD",
                    simulated_capital_usd=None):
    """
    Calculate position size based on ATR and max risk per trade.
    Designed for small accounts (~1000 SGD / $740 USD).
 
    If simulated_capital_usd is set, uses that fixed amount for sizing
    instead of actual account equity — simulates a real small account
    on top of a larger demo balance.
 
    For Gold (XAU_USD): units are troy ounces, max 1oz for small accounts.
    """
    stop_loss_distance = atr * sl_multiplier
 
    if stop_loss_distance <= 0:
        return 0
 
    # Use simulated capital if set, otherwise convert equity to USD
    if simulated_capital_usd:
        equity_usd = simulated_capital_usd
        log_info(f"Using simulated capital: ${equity_usd:.2f} USD (~1000 SGD)")
    elif account_currency == "SGD":
        equity_usd = equity * sgd_to_usd
    else:
        equity_usd = equity
 
    risk_amount_usd = equity_usd * max_risk_pct
 
    if is_forex:
        pip_value_per_unit = 0.0001
        stop_pips = stop_loss_distance / 0.0001
        units = int(risk_amount_usd / (stop_pips * pip_value_per_unit))
        units = max(100, min(units, 3000))
    else:
        # Gold: risk_amount_usd / stop_distance = oz
        units_float = risk_amount_usd / stop_loss_distance
        units = round(max(0.1, min(units_float, 1.0)), 1)  # max 1oz
        if units < 0.1:
            units = 0.1
 
    log_info(f"Position size: {units} units | Risk: ~${risk_amount_usd:.2f} USD | Stop: {stop_loss_distance:.2f}")
    return units
 
 
def check_drawdown(current_equity, peak_equity, max_drawdown_pct):
    """
    Returns True if drawdown limit exceeded (should halt trading).
    """
    if peak_equity <= 0:
        return False
 
    drawdown = (peak_equity - current_equity) / peak_equity
 
    if drawdown >= max_drawdown_pct:
        log_warning(f"Max drawdown reached: {drawdown:.2%} (limit: {max_drawdown_pct:.2%}). Halting.")
        return True
 
    log_info(f"Current drawdown: {drawdown:.2%} | Equity: ${current_equity:.2f} | Peak: ${peak_equity:.2f}")
    return False
 
 
def get_open_trades(account_cfg, symbol):
    """Returns list of open trades for a symbol."""
    try:
        client = API(
            access_token=account_cfg["API_KEY"],
            environment=account_cfg["ENVIRONMENT"]
        )
        params = {"instrument": symbol}
        r = TradesList(accountID=account_cfg["ACCOUNT_ID"], params=params)
        client.request(r)
        return r.response.get("trades", [])
    except Exception as e:
        log_error(f"Failed to get open trades: {e}")
        return []
 
 
def close_all_trades(account_cfg, symbol):
    """Close all open trades for a symbol before opening a new one."""
    try:
        trades = get_open_trades(account_cfg, symbol)
        if not trades:
            return True
 
        client = API(
            access_token=account_cfg["API_KEY"],
            environment=account_cfg["ENVIRONMENT"]
        )
 
        for trade in trades:
            trade_id = trade["id"]
            r = TradeClose(accountID=account_cfg["ACCOUNT_ID"], tradeID=trade_id)
            client.request(r)
            log_info(f"Closed trade {trade_id} for {symbol}")
 
        return True
    except Exception as e:
        log_error(f"Failed to close trades for {symbol}: {e}")
        return False
 
 
def get_price_precision(symbol):
    """
    Oanda requires different decimal precision per instrument.
    Gold (XAU_USD): 2 decimal places  e.g. 2645.50
    Forex pairs:    5 decimal places  e.g. 1.17845
    """
    if symbol == "XAU_USD":
        return 2
    return 5
 
 
# Tracks which trade IDs have already had a partial close performed.
# Prevents re-closing the same trade every cycle.
_partial_closed_trades = set()
 
 
def manage_open_trade_stops(account_cfg, symbol, alerts=None, rules_cfg=None):
    """
    Position management — runs every cycle for each symbol.
 
    Stage 0 — Partial profit taking (NEW, optional via rules_cfg):
        When price reaches X% of the way to TP (default 50%),
        close half the position. Locks in profit early. Runs ONCE per trade.
 
    Stage 1 — Move to breakeven:
        Once price has moved 50% of original_risk in our favour,
        move SL to entry price + small buffer (lock in ~0 loss).
 
    Stage 2 — Trail the stop:
        Once unrealized profit >= 100% of original risk,
        trail SL to lock in ~50% of current profit.
    """
    try:
        trades = get_open_trades(account_cfg, symbol)
        if not trades:
            return
 
        client = API(
            access_token=account_cfg["API_KEY"],
            environment=account_cfg["ENVIRONMENT"]
        )
        precision = get_price_precision(symbol)
 
        for trade in trades:
            trade_id = trade["id"]
            entry_price = float(trade["price"])
            current_units = float(trade["currentUnits"])
            unrealized_pl = float(trade["unrealizedPL"])
            is_long = current_units > 0
 
            # Get current SL
            sl_order = trade.get("stopLossOrder")
            if not sl_order:
                continue
            current_sl = float(sl_order["price"])
 
            # Get current TP to calculate original risk distance
            tp_order = trade.get("takeProfitOrder")
            if not tp_order:
                continue
            current_tp = float(tp_order["price"])
 
            # Original risk = distance from entry to SL (in price)
            original_risk = abs(entry_price - current_sl)
            # Full reward = distance from entry to TP
            full_reward = abs(current_tp - entry_price)
            # Current profit distance = how far price has moved in our favour
            # Use unrealizedPL / abs(units) to get per-unit P&L in USD
            units_abs = abs(current_units)
            profit_per_unit = unrealized_pl / units_abs if units_abs > 0 else 0
 
            # ─── Stage 0: Partial profit taking ──────────────
            # Close fraction of position when price reaches X% of the way to TP.
            # Tracked in module-level _partial_closed_trades set so it runs ONCE per trade.
            partial_cfg = (rules_cfg or {}).get("partial_profit_taking", {})
            if partial_cfg.get("enabled") and trade_id not in _partial_closed_trades:
                trigger_pct   = partial_cfg.get("trigger_pct_to_tp", 0.50)
                close_frac    = partial_cfg.get("close_fraction", 0.50)
                partial_trigger = full_reward * trigger_pct
 
                if is_long:
                    current_price_est_partial = entry_price + profit_per_unit
                    reached = current_price_est_partial >= (entry_price + partial_trigger)
                else:
                    current_price_est_partial = entry_price - profit_per_unit
                    reached = current_price_est_partial <= (entry_price - partial_trigger)
 
                if reached:
                    units_to_close = int(units_abs * close_frac)
                    if units_to_close > 0 and units_to_close < units_abs:
                        try:
                            import oandapyV20.endpoints.trades as trades_ep
                            close_data = {"units": str(units_to_close)}
                            r = trades_ep.TradeClose(
                                accountID=account_cfg["ACCOUNT_ID"],
                                tradeID=trade_id,
                                data=close_data
                            )
                            client.request(r)
                            _partial_closed_trades.add(trade_id)
                            log_info(f"[{symbol}] Stage 0 partial close: {units_to_close}/{int(units_abs)} units "
                                     f"closed at ~{trigger_pct:.0%} to TP")
                            if alerts:
                                alerts.notify(
                                    f"💰 *Partial profit taken*\n"
                                    f"Symbol: `{symbol}`\n"
                                    f"Closed: `{units_to_close}` of `{int(units_abs)}` units\n"
                                    f"At ~{trigger_pct:.0%} to TP — running half with breakeven"
                                )
                        except Exception as e:
                            log_error(f"Stage 0 partial close failed for {symbol}: {e}")
 
            new_sl = None
 
            if is_long:
                current_price_est = entry_price + profit_per_unit
                breakeven_trigger = entry_price + (original_risk * 0.5)
                trail_trigger = entry_price + original_risk
 
                if current_price_est >= trail_trigger:
                    # Stage 2: trail SL to lock in 50% of current profit
                    new_sl = round(entry_price + (profit_per_unit * 0.5), precision)
                    locked = unrealized_pl * 0.5
                    if new_sl > current_sl:
                        log_info(f"[{symbol}] Stage 2 trail: moving SL {current_sl} → {new_sl} (locking ${locked:.2f})")
                        if alerts:
                            alerts.trail_alert(symbol, current_sl, new_sl, locked)
                    else:
                        new_sl = None
 
                elif current_price_est >= breakeven_trigger:
                    # Stage 1: move SL to breakeven (entry + small buffer)
                    buffer = 0.0001 if symbol != "XAU_USD" else 0.10
                    new_sl = round(entry_price + buffer, precision)
                    if new_sl > current_sl:
                        log_info(f"[{symbol}] Stage 1 breakeven: moving SL {current_sl} → {new_sl}")
                        if alerts:
                            alerts.breakeven_alert(symbol, current_sl, new_sl)
                    else:
                        new_sl = None
 
            else:  # short trade
                current_price_est = entry_price - profit_per_unit
                breakeven_trigger = entry_price - (original_risk * 0.5)
                trail_trigger = entry_price - original_risk
 
                if current_price_est <= trail_trigger:
                    # Stage 2: trail SL to lock in 50% of current profit
                    new_sl = round(entry_price - (profit_per_unit * 0.5), precision)
                    locked = unrealized_pl * 0.5
                    if new_sl < current_sl:
                        log_info(f"[{symbol}] Stage 2 trail: moving SL {current_sl} → {new_sl} (locking ${locked:.2f})")
                        if alerts:
                            alerts.trail_alert(symbol, current_sl, new_sl, locked)
                    else:
                        new_sl = None
 
                elif current_price_est <= breakeven_trigger:
                    # Stage 1: move SL to breakeven (entry - small buffer)
                    buffer = 0.0001 if symbol != "XAU_USD" else 0.10
                    new_sl = round(entry_price - buffer, precision)
                    if new_sl < current_sl:
                        log_info(f"[{symbol}] Stage 1 breakeven: moving SL {current_sl} → {new_sl}")
                        if alerts:
                            alerts.breakeven_alert(symbol, current_sl, new_sl)
                    else:
                        new_sl = None
 
            # Apply new SL if triggered
            if new_sl is not None:
                import oandapyV20.endpoints.trades as trades_ep
                data = {
                    "stopLoss": {
                        "price": str(new_sl),
                        "timeInForce": "GTC"
                    }
                }
                r = trades_ep.TradeCRCDO(
                    accountID=account_cfg["ACCOUNT_ID"],
                    tradeID=trade_id,
                    data=data
                )
                client.request(r)
                log_info(f"[{symbol}] SL updated to {new_sl} for trade {trade_id}")
 
    except Exception as e:
        log_error(f"Failed to manage stops for {symbol}: {e}")
 
 
def place_order(account_cfg, symbol, units, side, atr, current_price,
               trail_multiplier=2.0, sl_multiplier=1.5, tp_multiplier=4.0):
    """
    Place a market order with stop loss and take profit.
    side: 'buy' or 'sell'
    units: positive number (can be fractional for gold)
    sl_multiplier: ATR multiplier for stop loss (default 1.5)
    tp_multiplier: ATR multiplier for take profit (default 4.0 = wider TP)
    """
    try:
        client = API(
            access_token=account_cfg["API_KEY"],
            environment=account_cfg["ENVIRONMENT"]
        )
 
        precision = get_price_precision(symbol)
 
        stop_distance = round(atr * sl_multiplier, precision)
        tp_distance = round(atr * tp_multiplier, precision)
 
        # Handle fractional units for gold on small accounts (e.g. 0.5oz, 1oz)
        if side == "buy":
            actual_units = str(float(units)) if symbol == "XAU_USD" else str(int(units))
            stop_loss_price = round(current_price - stop_distance, precision)
            take_profit_price = round(current_price + tp_distance, precision)
        else:
            actual_units = str(-float(units)) if symbol == "XAU_USD" else str(-int(units))
            stop_loss_price = round(current_price + stop_distance, precision)
            take_profit_price = round(current_price - tp_distance, precision)
 
        order_data = {
            "order": {
                "type": "MARKET",
                "instrument": symbol,
                "units": actual_units,
                "stopLossOnFill": {
                    "price": str(stop_loss_price)
                },
                "takeProfitOnFill": {
                    "price": str(take_profit_price)
                },
                "timeInForce": "FOK"
            }
        }
 
        r = OrderCreate(accountID=account_cfg["ACCOUNT_ID"], data=order_data)
        client.request(r)
 
        log_info(f"Order placed: {side.upper()} {units} units of {symbol} @ ~{current_price} | SL: {stop_loss_price} | TP: {take_profit_price}")
        return True
 
    except Exception as e:
        log_error(f"Order failed for {symbol}: {e}")
        return False