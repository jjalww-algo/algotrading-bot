"""
rules.py
--------
The 7 trading discipline rules.
 
Each rule is a function that takes the rule config + state and returns
either a halt reason (str) or None (proceed). Functions are intentionally
small and independent so they can be toggled on/off via config.
 
Rules implemented:
  1. pre_financing_close  — close all positions before 5 AM UTC daily
  2. no_weekend_holds     — close positions Friday, no weekend exposure
  3. max_consecutive_losses — pause symbol after N losses in a row
  4. max_daily_trades     — hard cap on trades per UTC day
  5. news_blackout        — block trading around scheduled news events
  6. session_open_skip    — skip first N min of London/NY opens
  7. partial_profit_taking — see manage_partial_close() in risk_manager.py
 
State tracking is done with simple dicts that the main loop owns.
This module just inspects state — it doesn't mutate it directly.
"""
 
from datetime import datetime, timezone, timedelta
from logger import log_info, log_warning
 
 
# ─────────────────────────────────────────
# Rule 1 — pre-financing close
# ─────────────────────────────────────────
def should_close_before_financing(rules_cfg):
    """
    Returns True if we're in the pre-financing close window.
    OANDA charges daily financing at 5 AM UTC. We want to be flat by then.
    """
    cfg = rules_cfg.get("pre_financing_close", {})
    if not cfg.get("enabled"):
        return False
 
    minutes_before = cfg.get("close_minutes_before_5am_utc", 10)
    now            = datetime.now(timezone.utc)
 
    # Window: from (5 AM - minutes_before) to 5 AM
    window_start = now.replace(hour=5, minute=0, second=0, microsecond=0) - timedelta(minutes=minutes_before)
    window_end   = now.replace(hour=5, minute=0, second=0, microsecond=0)
 
    return window_start <= now < window_end
 
 
# ─────────────────────────────────────────
# Rule 2 — no weekend holds
# ─────────────────────────────────────────
def should_block_friday_entries(rules_cfg):
    """
    Returns True if we're past the Friday cutoff hour.
    Don't OPEN new trades after this point — they could carry into the weekend.
    """
    cfg = rules_cfg.get("no_weekend_holds", {})
    if not cfg.get("enabled"):
        return False
 
    cutoff_hour = cfg.get("friday_cutoff_hour_utc", 20)
    now         = datetime.now(timezone.utc)
 
    # weekday() — Monday=0, Friday=4, Saturday=5, Sunday=6
    if now.weekday() == 4 and now.hour >= cutoff_hour:
        return True
    # Also block all Saturday and Sunday (markets closed but be safe)
    if now.weekday() in (5, 6):
        return True
    return False
 
 
def should_force_close_friday(rules_cfg):
    """
    Returns True if it's the forced-close hour on Friday.
    CLOSE existing positions to be flat for the weekend.
    """
    cfg = rules_cfg.get("no_weekend_holds", {})
    if not cfg.get("enabled"):
        return False
 
    close_hour = cfg.get("friday_close_hour_utc", 21)
    now        = datetime.now(timezone.utc)
 
    return now.weekday() == 4 and now.hour == close_hour
 
 
# ─────────────────────────────────────────
# Rule 3 — max consecutive losses
# ─────────────────────────────────────────
def is_loss_streak_halted(symbol, rules_cfg, loss_streak_state):
    """
    Returns True if this symbol is currently halted due to a loss streak.
    loss_streak_state is a dict per symbol: {'count': int, 'halt_until': datetime|None}
    """
    cfg = rules_cfg.get("max_consecutive_losses", {})
    if not cfg.get("enabled"):
        return False
 
    state = loss_streak_state.get(symbol, {})
    halt_until = state.get("halt_until")
 
    if halt_until and datetime.now(timezone.utc) < halt_until:
        remaining = (halt_until - datetime.now(timezone.utc)).total_seconds() / 60
        log_info(f"Loss streak halt [{symbol}]: {remaining:.0f} min remaining")
        return True
    return False
 
 
def record_trade_outcome(symbol, pnl, rules_cfg, loss_streak_state):
    """
    Update the loss streak counter for a symbol after a trade closes.
    If we hit max_losses, set halt_until.
    Mutates loss_streak_state in place.
    """
    cfg = rules_cfg.get("max_consecutive_losses", {})
    if not cfg.get("enabled"):
        return
 
    max_losses     = cfg.get("max_losses", 3)
    cooldown_hours = cfg.get("cooldown_hours", 2)
 
    if symbol not in loss_streak_state:
        loss_streak_state[symbol] = {"count": 0, "halt_until": None}
 
    if pnl < 0:
        loss_streak_state[symbol]["count"] += 1
        log_info(f"Loss streak [{symbol}]: {loss_streak_state[symbol]['count']}/{max_losses}")
 
        if loss_streak_state[symbol]["count"] >= max_losses:
            halt_until = datetime.now(timezone.utc) + timedelta(hours=cooldown_hours)
            loss_streak_state[symbol]["halt_until"] = halt_until
            loss_streak_state[symbol]["count"]      = 0
            log_warning(f"Loss streak halt triggered [{symbol}]: halted until {halt_until}")
    else:
        # Win — reset counter
        if loss_streak_state[symbol]["count"] > 0:
            log_info(f"Loss streak reset [{symbol}] — win clears counter")
        loss_streak_state[symbol]["count"] = 0
 
 
# ─────────────────────────────────────────
# Rule 4 — max daily trades
# ─────────────────────────────────────────
def is_daily_trade_limit_hit(rules_cfg, daily_trade_count):
    """
    Returns True if we've already hit the max trades per UTC day.
    daily_trade_count is just an int, reset each UTC day by the main loop.
    """
    cfg = rules_cfg.get("max_daily_trades", {})
    if not cfg.get("enabled"):
        return False
 
    max_trades = cfg.get("max_trades", 15)
    if daily_trade_count >= max_trades:
        log_info(f"Daily trade limit hit: {daily_trade_count}/{max_trades}")
        return True
    return False
 
 
# ─────────────────────────────────────────
# Rule 5 — news blackout
# ─────────────────────────────────────────
def is_news_blackout(rules_cfg):
    """
    Returns True if we're inside a news blackout window.
 
    Reads scheduled_events_utc from config — list of ISO timestamp strings:
    ["2026-04-25T12:30:00", "2026-04-25T18:00:00", ...]
 
    For each event, the blackout window is:
        (event_time - minutes_before)  to  (event_time + minutes_after)
 
    To use this rule effectively, populate scheduled_events_utc weekly
    from a calendar like ForexFactory or Investing.com.
    """
    cfg = rules_cfg.get("news_blackout", {})
    if not cfg.get("enabled"):
        return False
 
    events = cfg.get("scheduled_events_utc", [])
    if not events:
        return False
 
    minutes_before = cfg.get("minutes_before", 15)
    minutes_after  = cfg.get("minutes_after", 30)
    now            = datetime.now(timezone.utc)
 
    for event_str in events:
        try:
            # Parse ISO timestamp, assume UTC if no tz given
            event_time = datetime.fromisoformat(event_str)
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            log_warning(f"Bad news event timestamp in config: {event_str}")
            continue
 
        window_start = event_time - timedelta(minutes=minutes_before)
        window_end   = event_time + timedelta(minutes=minutes_after)
 
        if window_start <= now <= window_end:
            log_info(f"News blackout active: event at {event_time} (window {window_start} - {window_end})")
            return True
    return False
 
 
# ─────────────────────────────────────────
# Rule 6 — session open skip
# ─────────────────────────────────────────
def is_in_session_open_skip(rules_cfg):
    """
    Returns True if we're inside the first N minutes of London or NY open.
    London open = 8 AM UTC, NY open = 1 PM UTC by default.
    """
    cfg = rules_cfg.get("session_open_skip", {})
    if not cfg.get("enabled"):
        return False
 
    skip_minutes = cfg.get("skip_minutes", 30)
    london_hour  = cfg.get("london_open_hour_utc", 8)
    ny_hour      = cfg.get("ny_open_hour_utc", 13)
 
    now = datetime.now(timezone.utc)
 
    # London open window
    if now.hour == london_hour and now.minute < skip_minutes:
        log_info(f"London open skip active — {skip_minutes - now.minute} min remaining")
        return True
 
    # NY open window
    if now.hour == ny_hour and now.minute < skip_minutes:
        log_info(f"NY open skip active — {skip_minutes - now.minute} min remaining")
        return True
 
    return False
 
 
# ─────────────────────────────────────────
# Master pre-trade check
# ─────────────────────────────────────────
def check_all_rules_before_entry(symbol, rules_cfg, state):
    """
    Master pre-trade gate. Runs all rules that should block NEW trade entries.
    Returns (should_block, reason) tuple.
 
    state is a dict containing:
      - loss_streak_state: dict per symbol
      - daily_trade_count: int
    """
    if should_block_friday_entries(rules_cfg):
        return True, "Weekend lockout — no Friday-evening or weekend entries"
 
    if should_close_before_financing(rules_cfg):
        return True, "Pre-financing close window — flattening, no new trades"
 
    if is_news_blackout(rules_cfg):
        return True, "Scheduled news blackout"
 
    if is_in_session_open_skip(rules_cfg):
        return True, "Session open skip window"
 
    if is_daily_trade_limit_hit(rules_cfg, state.get("daily_trade_count", 0)):
        return True, "Daily trade limit reached"
 
    if is_loss_streak_halted(symbol, rules_cfg, state.get("loss_streak_state", {})):
        return True, f"Loss streak halt active for {symbol}"
 
    return False, ""