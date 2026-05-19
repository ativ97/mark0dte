import logging
import os
import sys

# --- LOGGING CONFIGURATION ---
def setup_logging():
    """
    Sets up a clean, structured logging framework.
    Console: Clean, high-level (INFO/WARNING/ERROR)
    File: Detailed, context-rich (DEBUG/INFO/WARNING/ERROR)
    """
    # Create the root logger
    logger = logging.getLogger("0DTE-QuantEngine")
    
    # Avoid duplicate logs if setup_logging is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # Base logging level
    logger.setLevel(logging.DEBUG)

    # 1. Console Handler - Clean format, no clutter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_format)

    # 2. File Handler - Detailed audit trail
    # Ensure logs directory exists
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    file_handler = logging.FileHandler(os.path.join(log_dir, "engine_audit.log"))
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | [%(filename)s:%(lineno)d] | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_format)

    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

# Initialize logger
logger = setup_logging()

# --- API & DATA CONFIGURATION ---
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "PKE7TTHDCYW4PFXYPHDIHUKYJ6")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "5ytWV4AYCRGqpLSQthwM1bjhvfMPePz94raPK1Q3hGu2")

if ALPACA_API_KEY == "PKE7TTHDCYW4PFXYPHDIHUKYJ6" or ALPACA_SECRET_KEY == "5ytWV4AYCRGqpLSQthwM1bjhvfMPePz94raPK1Q3hGu2":
    logger.warning("Using default Alpaca API keys. Please set environment variables for production.")

BASE_DATA_URL = "https://data.alpaca.markets/v2/stocks"

HEADERS = {
    "Apca-Api-Key-Id": ALPACA_API_KEY,
    "Apca-Api-Secret-Key": ALPACA_SECRET_KEY,
    "Accept": "application/json"
}

# --- MARKET REGIME THRESHOLDS ---
# These can be tuned without changing the engine logic
CHOP_THRESHOLD = 61.8
EFFICIENCY_RATIO_THRESHOLD = 0.20
RSI_DEAD_ZONE_LOWER = 45
RSI_DEAD_ZONE_UPPER = 55
EMA_COMPRESSION_THRESHOLD_PCT = 0.001  # 0.1% of price
VWAP_ELASTICITY_THRESHOLD_PCT = 0.35
