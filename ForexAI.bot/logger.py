import logging
import os
from datetime import datetime

# Create logs directory
os.makedirs("logs", exist_ok=True)

log_filename = f"logs/bot_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()  # also prints to terminal
    ]
)

logger = logging.getLogger("ForexAIBot")

def log_info(msg):
    logger.info(msg)

def log_warning(msg):
    logger.warning(msg)

def log_error(msg):
    logger.error(msg)

def log_trade(action, symbol, units, price, reason=""):
    msg = f"TRADE | {action} | {symbol} | Units: {units} | Price: {price}"
    if reason:
        msg += f" | Reason: {reason}"
    logger.info(msg)
