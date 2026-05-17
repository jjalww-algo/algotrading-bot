"""
trade_logger.py
---------------
Writes every trade to trade_log.csv — clean, no OANDA noise.
 
One row per trade. Columns:
  date, time, symbol, side, units, entry_price, exit_price,
  pnl_sgd, regime, h1_trend, confidence, rule_blocked, status
 
Also writes a weekly summary to trade_summary.txt every time
print_summary() is called (bot does this on CTRL+C or weekly reset).
 
HOW TO READ THE FILES:
  trade_log.csv     — open in Excel, one row per trade
  trade_summary.txt — plain text weekly report
 
STATUS VALUES:
  OPEN    — trade placed, not yet closed
  WIN     — closed with profit
  LOSS    — closed with loss
  BLOCKED — rule prevented entry (no trade placed)
  CLOSED  — closed flat (breakeven or forced close)
"""
 
import csv
import os
from datetime import datetime, timezone, timedelta
from logger import log_info, log_error
 
LOG_FILE     = "trade_log.csv"
SUMMARY_FILE = "trade_summary.txt"
 
HEADERS = [
    "date", "time_utc", "symbol", "side", "units",
    "entry_price", "exit_price", "pnl_sgd",
    "regime", "h1_trend", "confidence",
    "rule_blocked", "status"
]
 
 
def _ensure_file():
    """Create CSV with headers if it doesn't exist yet."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writeheader()
        log_info(f"Created {LOG_FILE}")
 
 
def log_trade_open(symbol, side, units, entry_price,
                   regime="", h1_trend="", confidence=0.0):
    """
    Call this when a trade is successfully placed.
    Returns a row_id (timestamp string) used to update the row on close.
    """
    _ensure_file()
    now = datetime.now(timezone.utc)
    row_id = now.strftime("%Y%m%d_%H%M%S") + f"_{symbol}"
 
    row = {
        "date":        now.strftime("%Y-%m-%d"),
        "time_utc":    now.strftime("%H:%M:%S"),
        "symbol":      symbol,
        "side":        side.upper(),
        "units":       units,
        "entry_price": round(entry_price, 5),
        "exit_price":  "",
        "pnl_sgd":     "",
        "regime":      regime,
        "h1_trend":    h1_trend,
        "confidence":  f"{confidence:.2%}",
        "rule_blocked":"",
        "status":      "OPEN",
    }
 
    with open(LOG_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=HEADERS).writerow(row)
 
    log_info(f"Trade logged [OPEN]: {side.upper()} {symbol} @ {entry_price}")
    return row_id
 
 
def log_trade_close(symbol, exit_price, pnl_sgd):
    """
    Call this when a trade closes.
    Finds the most recent OPEN row for this symbol and updates it.
    """
    _ensure_file()
    rows = []
    updated = False
 
    with open(LOG_FILE, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (not updated and
                    row["symbol"] == symbol and
                    row["status"] == "OPEN"):
                row["exit_price"] = round(exit_price, 5)
                row["pnl_sgd"]    = round(pnl_sgd, 2)
                row["status"]     = "WIN" if pnl_sgd > 0 else ("LOSS" if pnl_sgd < 0 else "CLOSED")
                updated = True
            rows.append(row)
 
    if updated:
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        log_info(f"Trade logged [CLOSE]: {symbol} pnl=${pnl_sgd:+.2f}")
    else:
        log_info(f"No open trade found to close for {symbol}")
 
 
def log_rule_block(symbol, rule_reason, regime="", confidence=0.0):
    """
    Call this when a rule blocks a trade entry.
    Lets you see which rules are actually firing.
    """
    _ensure_file()
    now = datetime.now(timezone.utc)
 
    row = {
        "date":        now.strftime("%Y-%m-%d"),
        "time_utc":    now.strftime("%H:%M:%S"),
        "symbol":      symbol,
        "side":        "BLOCKED",
        "units":       "",
        "entry_price": "",
        "exit_price":  "",
        "pnl_sgd":     "",
        "regime":      regime,
        "h1_trend":    "",
        "confidence":  f"{confidence:.2%}" if confidence else "",
        "rule_blocked": rule_reason,
        "status":      "BLOCKED",
    }
 
    with open(LOG_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=HEADERS).writerow(row)
 
 
def print_summary(days=7):
    """
    Print a clean weekly summary to trade_summary.txt and to console.
    Called on CTRL+C or manual request.
    """
    _ensure_file()
 
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows   = []
 
    try:
        with open(LOG_FILE, "r", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    row_date = datetime.strptime(
                        row["date"] + " " + row["time_utc"],
                        "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                    if row_date >= cutoff:
                        rows.append(row)
                except (ValueError, KeyError):
                    continue
    except FileNotFoundError:
        log_error("trade_log.csv not found — no summary to generate")
        return
 
    # Separate real trades from blocks
    trades = [r for r in rows if r["status"] in ("WIN", "LOSS", "CLOSED", "OPEN")]
    blocks = [r for r in rows if r["status"] == "BLOCKED"]
    closed = [r for r in trades if r["status"] in ("WIN", "LOSS", "CLOSED")]
    wins   = [r for r in trades if r["status"] == "WIN"]
    losses = [r for r in trades if r["status"] == "LOSS"]
 
    def safe_float(val):
        try: return float(val)
        except: return 0.0
 
    total_pnl   = sum(safe_float(r["pnl_sgd"]) for r in closed)
    avg_win     = (sum(safe_float(r["pnl_sgd"]) for r in wins)   / len(wins)   if wins   else 0)
    avg_loss    = (sum(safe_float(r["pnl_sgd"]) for r in losses) / len(losses) if losses else 0)
    win_rate    = len(wins) / len(closed) * 100 if closed else 0
    best_trade  = max((safe_float(r["pnl_sgd"]) for r in closed), default=0)
    worst_trade = min((safe_float(r["pnl_sgd"]) for r in closed), default=0)
 
    # Per symbol breakdown
    symbols = sorted(set(r["symbol"] for r in trades))
    sym_lines = []
    for sym in symbols:
        st = [r for r in closed if r["symbol"] == sym]
        sw = [r for r in st if r["status"] == "WIN"]
        sym_pnl = sum(safe_float(r["pnl_sgd"]) for r in st)
        sym_wr  = len(sw) / len(st) * 100 if st else 0
        sym_lines.append(
            f"  {sym:<12} {len(st):>3} trades  "
            f"{len(sw):>2}W / {len(st)-len(sw):>2}L  "
            f"({sym_wr:>5.1f}% WR)  "
            f"P&L: SGD {sym_pnl:>+8.2f}"
        )
 
    # Rule block breakdown
    block_counts = {}
    for b in blocks:
        reason = b["rule_blocked"] or "unknown"
        block_counts[reason] = block_counts.get(reason, 0) + 1
 
    block_lines = [f"  {v:>3}x  {k}" for k, v in
                   sorted(block_counts.items(), key=lambda x: -x[1])]
 
    # Regime breakdown
    regime_counts = {}
    for r in closed:
        reg = r.get("regime") or "unknown"
        regime_counts[reg] = regime_counts.get(reg, 0) + 1
 
    regime_lines = [f"  {k:<12} {v} trades"
                    for k, v in sorted(regime_counts.items())]
 
    # Daily P&L
    daily = {}
    for r in closed:
        d = r["date"]
        daily[d] = daily.get(d, 0) + safe_float(r["pnl_sgd"])
    daily_lines = [
        f"  {d}   SGD {pnl:>+8.2f}  {'▲' if pnl >= 0 else '▼'}"
        for d, pnl in sorted(daily.items())
    ]
 
    lines = [
        "=" * 55,
        f"  FOREXAI BOT — {days}-DAY TRADE SUMMARY",
        f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 55,
        "",
        "OVERVIEW",
        f"  Total trades placed : {len(trades)}",
        f"  Closed trades       : {len(closed)}",
        f"  Open trades         : {len(trades) - len(closed)}",
        f"  Win rate            : {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)",
        f"  Total P&L           : SGD {total_pnl:+.2f}",
        f"  Avg win             : SGD {avg_win:+.2f}",
        f"  Avg loss            : SGD {avg_loss:+.2f}",
        f"  Best trade          : SGD {best_trade:+.2f}",
        f"  Worst trade         : SGD {worst_trade:+.2f}",
        "",
        "BY SYMBOL",
        *sym_lines,
        "",
        "DAILY P&L",
        *daily_lines,
        "",
        "REGIME BREAKDOWN",
        *regime_lines,
        "",
        f"RULES BLOCKED ({len(blocks)} total entries prevented)",
        *(block_lines if block_lines else ["  No blocks recorded"]),
        "",
        "=" * 55,
    ]
 
    summary_text = "\n".join(lines)
    print(summary_text)
 
    try:
        with open(SUMMARY_FILE, "w") as f:
            f.write(summary_text)
        log_info(f"Summary written to {SUMMARY_FILE}")
    except Exception as e:
        log_error(f"Could not write summary file: {e}")