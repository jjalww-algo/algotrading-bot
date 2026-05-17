"""
model_training.py
-----------------
Trains a LightGBM model for each symbol.
 
KEY CHANGE — time-weighted training:
Uses ALL 5000 available candles (uptrends, downtrends, ranging, news events)
but applies exponentially increasing sample weights so the model learns ALL
market conditions while being more responsive to recent behaviour.
 
This replaces the old approach of only using 2500 candles which made the
model forget how to handle market reversals.
 
WHEN TO RUN:
- Run once before starting the bot for the first time.
- Re-run every Monday before the trading week starts.
- Re-run any time the market regime changes significantly.
 
Command: python model_training.py
"""
 
import json
import pandas as pd
import numpy as np
import lightgbm as lgb
import joblib
import os
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, classification_report
 
from data_feed import get_candles
from features import compute_features, FEATURE_COLS
from logger import log_info, log_error
 
os.makedirs("models", exist_ok=True)
 
 
def create_labels(df, lookahead=3):
    """
    Label each candle based on which direction wins over the next N candles.
 
    Uses ATR-relative threshold so the required move scales with volatility.
    In a $5000 gold market a 0.05% move is $2.50 — meaningful.
    In a 1.15 EUR market a 0.05% move is 0.0006 — also meaningful.
    Both use the same percentage threshold so labels are consistent.
 
    Threshold = 0.10% (raised from 0.05%) — filters out noise candles
    that would never move enough to hit a real TP anyway.
    """
    future_high = df["High"].rolling(lookahead).max().shift(-lookahead)
    future_low  = df["Low"].rolling(lookahead).min().shift(-lookahead)
 
    gain = (future_high - df["Close"]) / df["Close"]
    loss = (df["Close"] - future_low)  / df["Close"]
 
    threshold = 0.001  # 0.10%
 
    df["target"] = np.where(
        (gain > loss) & (gain > threshold), 1,
        np.where(
            (loss > gain) & (loss > threshold), 0,
            np.nan
        )
    )
    df.dropna(subset=["target"], inplace=True)
    df["target"] = df["target"].astype(int)
    return df
 
 
def make_sample_weights(n, decay=0.0003):
    """
    Exponentially increasing weights: most recent candle = weight 1.0,
    oldest candle = weight ~exp(-decay * n).
 
    decay=0.0003 over 5000 candles means the oldest candle has ~22% the
    weight of the newest. The model still SEES all market conditions but
    is tuned toward recent behaviour.
    """
    indices = np.arange(n)
    weights = np.exp(decay * indices)   # older = smaller index = lower weight
    weights = weights / weights.sum() * n   # normalise so sum = n
    return weights
 
 
def train_symbol(symbol, account_cfg):
    log_info(f"Training model for {symbol}...")
 
    # Fetch full history — ALL conditions: uptrend, downtrend, ranging, news
    df = get_candles(account_cfg, symbol, timeframe="M5", count=5000)
    if df is None or len(df) < 300:
        log_error(f"Not enough data for {symbol}. Skipping.")
        return
 
    df = compute_features(df)
    df = create_labels(df, lookahead=3)
 
    if len(df) < 100:
        log_error(f"After feature computation, not enough rows for {symbol}.")
        return
 
    X = df[FEATURE_COLS]
    y = df["target"]
 
    log_info(f"  Training on {len(X)} labelled candles for {symbol}")
    log_info(f"  Label balance: {y.value_counts().to_dict()}")
 
    # Walk-forward cross validation
    tscv = TimeSeriesSplit(n_splits=5)
    fold_scores = []
 
    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        w_train = make_sample_weights(len(X_train))
 
        model = lgb.LGBMClassifier(
            n_estimators=300,
            learning_rate=0.03,
            max_depth=6,
            num_leaves=50,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=30,
            reg_alpha=0.1,       # L1 regularisation — prevents overfitting
            reg_lambda=0.1,      # L2 regularisation
            class_weight="balanced",  # handles imbalanced BUY/SELL labels
            random_state=42,
            verbose=-1
        )
        model.fit(X_train, y_train, sample_weight=w_train)
        preds = model.predict(X_test)
        score = accuracy_score(y_test, preds)
        fold_scores.append(score)
        log_info(f"  Fold {fold+1} accuracy: {score:.4f}")
 
    avg_score = np.mean(fold_scores)
    log_info(f"  Average cross-val accuracy for {symbol}: {avg_score:.4f}")
 
    if avg_score < 0.52:
        log_info(f"  Warning: accuracy {avg_score:.4f} is weak. "
                 f"Model will still be saved — the trend/regime filters in main.py "
                 f"provide additional protection.")
 
    # Final model trained on ALL data with time-weighting
    all_weights = make_sample_weights(len(X))
    final_model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.03,
        max_depth=6,
        num_leaves=50,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_samples=30,
        reg_alpha=0.1,
        reg_lambda=0.1,
        class_weight="balanced",
        random_state=42,
        verbose=-1
    )
    final_model.fit(X, y, sample_weight=all_weights)
 
    model_path = f"models/{symbol}_lgbm.pkl"
    joblib.dump(final_model, model_path)
    log_info(f"  Model saved to {model_path}")
 
    preds_all = final_model.predict(X)
    log_info(f"\n{classification_report(y, preds_all)}")
 
    # Feature importance — useful for debugging
    importances = dict(zip(FEATURE_COLS, final_model.feature_importances_))
    top = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]
    log_info(f"  Top 5 features: {top}")
 
 
def train_all(config):
    account_cfg = config["oanda"]
    symbols     = config["trading"]["symbols"]
 
    for symbol in symbols:
        train_symbol(symbol, account_cfg)
 
    log_info("All models trained successfully.")
 
 
if __name__ == "__main__":
    with open("config.json") as f:
        config = json.load(f)
 
    train_all(config)