"""
backtest.py
-----------
Simple backtesting script using the trained LightGBM model.
Run this BEFORE going live to see how the strategy performs historically.

Usage: python backtest.py
"""

import json
import joblib
import os
import pandas as pd
import numpy as np
from data_feed import get_candles
from features import compute_features, FEATURE_COLS
from logger import log_info, log_error


def run_backtest(symbol, model, account_cfg, initial_capital=100000, max_risk_pct=0.02):
    log_info(f"\n{'='*50}")
    log_info(f"Backtesting {symbol}...")

    df = get_candles(account_cfg, symbol, timeframe="M5", count=5000)
    if df is None or len(df) < 100:
        log_error(f"Not enough data for {symbol}")
        return

    df = compute_features(df)

    # Generate signals
    X = df[FEATURE_COLS]
    df["signal"] = model.predict(X)
    df["confidence"] = model.predict_proba(X).max(axis=1)

    # Only act on high-confidence signals
    df["active_signal"] = np.where(df["confidence"] >= 0.55, df["signal"], np.nan)

    # Simulate returns
    df["next_return"] = df["Close"].shift(-1) / df["Close"] - 1
    df["trade_return"] = np.where(
        df["active_signal"] == 1, df["next_return"],       # long
        np.where(df["active_signal"] == 0, -df["next_return"], 0)  # short
    )

    # Apply simple 2% risk per trade (position sizing approximation)
    df["equity"] = initial_capital
    equity = initial_capital
    equity_history = []
    peak = initial_capital
    max_dd = 0

    for i, row in df.iterrows():
        ret = row["trade_return"]
        if ret != 0:
            trade_pnl = equity * max_risk_pct * (ret / (df["atr"].mean() * 1.5))
            equity += trade_pnl
        equity_history.append(equity)

        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    df["equity_curve"] = equity_history
    total_return = (equity - initial_capital) / initial_capital * 100
    total_trades = int(df["active_signal"].notna().sum())
    win_rate = float((df.loc[df["active_signal"].notna(), "trade_return"] > 0).mean() * 100)

    log_info(f"Results for {symbol}:")
    log_info(f"  Total trades:   {total_trades}")
    log_info(f"  Win rate:       {win_rate:.1f}%")
    log_info(f"  Total return:   {total_return:.2f}%")
    log_info(f"  Max drawdown:   {max_dd:.2%}")
    log_info(f"  Final equity:   ${equity:,.2f}")

    return {
        "symbol": symbol,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "total_return": total_return,
        "max_drawdown": max_dd,
        "final_equity": equity
    }


if __name__ == "__main__":
    with open("config.json") as f:
        config = json.load(f)

    account_cfg = config["oanda"]
    symbols = config["trading"]["symbols"]
    results = []

    for symbol in symbols:
        model_path = f"models/{symbol}_lgbm.pkl"
        if os.path.exists(model_path):
            model = joblib.load(model_path)
            result = run_backtest(symbol, model, account_cfg)
            if result:
                results.append(result)
        else:
            log_error(f"No model found for {symbol}. Run model_training.py first.")

    log_info("\n" + "="*50)
    log_info("BACKTEST SUMMARY")
    log_info("="*50)
    for r in results:
        log_info(f"{r['symbol']}: Return={r['total_return']:.2f}% | WinRate={r['win_rate']:.1f}% | MaxDD={r['max_drawdown']:.2%}")
