from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas_ta as ta
import pandas as pd
import requests
import uvicorn
from pydantic import BaseModel
import datetime

app = FastAPI(title="0DTE Quant Engine V2.0")

# Allow React frontend to communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ALPACA API CONFIGURATION ---
ALPACA_API_KEY = "PKE7TTHDCYW4PFXYPHDIHUKYJ6"
ALPACA_SECRET_KEY = "5ytWV4AYCRGqpLSQthwM1bjhvfMPePz94raPK1Q3hGu2"
BASE_DATA_URL = "https://data.alpaca.markets/v2/stocks"

HEADERS = {
    "Apca-Api-Key-Id": ALPACA_API_KEY,
    "Apca-Api-Secret-Key": ALPACA_SECRET_KEY,
    "Accept": "application/json"
}


class TelemetryResponse(BaseModel):
    symbol: str
    current_price: float
    ema_9: float
    ema_21: float
    rsi_14: float
    chop_value: float
    er_value: float
    vwap_dev: float
    regime_state: str
    regime_score: int
    recommended_moat: str
    stop_loss_rule: str
    timestamp: str


def fetch_alpaca_market_data(symbol: str = "SPY"):
    """
    Fetches 5-min historical bars for TA calculation AND the live sub-second trade tick.
    Stitches them together to bypass retail Bid/Ask spread issues.
    """
    # 1. Fetch the last 500 5-Minute Bars (Provides OHLCV for Indicators)
    bars_url = f"{BASE_DATA_URL}/{symbol}/bars?timeframe=5Min&limit=500"
    bars_res = requests.get(bars_url, headers=HEADERS)

    if bars_res.status_code != 200:
        print(f"Alpaca API Error (Bars): {bars_res.text}")
        return None, None

    bars_data = bars_res.json().get('bars', [])
    if not bars_data:
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
    trade_res = requests.get(trade_url, headers=HEADERS)

    live_price = df['Close'].iloc[-1]  # Fallback to last bar close
    if trade_res.status_code == 200:
        trade_data = trade_res.json()
        if 'trade' in trade_data and 'p' in trade_data['trade']:
            live_price = trade_data['trade']['p']

    # 3. The Stitch: Override the incomplete current bar's close with the live exact tick
    df.iloc[-1, df.columns.get_loc('Close')] = live_price

    # Update High/Low of the current bar just in case the live tick breached them
    if live_price > df.iloc[-1]['High']:
        df.iloc[-1, df.columns.get_loc('High')] = live_price
    if live_price < df.iloc[-1]['Low']:
        df.iloc[-1, df.columns.get_loc('Low')] = live_price

    return df, live_price


def analyze_market_regime(df: pd.DataFrame) -> dict:
    latest = df.iloc[-1]

    ema_9 = latest['EMA_9']
    ema_21 = latest['EMA_21']
    rsi = latest['RSI_14']

    chop_col = next((col for col in latest.index if 'CHOP' in col), None)
    er_col = next((col for col in latest.index if 'ER' in col), None)
    chop = latest[chop_col] if chop_col else 50.0
    er = latest[er_col] if er_col else 0.5

    vwap_col = next((col for col in latest.index if 'VWAP' in col), None)
    vwap_val = latest[vwap_col] if vwap_col else latest['Close']
    vwap_deviation_pct = (abs(latest['Close'] - vwap_val) / vwap_val) * 100

    regime_score = 0

    if chop > 61.8: regime_score += 1
    if er < 0.20: regime_score += 1
    if 45 <= rsi <= 55: regime_score += 1

    ema_diff = abs(ema_9 - ema_21)
    if ema_diff < (latest['Close'] * 0.001):
        regime_score += 1

    if regime_score <= 1:
        state = "STATE A: TRENDING"
        moat = "35-40 Points"
        stop = "Strict 200% Premium Hit"
    elif regime_score == 2:
        state = "STATE B: MODERATE CHOP"
        moat = "50-60 Points"
        stop = "250% Premium OR 15-pt Asset Breach"
    else:
        state = "STATE C: HIGH ENTROPY / WHIPSAW"
        moat = "70+ Points"
        stop = "Strict Asset Boundary ONLY (Ignore premium spikes)"

    if vwap_deviation_pct > 0.35:
        state = state + " [OVERRIDE: MAX ELASTICITY]"
        stop = "SUSPEND STOPS. Wait 10 mins for Mean Reversion Bounce, then Eject."

    return {
        "regime_state": state,
        "regime_score": regime_score,
        "recommended_moat": moat,
        "stop_loss_rule": stop,
        "chop_value": round(chop, 2),
        "er_value": round(er, 2),
        "vwap_dev": round(vwap_deviation_pct, 3)
    }


@app.get("/api/telemetry", response_model=TelemetryResponse)
def get_telemetry():
    # Call the new Alpaca integration
    df, live_price = fetch_alpaca_market_data("SPY")

    if df is None or df.empty:
        return {"error": "Failed to fetch data from Alpaca API."}

    # Calculate Standard Indicators
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.rsi(length=14, append=True)

    # Calculate Advanced Regime Indicators
    df.ta.chop(length=14, append=True)
    df.ta.er(length=10, append=True)

    # Note: VWAP is usually provided by Alpaca directly, but we can recalculate it
    df.ta.vwap(append=True)

    df.dropna(inplace=True)
    latest_data = df.iloc[-1]

    regime_data = analyze_market_regime(df)

    return TelemetryResponse(
        symbol="SPY (SPX Proxy) [Alpaca V2]",
        current_price=round(live_price, 2),
        ema_9=round(latest_data['EMA_9'], 2),
        ema_21=round(latest_data['EMA_21'], 2),
        rsi_14=round(latest_data['RSI_14'], 2),
        chop_value=regime_data["chop_value"],
        er_value=regime_data["er_value"],
        vwap_dev=regime_data["vwap_dev"],
        regime_state=regime_data["regime_state"],
        regime_score=regime_data["regime_score"],
        recommended_moat=regime_data["recommended_moat"],
        stop_loss_rule=regime_data["stop_loss_rule"],
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S CDT")
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)