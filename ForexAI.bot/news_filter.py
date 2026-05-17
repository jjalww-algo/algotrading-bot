import requests
from datetime import datetime, timezone
from logger import log_info, log_warning
 
 
# High-impact economic keywords that should halt trading
HIGH_IMPACT_KEYWORDS = [
    "fed", "federal reserve", "fomc", "rate decision", "interest rate",
    "nonfarm payroll", "nfp", "cpi", "inflation", "gdp",
    "unemployment", "ecb", "bank of england", "boe",
    "flash crash", "circuit breaker", "halt", "emergency",
    "war", "attack", "crisis", "default", "collapse",
    "pmi", "retail sales", "jobs report"
]
 
# Max spread as a fraction of ATR.
# If spread > this fraction of ATR, trade cost is too high vs expected move.
# Normal EUR spread ~0.00015 (1.5 pips). Normal ATR ~0.0008 (8 pips).
# Ratio = 0.19 in normal conditions.
# During war on 16/03: spread was $1.81 SGD on a $0.21 normal trade → 8.6× = ratio ~1.6
# We halt if spread > 40% of ATR — that still allows entry in mildly elevated conditions
# but blocks the extreme 3×+ war-time spikes.
MAX_SPREAD_ATR_RATIO = 0.40
 
 
def check_spread_cost(df, symbol):
    """
    Estimates whether the current spread is too wide to trade profitably.
 
    Uses the wick_up + wick_down on the most recent candle as a proxy for
    bid-ask spread (OANDA's midpoint pricing means the true spread is hidden,
    but abnormally wide wicks on tiny-body candles are a reliable spread signal).
 
    A simpler and more direct check: compares the current ATR to a rolling
    baseline. When ATR doubles, spreads typically triple. We use ATR ratio
    directly since we already compute it in features.
 
    Returns True if spread is too wide (halt), False if safe to trade.
    """
    if len(df) < 20:
        return False
 
    # atr_ratio is already computed in features.py:
    # current ATR / 50-period average ATR
    # >2.5 during war = spreads are likely 3-5× normal = don't trade
    if "atr_ratio" in df.columns:
        atr_ratio = df["atr_ratio"].iloc[-1]
        if atr_ratio > 2.5:
            log_warning(
                f"Spread guard [{symbol}]: ATR ratio {atr_ratio:.2f} > 2.5 "
                f"— spreads likely {atr_ratio:.1f}× normal. Skipping entry."
            )
            return True
 
    return False
 
 
def check_finnhub_news(api_key, category="forex"):
    """
    Pulls latest news from Finnhub and checks for high-impact keywords.
    Returns True if trading should be halted, False if safe.
    """
    try:
        url = f"https://finnhub.io/api/v1/news?category={category}&token={api_key}"
        resp = requests.get(url, timeout=5)
        articles = resp.json()
 
        if not articles:
            return False
 
        # Check top 5 most recent headlines
        for article in articles[:5]:
            headline = article.get("headline", "").lower()
            for keyword in HIGH_IMPACT_KEYWORDS:
                if keyword in headline:
                    log_warning(f"News halt triggered: '{headline}'")
                    return True
 
        return False
 
    except Exception as e:
        log_warning(f"Finnhub news check failed: {e} — defaulting to safe (no halt)")
        return False
 
 
def check_volatility_spike(df, atr_multiplier=2.0):
    """
    Detects abnormal volatility in the latest candle.
    Proxy for sudden news events when no API is available.
    Returns True if spike detected (halt trading).
    """
    if len(df) < 20:
        return False
 
    current_atr = df["atr"].iloc[-1]
    avg_atr = df["atr"].iloc[-20:].mean()
 
    if current_atr > avg_atr * atr_multiplier:
        log_warning(f"Volatility spike detected: ATR {current_atr:.5f} vs avg {avg_atr:.5f}")
        return True
 
    return False
 
 
def check_wick_spike(df, wick_threshold=2.5):
    """
    Detects candle wick anomalies — large wicks signal sudden price rejection
    often caused by news events.
    Returns True if wick spike detected (halt trading).
    """
    if len(df) < 20:
        return False
 
    wick_ratio = df["wick_ratio"].iloc[-1]
 
    if wick_ratio > wick_threshold:
        log_warning(f"Wick spike detected: ratio {wick_ratio:.2f}")
        return True
 
    return False
 
 
def check_volume_spike(df, volume_threshold=2.0):
    """
    Detects abnormal volume — a proxy for institutional news-driven moves.
    Returns True if volume spike detected (halt trading).
    """
    if len(df) < 20:
        return False
 
    vol_ratio = df["vol_ratio"].iloc[-1]
 
    if vol_ratio > volume_threshold:
        log_warning(f"Volume spike detected: ratio {vol_ratio:.2f}")
        return True
 
    return False
 
 
def is_trading_session_active(session_cfg=None):
    """
    Checks if current time is within an active trading session.
 
    Sessions for Gold (XAU_USD):
    - London + NY: 08:00 - 22:00 UTC (high volume, strong trends)
    - Asia:        00:00 - 08:00 UTC (lower volume but gold still moves)
 
    Asia session is optional — enabled via config trading.sessions.trade_asia
    """
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
 
    # Default: London + NY only
    in_london_ny = 8 <= hour < 22
 
    # Asia session: midnight to 8am UTC
    in_asia = 0 <= hour < 8
 
    # Check if Asia trading is enabled in config
    trade_asia = False
    if session_cfg and session_cfg.get("trade_asia", False):
        trade_asia = True
 
    if in_london_ny:
        log_info(f"Active session: London/NY (UTC {hour}:00)")
        return True
 
    if in_asia and trade_asia:
        log_info(f"Active session: Asia (UTC {hour}:00)")
        return True
 
    log_info(f"Outside active trading session (UTC {hour}:00). Skipping.")
    return False
 
 
def should_halt_trading(df, finnhub_cfg, session_cfg=None, symbol=""):
    """
    Master halt check. Combines all filters.
    Returns (halt: bool, reason: str)
    """
    # Session check
    if not is_trading_session_active(session_cfg):
        return True, "Outside trading session"
 
    # Spread guard — war-time spread explosion killer
    if check_spread_cost(df, symbol):
        return True, "Spread too wide (war/news conditions)"
 
    # Volatility spike
    if check_volatility_spike(df):
        return True, "Volatility spike"
 
    # Wick spike
    if check_wick_spike(df):
        return True, "Wick spike (news proxy)"
 
    # Volume spike
    if check_volume_spike(df):
        return True, "Volume spike"
 
    # Finnhub news (only if enabled and key provided)
    if finnhub_cfg.get("enabled") and finnhub_cfg.get("API_KEY") != "YOUR_FINNHUB_API_KEY_HERE":
        if check_finnhub_news(finnhub_cfg["API_KEY"]):
            return True, "Finnhub news event"
 
    return False, ""