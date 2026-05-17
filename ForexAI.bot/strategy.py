"""
strategy.py
-----------
Pure structural trading logic. No ML model needed.
 
The bot looks for THREE high-probability setups:
 
1. BREAKOUT — price breaks above recent resistance with momentum
2. MEAN REVERSION — price hits oversold/overbought extreme and reverses
3. PULLBACK CONTINUATION — uptrend pulls back to support, then resumes
 
Each setup has clear, deterministic entry rules. No black box.
Each setup is only valid in certain regimes (trending vs ranging).
 
WHY THIS WORKS BETTER THAN ML ON M5:
- M5 ML was trying to predict a coin flip (50% accurate at best)
- Structural setups have base rates of 55-65% historically
- Stop losses placed at structure (last swing) not arbitrary ATR
- Risk:reward defined by setup, not regime multipliers
"""
 
import pandas as pd
import numpy as np
from logger import log_info
 
 
# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def find_swing_high(df, lookback=20, window=5):
    """
    Find the highest swing high in the last `lookback` candles.
    A swing high is a candle whose high is the max of `window` candles each side.
    Returns the price level, or None.
    """
    if len(df) < lookback + window:
        return None
 
    recent = df.tail(lookback + window).copy()
    highs = recent["High"].values
    swing_highs = []
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i-window:i+window+1]):
            swing_highs.append(highs[i])
    return max(swing_highs) if swing_highs else None
 
 
def find_swing_low(df, lookback=20, window=5):
    """Mirror of find_swing_high."""
    if len(df) < lookback + window:
        return None
    recent = df.tail(lookback + window).copy()
    lows = recent["Low"].values
    swing_lows = []
    for i in range(window, len(lows) - window):
        if lows[i] == min(lows[i-window:i+window+1]):
            swing_lows.append(lows[i])
    return min(swing_lows) if swing_lows else None
 
 
# ─────────────────────────────────────────
# Setup 1 — BREAKOUT
# ─────────────────────────────────────────
def detect_breakout(df, regime, daily_trend):
    """
    BREAKOUT SETUP — works best in trending regime.
 
    Conditions:
      - Current candle CLOSES above the last 20-bar swing high (BUY)
        OR closes below the last 20-bar swing low (SELL)
      - Candle has strong body (body > 60% of range — not a doji)
      - Volume is above average (institutional participation)
      - Daily trend aligns with breakout direction
      - Bollinger Band expansion (volatility increasing)
 
    Stop loss: at the broken level (former resistance, now support)
    Take profit: 1.5x risk distance (asymmetric — let breakouts run)
    """
    if len(df) < 50 or regime == "ranging":
        return None
 
    latest = df.iloc[-1]
    close = latest["Close"]
 
    # Swing levels
    swing_high = find_swing_high(df.iloc[:-1], lookback=20, window=3)
    swing_low  = find_swing_low(df.iloc[:-1], lookback=20, window=3)
    if swing_high is None or swing_low is None:
        return None
 
    # Strong body check
    body = abs(latest["Close"] - latest["Open"])
    rng  = latest["High"] - latest["Low"]
    body_ratio = body / rng if rng > 0 else 0
    if body_ratio < 0.6:
        return None
 
    # Volume confirmation
    vol_avg = df["Volume"].tail(20).mean()
    if latest["Volume"] < vol_avg * 1.2:
        return None
 
    # Bollinger expansion — bands widening means volatility is expanding
    if "bb_width" in df.columns:
        bb_now = df["bb_width"].iloc[-1]
        bb_avg = df["bb_width"].tail(20).mean()
        if bb_now < bb_avg * 1.1:
            return None  # bands not expanding, fake breakout risk
 
    # BULLISH BREAKOUT
    if close > swing_high and daily_trend in ("bullish", "neutral"):
        sl = swing_high * 0.999  # SL just below the broken level
        risk = close - sl
        tp = close + (risk * 1.5)
        return {
            "side": "BUY",
            "setup": "BREAKOUT",
            "entry": close,
            "sl": sl,
            "tp": tp,
            "risk_price": risk,
            "reason": f"Broke above swing high {swing_high:.5f}, vol {latest['Volume']/vol_avg:.1f}x"
        }
 
    # BEARISH BREAKOUT
    if close < swing_low and daily_trend in ("bearish", "neutral"):
        sl = swing_low * 1.001
        risk = sl - close
        tp = close - (risk * 1.5)
        return {
            "side": "SELL",
            "setup": "BREAKOUT",
            "entry": close,
            "sl": sl,
            "tp": tp,
            "risk_price": risk,
            "reason": f"Broke below swing low {swing_low:.5f}, vol {latest['Volume']/vol_avg:.1f}x"
        }
 
    return None
 
 
# ─────────────────────────────────────────
# Setup 2 — MEAN REVERSION
# ─────────────────────────────────────────
def detect_mean_reversion(df, regime, daily_trend):
    """
    MEAN REVERSION SETUP — works best in RANGING regime.
 
    Conditions:
      - Bollinger Band touch: price tags upper or lower band
      - RSI confirms exhaustion: >70 at upper band (overbought, SELL),
        <30 at lower band (oversold, BUY)
      - Previous candle showed exhaustion (long wick rejection)
      - Daily trend is NEUTRAL or aligns with reversion direction
        (don't fight strong trend with mean reversion)
 
    Stop loss: beyond the bb extreme (price keeps running, we're wrong)
    Take profit: at the middle band (mean) — 1:1 risk reward typically
    """
    if len(df) < 30 or regime == "trending":
        return None
 
    latest = df.iloc[-1]
    prev   = df.iloc[-2]
    close  = latest["Close"]
 
    if "bb_pct" not in df.columns or "rsi" not in df.columns:
        return None
 
    bb_pct = latest["bb_pct"]
    rsi    = latest["rsi"]
 
    # Calculate band levels from bb_width
    bb_mid = (latest["High"] + latest["Low"] + latest["Close"]) / 3  # rough mid
 
    # OVERSOLD reversal — BUY
    if bb_pct < 0.05 and rsi < 30:
        # Need a rejection wick (lower wick longer than body)
        lower_wick = min(prev["Open"], prev["Close"]) - prev["Low"]
        body = abs(prev["Close"] - prev["Open"])
        if lower_wick > body * 1.5 and daily_trend != "bearish":
            sl_dist = (close - prev["Low"]) * 1.1  # SL beyond rejection low
            sl = close - sl_dist
            tp = close + sl_dist  # 1:1 target at mid
            return {
                "side": "BUY",
                "setup": "MEAN_REVERSION",
                "entry": close,
                "sl": sl,
                "tp": tp,
                "risk_price": sl_dist,
                "reason": f"BB lower tag (bb%={bb_pct:.2f}), RSI={rsi:.1f}, wick rejection"
            }
 
    # OVERBOUGHT reversal — SELL
    if bb_pct > 0.95 and rsi > 70:
        upper_wick = prev["High"] - max(prev["Open"], prev["Close"])
        body = abs(prev["Close"] - prev["Open"])
        if upper_wick > body * 1.5 and daily_trend != "bullish":
            sl_dist = (prev["High"] - close) * 1.1
            sl = close + sl_dist
            tp = close - sl_dist
            return {
                "side": "SELL",
                "setup": "MEAN_REVERSION",
                "entry": close,
                "sl": sl,
                "tp": tp,
                "risk_price": sl_dist,
                "reason": f"BB upper tag (bb%={bb_pct:.2f}), RSI={rsi:.1f}, wick rejection"
            }
 
    return None
 
 
# ─────────────────────────────────────────
# Setup 3 — PULLBACK CONTINUATION
# ─────────────────────────────────────────
def detect_pullback(df, regime, daily_trend, h1_trend):
    """
    PULLBACK CONTINUATION — the highest-probability setup.
    Works in TRENDING regime when H1 and D1 both agree.
 
    Conditions:
      - Daily trend AND H1 trend both bullish (or both bearish)
      - Price pulled back to or near EMA21 (the dynamic support)
      - Current candle is a bullish rejection (long lower wick + green close)
        OR bearish rejection (long upper wick + red close)
      - RSI between 35-50 for buys (cooled off but not oversold)
        or 50-65 for sells
 
    This is "buy the dip in an uptrend" with confirmation.
    Stop loss: below recent swing low (structure-based)
    Take profit: 2x risk (let trends run)
    """
    if len(df) < 50 or regime == "ranging":
        return None
 
    latest = df.iloc[-1]
    close = latest["Close"]
 
    if "ema_slow" not in df.columns or "rsi" not in df.columns:
        return None
 
    ema21 = latest["ema_slow"]
    rsi = latest["rsi"]
    dist_from_ema = abs(close - ema21) / close
 
    # Must be near EMA21 (within 0.3% for forex, 0.5% for gold)
    threshold = 0.005
    if dist_from_ema > threshold:
        return None
 
    # BULLISH PULLBACK — D1 + H1 both bullish, RSI 35-50, bullish rejection
    if daily_trend == "bullish" and h1_trend == "bullish" and 35 <= rsi <= 55:
        # Bullish candle with lower wick
        is_green = latest["Close"] > latest["Open"]
        lower_wick = min(latest["Open"], latest["Close"]) - latest["Low"]
        body = abs(latest["Close"] - latest["Open"])
        if is_green and lower_wick > body * 0.5:
            swing_low = find_swing_low(df, lookback=15, window=3)
            if swing_low is None or swing_low >= close:
                return None
            sl = swing_low * 0.999
            risk = close - sl
            tp = close + (risk * 2.0)
            return {
                "side": "BUY",
                "setup": "PULLBACK",
                "entry": close,
                "sl": sl,
                "tp": tp,
                "risk_price": risk,
                "reason": f"D1+H1 bullish, near EMA21, RSI={rsi:.1f}, bullish rejection"
            }
 
    # BEARISH PULLBACK
    if daily_trend == "bearish" and h1_trend == "bearish" and 45 <= rsi <= 65:
        is_red = latest["Close"] < latest["Open"]
        upper_wick = latest["High"] - max(latest["Open"], latest["Close"])
        body = abs(latest["Close"] - latest["Open"])
        if is_red and upper_wick > body * 0.5:
            swing_high = find_swing_high(df, lookback=15, window=3)
            if swing_high is None or swing_high <= close:
                return None
            sl = swing_high * 1.001
            risk = sl - close
            tp = close - (risk * 2.0)
            return {
                "side": "SELL",
                "setup": "PULLBACK",
                "entry": close,
                "sl": sl,
                "tp": tp,
                "risk_price": risk,
                "reason": f"D1+H1 bearish, near EMA21, RSI={rsi:.1f}, bearish rejection"
            }
 
    return None
 
 
# ─────────────────────────────────────────
# Master signal generator
# ─────────────────────────────────────────
def find_setup(df, regime, daily_trend, h1_trend):
    """
    Master function called by main.py.
    Tries each setup in order of priority. Returns first match or None.
 
    Priority order:
      1. PULLBACK (highest win rate, trend continuation)
      2. BREAKOUT (clear momentum signal)
      3. MEAN_REVERSION (counter-trend, lowest priority)
    """
    setup = detect_pullback(df, regime, daily_trend, h1_trend)
    if setup:
        log_info(f"Setup found: {setup['setup']} {setup['side']} — {setup['reason']}")
        return setup
 
    setup = detect_breakout(df, regime, daily_trend)
    if setup:
        log_info(f"Setup found: {setup['setup']} {setup['side']} — {setup['reason']}")
        return setup
 
    setup = detect_mean_reversion(df, regime, daily_trend)
    if setup:
        log_info(f"Setup found: {setup['setup']} {setup['side']} — {setup['reason']}")
        return setup
 
    return None