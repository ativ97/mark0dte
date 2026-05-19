from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import uvicorn
from pydantic import BaseModel
import datetime

app = FastAPI(title="0DTE Quant Engine")

# Allow React frontend to communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TelemetryResponse(BaseModel):
    symbol: str
    current_price: float
    ema_9: float
    ema_21: float
    rsi_14: float
    chop_value: float
    er_value: float
    vwap_dev: float  # NEW: VWAP Deviation Percentage
    regime_state: str
    regime_score: int
    recommended_moat: str
    stop_loss_rule: str
    timestamp: str


def analyze_market_regime(df: pd.DataFrame) -> dict:
    """
    Analyzes the latest dataframe row to determine the market state
    using a Multi-Factor Ensemble Voting Classifier + VWAP Elasticity Override.
    """
    latest = df.iloc[-1]

    # Extract standard values
    ema_9 = latest['EMA_9']
    ema_21 = latest['EMA_21']
    rsi = latest['RSI_14']

    # Dynamically find CHOP and ER columns to prevent silent defaults
    chop_col = next((col for col in latest.index if 'CHOP' in col), None)
    er_col = next((col for col in latest.index if 'ER' in col), None)
    chop = latest[chop_col] if chop_col else 50.0
    er = latest[er_col] if er_col else 0.5

    # Extract VWAP and calculate the deviation elasticity
    vwap_col = next((col for col in latest.index if 'VWAP' in col), None)
    vwap_val = latest[vwap_col] if vwap_col else latest['Close']
    vwap_deviation_pct = (abs(latest['Close'] - vwap_val) / vwap_val) * 100

    # --- Ensemble Voting Logic (The Quant Brain) ---
    regime_score = 0

    # Rule 1: Choppiness Index > 61.8 (Fibonacci threshold for High Chop)
    if chop > 61.8:
        regime_score += 1

    # Rule 2: Kaufman's Efficiency Ratio < 0.20 (Highly inefficient price action)
    if er < 0.20:
        regime_score += 1

    # Rule 3: RSI "Dead Zone" Exhaustion (45-55)
    if 45 <= rsi <= 55:
        regime_score += 1

    # Rule 4: Moving Average Braiding (EMAs are tightly compressed)
    ema_diff = abs(ema_9 - ema_21)
    if ema_diff < (latest['Close'] * 0.001):
        regime_score += 1

    # --- Baseline State Classification based on Score ---
    if regime_score <= 1:
        state = "STATE A: TRENDING"
        moat = "35-40 Points"
        stop = "Strict 200% Premium Hit"
    elif regime_score == 2:
        state = "STATE B: MODERATE CHOP"
        moat = "50-60 Points"
        stop = "250% Premium OR 15-pt Asset Breach"
    else:  # Score 3 or 4
        state = "STATE C: HIGH ENTROPY / WHIPSAW"
        moat = "70+ Points"
        stop = "Strict Asset Boundary ONLY (Ignore premium spikes)"

    # --- THE RUBBER BAND OVERRIDE (System V1.2) ---
    # If the asset stretches more than 0.35% from VWAP, it is a high-probability reversal zone.
    # Institutional algos will likely buy/sell it back to the mean.
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
    """
    Fetches live/delayed 5-minute SPY data, calculates TA, and returns the actionable regime.
    """
    # Fetch 5-minute data for the last 5 days
    ticker = yf.Ticker("SPY")
    df = ticker.history(period="5d", interval="5m")

    if df.empty:
        return {"error": "No data returned from yfinance."}

    # Calculate Standard Indicators
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.rsi(length=14, append=True)

    # Calculate Advanced Regime Indicators
    df.ta.chop(length=14, append=True)
    df.ta.er(length=10, append=True)

    # Calculate Institutional VWAP
    df.ta.vwap(append=True)

    # Drop NaNs created by lookback periods
    df.dropna(inplace=True)

    # Get the most recent completed row
    latest_data = df.iloc[-1]

    # Run the regime classification
    regime_data = analyze_market_regime(df)

    return TelemetryResponse(
        symbol="SPY (SPX Proxy)",
        current_price=round(latest_data['Close'], 2),
        ema_9=round(latest_data['EMA_9'], 2),
        ema_21=round(latest_data['EMA_21'], 2),
        rsi_14=round(latest_data['RSI_14'], 2),
        chop_value=regime_data["chop_value"],
        er_value=regime_data["er_value"],
        vwap_dev=regime_data["vwap_dev"],  # NEW
        regime_state=regime_data["regime_state"],
        regime_score=regime_data["regime_score"],
        recommended_moat=regime_data["recommended_moat"],
        stop_loss_rule=regime_data["stop_loss_rule"],
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S CDT")
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)