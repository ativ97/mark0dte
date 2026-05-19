from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas_ta as ta
import uvicorn
from pydantic import BaseModel
import datetime

# Import modular components
from config import logger
from data_fetcher import fetch_alpaca_market_data
from engine import analyze_market_regime

app = FastAPI(title="0DTE Quant Engine V3.0")

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
    vwap_dev: float
    regime_state: str
    regime_score: int
    recommended_moat: str
    stop_loss_rule: str
    timestamp: str


@app.get("/api/telemetry", response_model=TelemetryResponse)
def get_telemetry():
    logger.info("Processing GET request to /api/telemetry")

    # 1. Fetch Data
    df, live_price = fetch_alpaca_market_data("SPY")

    if df is None or df.empty:
        logger.error("Dataframe empty or failed to download from Alpaca API!")
        raise HTTPException(status_code=503, detail="Failed to fetch market data from upstream API.")

    # 2. Calculate Indicators
    logger.info("Calculating technical indicators...")
    try:
        df.ta.ema(length=9, append=True)
        df.ta.ema(length=21, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.chop(length=14, append=True)
        df.ta.er(length=10, append=True)
        df.ta.vwap(append=True)

        row_count_before = len(df)
        df.dropna(inplace=True)
        row_count_after = len(df)
        logger.info(
            f"Indicators calculated. Dropped {row_count_before - row_count_after} NaN rows. Active rows: {row_count_after}")
    except Exception as e:
        logger.exception("Error during indicator calculations:")
        raise HTTPException(status_code=500, detail=f"Error calculating technical indicators: {str(e)}")

    latest_data = df.iloc[-1]

    # 3. Analyze and get Regime
    regime_data = analyze_market_regime(df)

    # 4. Formulate and send response
    logger.info("Successfully formulated telemetry response payload.")
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
    logger.info("Starting 0DTE Quant Engine server...")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)