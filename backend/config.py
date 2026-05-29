import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the backend directory
load_dotenv(Path(__file__).resolve().parent / ".env")

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
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
    logger.error("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in backend/.env")
    raise SystemExit("Missing Alpaca API credentials. Create backend/.env with ALPACA_API_KEY and ALPACA_SECRET_KEY.")

# --- THETADATA OPTIONS API ---
THETA_EMAIL = os.getenv("THETA_EMAIL")
THETA_PASSWORD = os.getenv("THETA_PASSWORD")
if not THETA_EMAIL or not THETA_PASSWORD:
    logger.warning("THETA_EMAIL/THETA_PASSWORD not set in .env — GEX data will be unavailable")

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

# --- SPX PROXY ---
# Alpaca does not provide SPX index data. We derive SPX from SPY * multiplier.
# The true ratio drifts due to dividends/expense ratio. Calibrate periodically.
# As of 2026-05: SPX ~5900, SPY ~590 => multiplier ~10.0
SPX_PROXY_MULTIPLIER = 10.0

# --- POSITION RISK BOUNDARIES (SPX Points) ---
GAMMA_TRAP_THRESHOLD = 10    # Mandatory eject zone
WARNING_ZONE_THRESHOLD = 25  # Volatility expansion warning
SAFE_ZONE_THRESHOLD = 25     # Above this = theta decay safe
MOAT_BAR_SCALE = 80          # Points range for the UI progress bar (0-100%)

# --- RECOMMENDED MINIMUM MOAT PER REGIME ---
# Positions with moat above WARNING but below these values get a CAUTION flag
STATE_A_MIN_MOAT = 35   # Clean trend: tighter moats acceptable
STATE_B_MIN_MOAT = 50   # Moderate chop: wider buffer needed
STATE_C_MIN_MOAT = 70   # High entropy: maximum distance required

# --- TIME-DELAYED VERIFICATION ---
BREACH_VERIFICATION_MINUTES = 5  # Minutes condition must persist before kill switch

# --- TIME PRESSURE (0DTE Gamma Acceleration) ---
MARKET_CLOSE_HOUR_ET = 16       # 4:00 PM Eastern
GAMMA_ACCELERATION_HOUR_ET = 14  # 2:00 PM Eastern — gamma ramp begins
FINAL_HOUR_MOAT_MULTIPLIER = 1.5 # In final 2 hours, recommended moat is multiplied by this

# --- SPREAD WIDTH ---
SPREAD_WIDTH_SPX = 5.0  # Always $5 wide SPX spreads

# --- POSITION SIZING GUARDRAIL (P0-3; % of account, 2-tier; revised 2026-05-29) ---
# Max loss on a $5-wide credit spread = (width - credit) * 100 * contracts.
# Tiers are a % of ACCOUNT_SIZE so they scale as the account grows.
# >>> CONFIRM ACCOUNT_SIZE + the two % to your real numbers (placeholders below). <<<
ACCOUNT_SIZE = 15000.0            # USD (Ativ, 2026-05-29)
MAX_RISK_WARN_PCT = 0.25          # amber INFORMATIONAL notice: single-trade max loss above this % of account
MAX_RISK_PER_TRADE_PCT = 0.50     # reference line only
SIZING_HARD_BLOCK = False         # Ativ choice 2026-05-29: guardrail is INFORMATIONAL — never hard-block / never label "over limit"
MAX_RISK_WARN = ACCOUNT_SIZE * MAX_RISK_WARN_PCT            # = $3,750 (amber notice)
MAX_RISK_PER_TRADE = ACCOUNT_SIZE * MAX_RISK_PER_TRADE_PCT  # = $7,500 (reference only)
MAX_RISK_PER_DAY_PCT = 0.30       # suggested daily stop (cumulative realized loss); guidance only, not enforced

# --- VALID POSITION TYPES ---
VALID_POSITION_TYPES = ["Put Spread", "Call Spread", "Iron Condor"]
