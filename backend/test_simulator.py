import yfinance as yf
import pandas_ta as ta
import pandas as pd

# Import the logic directly from your main backend file (the Canvas)
from main import analyze_market_regime


def run_historical_simulation():
    """
    Simulates the Quant Engine running in real-time by feeding it
    historical data sequentially.
    """
    print("Fetching historical 5-minute SPY data...")
    ticker = yf.Ticker("SPY")
    # Fetch 1 month of 5-minute data for a robust sample size
    df = ticker.history(period="1mo", interval="5m")

    if df.empty:
        print("Error: Could not fetch data.")
        return

    print("Calculating Technical Indicators...")
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.chop(length=14, append=True)
    df.ta.er(length=10, append=True)

    # Drop rows with NaN values caused by indicator lookback periods
    df.dropna(inplace=True)

    # We will simulate the last 50 5-minute candles (roughly 1 trading day)
    simulation_length = 50
    start_idx = len(df) - simulation_length

    print("\n--- BEGINNING SIMULATION OVER LAST 50 PERIODS ---\n")

    # Step through the historical data exactly as if it were streaming live
    for i in range(start_idx, len(df)):
        # Create a slice of data up to the "current" simulation point
        current_slice = df.iloc[:i + 1]

        # Pass the slice to our engine
        regime_output = analyze_market_regime(current_slice)

        # Extract the timestamp and closing price for logging
        timestamp = current_slice.index[-1].strftime("%Y-%m-%d %H:%M")
        close_price = current_slice['Close'].iloc[-1]

        # Print the simulation log
        print(
            f"[{timestamp}] SPY: ${close_price:.2f} | Score: {regime_output['regime_score']} | State: {regime_output['regime_state']}")
        print(
            f"  -> CHOP: {regime_output['chop_value']} | ER: {regime_output['er_value']} | RSI: {current_slice['RSI_14'].iloc[-1]:.2f}\n")


if __name__ == "__main__":
    run_historical_simulation()