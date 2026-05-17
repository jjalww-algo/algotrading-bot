"""
features.py
-----------
Computes all technical indicators used as ML features.
 
Key additions over v1:
- ADX (Average Directional Index) — measures trend STRENGTH, not direction.
  ADX > 25 = trending market. ADX < 20 = ranging/choppy market.
  This is critical for regime detection in main.py.
- Stochastic oscillator — better overbought/oversold signal than RSI alone
- Price position relative to EMA200 — tells model where price is in big picture
- Candle body ratio — distinguishes strong directional candles from dojis/noise
"""
 
import pandas as pd
import numpy as np
import ta
from logger import log_error
 
 
def compute_features(df):
    """
    Compute technical indicators used as ML features.
    Returns DataFrame with added feature columns, NaN rows dropped.
    """
    try:
        df = df.copy()
 
        # Trend
        df["ema_fast"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["ema_slow"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["ema200"]   = ta.trend.EMAIndicator(df["Close"], window=200).ema_indicator()
        df["ema_diff"] = (df["ema_fast"] - df["ema_slow"]) / df["Close"]
        df["price_vs_ema200"] = (df["Close"] - df["ema200"]) / df["Close"]
 
        # ADX regime detector
        adx_ind     = ta.trend.ADXIndicator(df["High"], df["Low"], df["Close"], window=14)
        df["adx"]   = adx_ind.adx()
        df["adx_pos"] = adx_ind.adx_pos()
        df["adx_neg"] = adx_ind.adx_neg()
        df["di_diff"] = (df["adx_pos"] - df["adx_neg"]) / (df["adx"] + 1e-9)
 
        # Momentum
        df["rsi"]  = ta.momentum.RSIIndicator(df["Close"], window=14).rsi()
        df["mom"]  = df["Close"].diff(10)
        df["roc"]  = df["Close"].pct_change(10)
        stoch      = ta.momentum.StochasticOscillator(
            df["High"], df["Low"], df["Close"], window=14, smooth_window=3)
        df["stoch_k"] = stoch.stoch()
        df["stoch_d"] = stoch.stoch_signal()
 
        # Volatility
        atr_ind       = ta.volatility.AverageTrueRange(df["High"], df["Low"], df["Close"], window=14)
        df["atr"]     = atr_ind.average_true_range()
        df["vol_pct"] = df["atr"] / df["Close"] * 100
        df["atr_ratio"] = df["atr"] / (df["atr"].rolling(50).mean() + 1e-9)
 
        # Volume
        df["vol_ma"]    = df["Volume"].rolling(20).mean()
        df["vol_ratio"] = df["Volume"] / (df["vol_ma"] + 1e-9)
 
        # Candle structure
        df["wick_up"]    = df["High"] - df[["Open", "Close"]].max(axis=1)
        df["wick_down"]  = df[["Open", "Close"]].min(axis=1) - df["Low"]
        df["avg_wick"]   = (df["wick_up"] + df["wick_down"]).rolling(20).mean()
        df["wick_ratio"] = (df["wick_up"] + df["wick_down"]) / (df["avg_wick"] + 1e-9)
        candle_range     = (df["High"] - df["Low"]).replace(0, 1e-9)
        df["body_ratio"] = abs(df["Close"] - df["Open"]) / candle_range
 
        # Bollinger Bands
        bb = ta.volatility.BollingerBands(df["Close"], window=20)
        df["bb_width"] = (bb.bollinger_hband() - bb.bollinger_lband()) / df["Close"]
        df["bb_pct"]   = bb.bollinger_pband()
 
        # MACD
        macd = ta.trend.MACD(df["Close"])
        df["macd_diff"] = macd.macd_diff()
 
        df.dropna(inplace=True)
        return df
 
    except Exception as e:
        log_error(f"Feature computation error: {e}")
        return df
 
 
FEATURE_COLS = [
    "ema_diff", "price_vs_ema200",
    "adx", "di_diff",
    "rsi", "mom", "roc", "stoch_k", "stoch_d",
    "vol_pct", "atr_ratio",
    "vol_ratio",
    "wick_ratio", "body_ratio",
    "bb_width", "bb_pct",
    "macd_diff",
]
 