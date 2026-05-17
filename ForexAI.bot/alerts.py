"""
alerts.py
---------
Telegram alert system for ForexAI Bot.
Sends notifications for every meaningful event:
- Trade entry (with SL and TP)
- Stop loss moved to breakeven
- Stop loss trailed (with new level)
- Take profit hit
- Stop loss hit
- Drawdown warning
- Bot startup/halt/error
"""

import requests
from logger import log_warning
from datetime import datetime, timezone


def send_telegram(bot_token, chat_id, message):
    """Send a message via Telegram bot."""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        # Try with Markdown first
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        resp = requests.post(url, json=payload, timeout=5)
        # If Markdown fails (special chars in news headlines etc), retry as plain text
        if resp.status_code != 200:
            payload_plain = {
                "chat_id": chat_id,
                "text": message.replace("*", "").replace("`", "").replace("_", "")
            }
            resp2 = requests.post(url, json=payload_plain, timeout=5)
            if resp2.status_code != 200:
                log_warning(f"Telegram alert failed: {resp2.text}")
    except Exception as e:
        log_warning(f"Telegram error: {e}")


class Alerts:
    def __init__(self, telegram_cfg):
        self.enabled = telegram_cfg.get("enabled", False)
        self.token = telegram_cfg.get("BOT_TOKEN", "")
        # Support single CHAT_ID or list via CHAT_IDS
        raw = telegram_cfg.get("CHAT_IDS", telegram_cfg.get("CHAT_ID", ""))
        if isinstance(raw, list):
            self.chat_ids = [str(c) for c in raw]
        else:
            self.chat_ids = [str(raw)] if raw else []

    def notify(self, message):
        if self.enabled and self.token:
            for chat_id in self.chat_ids:
                send_telegram(self.token, chat_id, message)

    def _time(self):
        return datetime.now(timezone.utc).strftime("%H:%M UTC")

    def trade_entry_alert(self, action, symbol, units, price, sl, tp, confidence):
        """Sent when a new trade is opened."""
        emoji = "🟢" if action == "BUY" else "🔴"
        direction = "📈" if action == "BUY" else "📉"
        msg = (
            f"{emoji} *NEW TRADE OPENED* {direction}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Symbol: `{symbol}`\n"
            f"📌 Direction: *{action}*\n"
            f"💰 Entry: `{price}`\n"
            f"🛑 Stop Loss: `{sl}`\n"
            f"🎯 Take Profit: `{tp}`\n"
            f"📦 Units: `{units}`\n"
            f"🧠 Confidence: `{confidence:.1%}`\n"
            f"🕐 Time: `{self._time()}`"
        )
        self.notify(msg)

    def breakeven_alert(self, symbol, old_sl, new_sl):
        """Sent when SL is moved to breakeven."""
        msg = (
            f"🔒 *STOP MOVED TO BREAKEVEN*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Symbol: `{symbol}`\n"
            f"🛑 Old SL: `{old_sl}`\n"
            f"✅ New SL: `{new_sl}` *(breakeven)*\n"
            f"💡 Worst case is now ~zero loss\n"
            f"🕐 Time: `{self._time()}`"
        )
        self.notify(msg)

    def trail_alert(self, symbol, old_sl, new_sl, locked_profit):
        """Sent when SL is trailed to lock in profit."""
        msg = (
            f"📈 *STOP TRAILED — PROFIT LOCKED*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Symbol: `{symbol}`\n"
            f"🛑 Old SL: `{old_sl}`\n"
            f"✅ New SL: `{new_sl}`\n"
            f"💰 Minimum profit locked: `${locked_profit:.2f}`\n"
            f"🕐 Time: `{self._time()}`"
        )
        self.notify(msg)

    def take_profit_alert(self, symbol, units, entry_price, close_price, profit):
        """Sent when TP is hit."""
        msg = (
            f"🎯 *TAKE PROFIT HIT* 💰\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Symbol: `{symbol}`\n"
            f"📌 Entry: `{entry_price}`\n"
            f"✅ Closed: `{close_price}`\n"
            f"📦 Units: `{units}`\n"
            f"💵 Profit: *+${profit:.2f}*\n"
            f"🕐 Time: `{self._time()}`"
        )
        self.notify(msg)

    def stop_loss_alert(self, symbol, units, entry_price, close_price, loss):
        """Sent when SL is hit."""
        msg = (
            f"🛑 *STOP LOSS HIT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Symbol: `{symbol}`\n"
            f"📌 Entry: `{entry_price}`\n"
            f"❌ Closed: `{close_price}`\n"
            f"📦 Units: `{units}`\n"
            f"💸 Loss: *-${abs(loss):.2f}*\n"
            f"🕐 Time: `{self._time()}`"
        )
        self.notify(msg)

    def signal_close_alert(self, symbol, units, entry_price, close_price, pnl):
        """Sent when trade is closed due to signal reversal."""
        emoji = "✅" if pnl >= 0 else "❌"
        direction = "profit" if pnl >= 0 else "loss"
        msg = (
            f"{emoji} *TRADE CLOSED — SIGNAL REVERSED*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Symbol: `{symbol}`\n"
            f"📌 Entry: `{entry_price}`\n"
            f"🔄 Closed: `{close_price}`\n"
            f"📦 Units: `{units}`\n"
            f"💰 P&L: `{'+'if pnl>=0 else ''}{pnl:.2f}` ({direction})\n"
            f"🕐 Time: `{self._time()}`"
        )
        self.notify(msg)

    def trade_alert(self, action, symbol, units, price):
        emoji = "🟢" if action == "BUY" else "🔴"
        msg = f"{emoji} *{action}* | `{symbol}`\nUnits: {units} | Price: `{price}`"
        self.notify(msg)

    def halt_alert(self, reason):
        msg = f"⚠️ *Trading Halted*\nReason: {reason}\n🕐 `{self._time()}`"
        self.notify(msg)

    def drawdown_alert(self, drawdown_pct):
        msg = (
            f"🚨 *MAX DRAWDOWN REACHED*\n"
            f"Drawdown: `{drawdown_pct:.2%}`\n"
            f"Bot paused to protect capital.\n"
            f"🕐 `{self._time()}`"
        )
        self.notify(msg)

    def startup_alert(self, symbols):
        msg = (
            f"🤖 *JJGoldBot Started* ✅\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Symbols: `{', '.join(symbols)}`\n"
            f"🕐 `{self._time()}`"
        )
        self.notify(msg)

    def error_alert(self, error_msg):
        msg = f"❌ *Bot Error*\n`{error_msg}`\n🕐 `{self._time()}`"
        self.notify(msg)