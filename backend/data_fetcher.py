import pandas as pd
import requests
from config import BASE_DATA_URL, HEADERS, logger

def fetch_alpaca_market_data(symbol: str = "SPY"):
    """
    Fetches 5-min historical bars for TA calculation AND the live sub-second trade tick.
    Stitches them together to bypass retail Bid/Ask spread issues.
    """
    logger.info(f"Initiating Alpaca data fetch for symbol: {symbol}")

    # 1. Fetch the last 500 5-Minute Bars (Provides OHLCV for Indicators)
    bars_url = f"{BASE_DATA_URL}/{symbol}/bars?timeframe=5Min&limit=500"
    logger.info(f"Requesting historical bars from: {bars_url}")
    try:
        bars_res = requests.get(bars_url, headers=HEADERS, timeout=10)
        logger.info(f"Alpaca Bars API responded with status code: {bars_res.status_code}")

        if bars_res.status_code != 200:
            logger.error(f"Alpaca Bars API Error: Status {bars_res.status_code} - Response: {bars_res.text}")
            return None, None

        bars_data = bars_res.json().get('bars', [])
        logger.info(f"Successfully retrieved {len(bars_data)} bars from Alpaca.")
        if not bars_data:
            logger.warning("Retrieved bars list is empty!")
            return None, None

    except Exception as e:
        logger.exception("Failed to establish connection to Alpaca Bars API")
        return None, None

    # Convert Alpaca JSON into a Pandas DataFrame
    df = pd.DataFrame(bars_data)
    # Map Alpaca's shorthand keys to Pandas-TA standard column names
    df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume', 'vw': 'VWAP', 't': 'Date'},
              inplace=True)
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)

    # 2. Fetch the absolute Latest Trade for sub-second accuracy
    trade_url = f"{BASE_DATA_URL}/{symbol}/trades/latest"
    logger.info(f"Requesting latest live trade from: {trade_url}")

    live_price = df['Close'].iloc[-1]  # Fallback to last bar close
    logger.info(f"Defaulting live price to last bar close: {live_price}")

    try:
        trade_res = requests.get(trade_url, headers=HEADERS, timeout=5)
        logger.info(f"Trades API responded with status code: {trade_res.status_code}")
        if trade_res.status_code == 200:
            trade_data = trade_res.json()
            if 'trade' in trade_data and 'p' in trade_data['trade']:
                live_price = trade_data['trade']['p']
                logger.info(f"Successfully retrieved latest trade tick: ${live_price}")
            else:
                logger.warning(f"Unexpected trade response structure: {trade_data}")
        else:
            logger.error(f"Alpaca Trades API Error: Status {trade_res.status_code} - Response: {trade_res.text}")
    except Exception as e:
        logger.error(f"Failed to fetch latest trade tick due to error: {e}. Falling back to last bar close.")

    # 3. The Stitch: Override the incomplete current bar's close with the live exact tick
    df.iloc[-1, df.columns.get_loc('Close')] = live_price
    logger.info(f"Stitched live price ${live_price} into the last DataFrame candle close.")

    # Update High/Low of the current bar just in case the live tick breached them
    high_before = df.iloc[-1]['High']
    low_before = df.iloc[-1]['Low']
    if live_price > high_before:
        df.iloc[-1, df.columns.get_loc('High')] = live_price
        logger.info(f"Live price breached candle high. Updated High from {high_before} to {live_price}")
    if live_price < low_before:
        df.iloc[-1, df.columns.get_loc('Low')] = live_price
        logger.info(f"Live price breached candle low. Updated Low from {low_before} to {live_price}")

    return df, live_price