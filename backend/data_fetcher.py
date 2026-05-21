import math
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, date, timezone
from scipy.stats import norm
from config import BASE_DATA_URL, HEADERS, SPX_PROXY_MULTIPLIER, logger, THETA_EMAIL, THETA_PASSWORD

# --- SPX LIVE PRICE CACHE ---
_spx_cache = {"price": None, "fetched_at": None}
SPX_CACHE_TTL_SECONDS = 60  # Re-fetch from Yahoo at most once per minute

# --- SPX DAY RANGE CACHE ---
_spx_range_cache = {"day_high": None, "day_low": None, "fetched_at": None}
SPX_RANGE_CACHE_TTL_SECONDS = 30  # Day high/low can change fast

# --- VIX CACHE ---
_vix_cache = {"vix": None, "vix9d": None, "fetched_at": None}
VIX_CACHE_TTL_SECONDS = 120  # VIX is less volatile, cache 2 min


def fetch_spx_live_price(spy_fallback_price: float = None) -> tuple[float, str]:
    """
    Fetches the real SPX index price from Yahoo Finance (^GSPC).
    Returns (spx_price, source_label).
    Falls back to SPY * multiplier if yfinance fails.
    Results are cached for SPX_CACHE_TTL_SECONDS to avoid excessive API calls.
    """
    global _spx_cache
    now = datetime.now(timezone.utc)

    # Return cached value if still fresh
    if (_spx_cache["price"] is not None
            and _spx_cache["fetched_at"] is not None
            and (now - _spx_cache["fetched_at"]).total_seconds() < SPX_CACHE_TTL_SECONDS):
        logger.debug(f"SPX cache hit: ${_spx_cache['price']:.2f}")
        return _spx_cache["price"], "Yahoo ^GSPC (cached)"

    # Attempt live fetch
    try:
        ticker = yf.Ticker("^GSPC")
        price = ticker.fast_info.get("lastPrice") or ticker.fast_info.get("last_price")
        if price and price > 0:
            _spx_cache["price"] = float(price)
            _spx_cache["fetched_at"] = now
            logger.info(f"Fetched live SPX from Yahoo Finance: ${price:.2f}")
            return float(price), "Yahoo ^GSPC (live)"
        else:
            logger.warning("Yahoo Finance returned invalid SPX price.")
    except Exception as e:
        logger.warning(f"Yahoo Finance SPX fetch failed: {e}")

    # Fallback: SPY * multiplier
    if spy_fallback_price is not None:
        fallback = spy_fallback_price * SPX_PROXY_MULTIPLIER
        logger.warning(f"Using SPY proxy fallback: ${spy_fallback_price} * {SPX_PROXY_MULTIPLIER} = ${fallback:.2f}")
        return fallback, f"SPY Proxy (x{SPX_PROXY_MULTIPLIER})"

    # Last resort: return cached even if stale
    if _spx_cache["price"] is not None:
        logger.warning(f"Using stale SPX cache: ${_spx_cache['price']:.2f}")
        return _spx_cache["price"], "Yahoo ^GSPC (stale cache)"

    return None, "unavailable"


def fetch_spx_day_range(spy_day_high: float = None, spy_day_low: float = None,
                        spx_spy_ratio: float = None) -> dict:
    """
    Fetches the authoritative SPX intraday high/low from Yahoo Finance (^GSPC).
    Falls back to SPY values × spx_spy_ratio if Yahoo is unavailable.
    Cached for SPX_RANGE_CACHE_TTL_SECONDS to avoid excessive API calls.
    """
    global _spx_range_cache
    now = datetime.now(timezone.utc)

    # Return cached if fresh
    if (_spx_range_cache["day_high"] is not None
            and _spx_range_cache["fetched_at"] is not None
            and (now - _spx_range_cache["fetched_at"]).total_seconds() < SPX_RANGE_CACHE_TTL_SECONDS):
        return {
            "day_high_spx": _spx_range_cache["day_high"],
            "day_low_spx": _spx_range_cache["day_low"],
            "source": "Yahoo ^GSPC (cached)",
        }

    # Attempt live fetch from Yahoo ^GSPC
    try:
        ticker = yf.Ticker("^GSPC")
        info = ticker.fast_info
        day_high = info.get("dayHigh") or info.get("day_high")
        day_low = info.get("dayLow") or info.get("day_low")
        if day_high and day_low and day_high > 0 and day_low > 0:
            _spx_range_cache["day_high"] = round(float(day_high), 2)
            _spx_range_cache["day_low"] = round(float(day_low), 2)
            _spx_range_cache["fetched_at"] = now
            logger.info(f"Fetched SPX day range from Yahoo: High={day_high:.2f}, Low={day_low:.2f}")
            return {
                "day_high_spx": _spx_range_cache["day_high"],
                "day_low_spx": _spx_range_cache["day_low"],
                "source": "Yahoo ^GSPC (live)",
            }
        else:
            logger.warning("Yahoo Finance returned invalid SPX day range.")
    except Exception as e:
        logger.warning(f"Yahoo Finance SPX day range fetch failed: {e}")

    # Fallback: SPY day high/low × ratio (the old method — less accurate but available)
    if spy_day_high is not None and spy_day_low is not None and spx_spy_ratio is not None:
        fallback_high = round(spy_day_high * spx_spy_ratio, 2)
        fallback_low = round(spy_day_low * spx_spy_ratio, 2)
        logger.warning(f"Using SPY-ratio fallback for day range: High={fallback_high}, Low={fallback_low}")
        return {
            "day_high_spx": fallback_high,
            "day_low_spx": fallback_low,
            "source": "SPY ratio fallback",
        }

    # Stale cache as last resort
    if _spx_range_cache["day_high"] is not None:
        logger.warning("Using stale SPX day range cache")
        return {
            "day_high_spx": _spx_range_cache["day_high"],
            "day_low_spx": _spx_range_cache["day_low"],
            "source": "Yahoo ^GSPC (stale cache)",
        }

    return {"day_high_spx": None, "day_low_spx": None, "source": "unavailable"}


def fetch_vix_data() -> dict:
    """
    Fetches VIX (^VIX) and VIX9D (^VIX9D, 9-day expected vol) from Yahoo Finance.
    Returns dict with vix, vix9d, and derived expected move metrics.
    VIX9D is more relevant for 0DTE as it captures near-term expected vol.
    """
    global _vix_cache
    now = datetime.now(timezone.utc)

    # Return cached if fresh
    if (_vix_cache["vix"] is not None
            and _vix_cache["fetched_at"] is not None
            and (now - _vix_cache["fetched_at"]).total_seconds() < VIX_CACHE_TTL_SECONDS):
        logger.debug(f"VIX cache hit: VIX={_vix_cache['vix']}, VIX9D={_vix_cache['vix9d']}")
        return {
            "vix": _vix_cache["vix"],
            "vix9d": _vix_cache["vix9d"],
            "source": "cached",
        }

    vix_val = None
    vix9d_val = None

    # Fetch VIX
    try:
        ticker = yf.Ticker("^VIX")
        price = ticker.fast_info.get("lastPrice") or ticker.fast_info.get("last_price")
        if price and price > 0:
            vix_val = round(float(price), 2)
            logger.info(f"Fetched VIX from Yahoo: {vix_val}")
    except Exception as e:
        logger.warning(f"VIX fetch failed: {e}")

    # Fetch VIX9D (9-day VIX, better for 0DTE)
    try:
        ticker9d = yf.Ticker("^VIX9D")
        price9d = ticker9d.fast_info.get("lastPrice") or ticker9d.fast_info.get("last_price")
        if price9d and price9d > 0:
            vix9d_val = round(float(price9d), 2)
            logger.info(f"Fetched VIX9D from Yahoo: {vix9d_val}")
    except Exception as e:
        logger.warning(f"VIX9D fetch failed: {e}")

    # Cache results
    if vix_val is not None:
        _vix_cache["vix"] = vix_val
        _vix_cache["vix9d"] = vix9d_val
        _vix_cache["fetched_at"] = now

    # Fall back to stale cache
    if vix_val is None and _vix_cache["vix"] is not None:
        vix_val = _vix_cache["vix"]
        vix9d_val = _vix_cache["vix9d"]
        logger.warning(f"Using stale VIX cache: {vix_val}")

    return {
        "vix": vix_val,
        "vix9d": vix9d_val,
        "source": "live" if vix_val is not None else "unavailable",
    }


def compute_expected_move(spx_price: float, vix: float, vix9d: float = None,
                          hours_remaining: float = 6.5) -> dict:
    """
    Computes the expected SPX move for the remaining trading session.

    Math: Expected_Move = SPX × (VIX/100) × sqrt(hours_remaining / 8760)
    For intraday: use hours_remaining (not full year).

    VIX9D is preferred for 0DTE because it captures near-term vol more accurately.
    If VIX9D unavailable, use VIX with a 0.85 scaling factor (intraday vol < annualized).
    """
    # Use VIX9D if available, otherwise scale VIX down
    effective_vol = vix9d if vix9d else vix * 0.85

    # Annualized vol → intraday: divide by sqrt of trading hours per year
    # ~252 trading days × 6.5h = 1638 hours/year
    TRADING_HOURS_PER_YEAR = 252 * 6.5  # 1638

    # Expected 1-sigma move for remaining hours
    expected_1sigma = spx_price * (effective_vol / 100) * math.sqrt(hours_remaining / TRADING_HOURS_PER_YEAR)

    # Practical expected range (markets stay within 1σ ~68% of the time)
    expected_range = round(expected_1sigma, 1)
    # 2-sigma move (95% probability) — this is the "don't sell closer than this"
    expected_2sigma = round(expected_1sigma * 2, 1)
    # Conservative moat: 1.5σ (85% probability) — our recommended minimum
    recommended_moat = round(expected_1sigma * 1.5, 1)

    return {
        "vix": vix,
        "vix9d": vix9d,
        "effective_vol": round(effective_vol, 2),
        "expected_1sigma": expected_range,
        "expected_2sigma": expected_2sigma,
        "recommended_moat": recommended_moat,
        "hours_remaining": round(hours_remaining, 2),
        "explanation": (
            f"VIX{'9D' if vix9d else ''} {effective_vol:.1f} → "
            f"1σ move: ±{expected_range} pts, "
            f"2σ: ±{expected_2sigma} pts. "
            f"Rec moat: {recommended_moat} pts (1.5σ)"
        ),
    }


# --- REALIZED MOVE DISTRIBUTION CACHE ---
_realized_dist_cache = {"data": None, "fetched_date": None}


def fetch_realized_move_distribution(lookback_days: int = 120) -> dict:
    """
    Fetches last `lookback_days` trading days of ^GSPC daily closes from Yahoo Finance.
    Computes the % of days exceeding various absolute move thresholds.
    Cached per calendar day (only needs to refresh once daily).
    """
    global _realized_dist_cache
    today = date.today()

    if _realized_dist_cache["data"] is not None and _realized_dist_cache["fetched_date"] == today:
        return _realized_dist_cache["data"]

    try:
        ticker = yf.Ticker("^GSPC")
        # Fetch extra days to account for weekends/holidays
        hist = ticker.history(period=f"{lookback_days + 60}d", interval="1d")

        if hist is None or len(hist) < 20:
            logger.warning(f"Realized distribution: insufficient data ({len(hist) if hist is not None else 0} days)")
            return {"available": False}

        # Use last `lookback_days` trading days
        hist = hist.tail(lookback_days)
        closes = hist["Close"].values
        n = len(closes)

        if n < 20:
            return {"available": False}

        # Compute daily % moves (close-to-close)
        pct_moves = []
        for i in range(1, n):
            pct_moves.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100)

        abs_moves = [abs(m) for m in pct_moves]
        total = len(abs_moves)

        thresholds = [0.5, 1.0, 1.5, 2.0]
        exceedance = {}
        for t in thresholds:
            count = sum(1 for m in abs_moves if m >= t)
            exceedance[f"pct_over_{t}"] = round(count / total * 100, 1)

        # Also compute mean and median absolute move
        mean_abs = round(sum(abs_moves) / total, 3)
        sorted_abs = sorted(abs_moves)
        median_abs = round(sorted_abs[total // 2], 3)

        result = {
            "available": True,
            "lookback_days": total,
            "exceedance": exceedance,
            "mean_abs_move_pct": mean_abs,
            "median_abs_move_pct": median_abs,
            "explanation": (
                f"Last {total} trading days: "
                f"{exceedance['pct_over_0.5']}% exceeded ±0.5%, "
                f"{exceedance['pct_over_1.0']}% exceeded ±1.0%, "
                f"{exceedance['pct_over_1.5']}% exceeded ±1.5%, "
                f"{exceedance['pct_over_2.0']}% exceeded ±2.0%. "
                f"Avg daily move: ±{mean_abs}%."
            ),
        }

        _realized_dist_cache["data"] = result
        _realized_dist_cache["fetched_date"] = today
        logger.info(f"Realized distribution computed: {result['explanation']}")
        return result

    except Exception as e:
        logger.warning(f"Realized distribution fetch failed: {e}")
        return {"available": False}


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
    df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume', 'vw': 'VWAP_BAR', 't': 'Date'},
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


# ============================================================
# GEX (Gamma Exposure) Engine — ThetaData Integration
# ============================================================

# --- THETADATA CLIENT SINGLETON ---
_theta_client = None


def _get_theta_client():
    """Lazy singleton for ThetaData client to avoid repeated auth."""
    global _theta_client
    if _theta_client is None:
        if not THETA_EMAIL or not THETA_PASSWORD:
            return None
        try:
            from thetadata import ThetaClient
            _theta_client = ThetaClient(email=THETA_EMAIL, password=THETA_PASSWORD)
            logger.info("ThetaData client initialized")
        except Exception as e:
            logger.error(f"ThetaData client init failed: {e}")
            return None
    return _theta_client


# --- GEX CACHE ---
_gex_cache = {"data": None, "fetched_at": None}
GEX_CACHE_TTL_SECONDS = 120  # 2 min cache for real-time wall updates


def _bs_gamma(spot: float, strike: float, iv: float, t_years: float, r: float = 0.05) -> float:
    """
    Compute Black-Scholes gamma from implied volatility.
    gamma = N'(d1) / (S * sigma * sqrt(T))
    """
    if iv <= 0 or t_years <= 0 or spot <= 0:
        return 0.0
    try:
        sigma = iv
        sqrt_t = math.sqrt(t_years)
        d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t_years) / (sigma * sqrt_t)
        gamma = norm.pdf(d1) / (spot * sigma * sqrt_t)
        return gamma
    except (ZeroDivisionError, ValueError):
        return 0.0


def fetch_gex_data(spy_price: float = None, spx_spy_ratio: float = 10.0) -> dict | None:
    """
    Fetches SPY 0DTE options chain from ThetaData (first-order greeks + OI),
    computes gamma via Black-Scholes, and calculates per-strike GEX.

    Returns structured GEX data: net GEX, gamma wall, put wall, call wall,
    top levels, and regime classification.
    """
    global _gex_cache
    now = datetime.now(timezone.utc)

    # Return cached if fresh
    if (_gex_cache["data"] is not None
            and _gex_cache["fetched_at"] is not None
            and (now - _gex_cache["fetched_at"]).total_seconds() < GEX_CACHE_TTL_SECONDS):
        logger.debug("GEX cache hit")
        return _gex_cache["data"]

    client = _get_theta_client()
    if client is None:
        logger.warning("ThetaData client unavailable — GEX data skipped")
        return _gex_fallback()

    today = date.today()
    exp_str = today.strftime("%Y%m%d")

    try:
        # Fetch first-order greeks (delta + IV) for all strikes, both rights
        greeks_df = client.option_snapshot_greeks_first_order(
            "SPY", expiration=exp_str, strike="*", right="both"
        )
        # Fetch open interest
        oi_df = client.option_snapshot_open_interest(
            "SPY", expiration=exp_str, strike="*", right="both"
        )

        if greeks_df is None or len(greeks_df) == 0:
            logger.warning("ThetaData returned empty greeks")
            return _gex_fallback()

        # Convert polars to pandas for easier manipulation
        greeks = greeks_df.to_pandas()
        oi = oi_df.to_pandas()

        # Get underlying price from the data
        if spy_price is None:
            spy_price = greeks["underlying_price"].iloc[0]

        # Compute time to expiry in years (hours remaining today / 8760)
        now_et = datetime.now()
        market_close_hour = 16  # 4 PM ET
        hours_remaining = max(0.01, market_close_hour - now_et.hour - now_et.minute / 60)
        t_years = hours_remaining / (252 * 6.5)  # trading hours per year

        # Merge greeks with OI on strike + right
        merged = greeks.merge(
            oi[["strike", "right", "open_interest"]],
            on=["strike", "right"],
            how="left",
        )
        merged["open_interest"] = merged["open_interest"].fillna(0).astype(int)

        # Filter: only strikes with OI > 0 and valid IV
        merged = merged[(merged["open_interest"] > 0) & (merged["implied_vol"] > 0)].copy()

        if len(merged) == 0:
            logger.warning("No valid options with OI for GEX")
            return _gex_fallback()

        # Compute gamma per option from Black-Scholes
        merged["gamma"] = merged.apply(
            lambda row: _bs_gamma(spy_price, row["strike"], row["implied_vol"], t_years),
            axis=1,
        )

        # GEX per strike: gamma × OI × 100 (contract multiplier) × spot
        # Calls: positive GEX (dealers short calls → positive gamma effect)
        # Puts: negative GEX (dealers short puts → negative gamma effect)
        merged["gex"] = merged.apply(
            lambda row: row["gamma"] * row["open_interest"] * 100 * spy_price * (
                1.0 if row["right"] == "CALL" else -1.0
            ),
            axis=1,
        )

        # Aggregate by strike
        gex_by_strike = merged.groupby("strike").agg(
            call_gex=("gex", lambda x: x[merged.loc[x.index, "right"] == "CALL"].sum()),
            put_gex=("gex", lambda x: x[merged.loc[x.index, "right"] == "PUT"].sum()),
            total_gex=("gex", "sum"),
            call_oi=("open_interest", lambda x: x[merged.loc[x.index, "right"] == "CALL"].sum()),
            put_oi=("open_interest", lambda x: x[merged.loc[x.index, "right"] == "PUT"].sum()),
        ).reset_index()

        # Net GEX across all strikes
        net_gex = round(gex_by_strike["total_gex"].sum(), 0)

        # Scale to SPX terms
        spx_price = spy_price * spx_spy_ratio

        # Identify key levels
        # Gamma Wall: strike with highest absolute positive GEX (magnet)
        positive_gex = gex_by_strike[gex_by_strike["total_gex"] > 0]
        gamma_wall_spy = float(positive_gex.loc[positive_gex["total_gex"].idxmax(), "strike"]) if len(positive_gex) > 0 else spy_price
        gamma_wall_spx = round(gamma_wall_spy * spx_spy_ratio, 0)

        # Put Wall: strike with most negative GEX (floor / support)
        negative_gex = gex_by_strike[gex_by_strike["total_gex"] < 0]
        put_wall_spy = float(negative_gex.loc[negative_gex["total_gex"].idxmin(), "strike"]) if len(negative_gex) > 0 else spy_price - 5
        put_wall_spx = round(put_wall_spy * spx_spy_ratio, 0)

        # Call Wall: strike with highest call OI × gamma (ceiling / resistance)
        call_only = gex_by_strike[gex_by_strike["call_gex"] > 0]
        call_wall_spy = float(call_only.loc[call_only["call_gex"].idxmax(), "strike"]) if len(call_only) > 0 else spy_price + 5
        call_wall_spx = round(call_wall_spy * spx_spy_ratio, 0)

        # Top GEX levels (sorted by absolute magnitude)
        top_levels = gex_by_strike.nlargest(8, "total_gex", keep="first")[["strike", "total_gex", "call_oi", "put_oi"]].copy()
        top_levels["strike_spx"] = (top_levels["strike"] * spx_spy_ratio).round(0)
        top_levels_list = [
            {
                "strike_spy": round(row["strike"], 1),
                "strike_spx": int(row["strike_spx"]),
                "gex": round(row["total_gex"], 0),
                "call_oi": int(row["call_oi"]),
                "put_oi": int(row["put_oi"]),
            }
            for _, row in top_levels.iterrows()
        ]

        # GEX Regime Classification
        if net_gex > 0:
            gex_regime = "POSITIVE"
            gex_regime_label = "Mean-Reverting (Dealer Long Gamma)"
        elif net_gex < -50000:
            gex_regime = "NEGATIVE"
            gex_regime_label = "Trending / Volatile (Dealer Short Gamma)"
        else:
            gex_regime = "NEUTRAL"
            gex_regime_label = "Balanced Gamma"

        result = {
            "net_gex": net_gex,
            "gex_regime": gex_regime,
            "gex_regime_label": gex_regime_label,
            "gamma_wall_spy": round(gamma_wall_spy, 1),
            "gamma_wall_spx": gamma_wall_spx,
            "put_wall_spy": round(put_wall_spy, 1),
            "put_wall_spx": put_wall_spx,
            "call_wall_spy": round(call_wall_spy, 1),
            "call_wall_spx": call_wall_spx,
            "top_levels": top_levels_list,
            "total_strikes": len(gex_by_strike),
            "spy_price": round(spy_price, 2),
            "data_source": "ThetaData (real-time)",
            "expiration": today.isoformat(),
        }

        _gex_cache["data"] = result
        _gex_cache["fetched_at"] = now
        logger.info(f"GEX computed: net={net_gex:,.0f} regime={gex_regime} "
                     f"gamma_wall={gamma_wall_spx} put_wall={put_wall_spx} call_wall={call_wall_spx}")
        return result

    except Exception as e:
        logger.error(f"GEX fetch/compute failed: {e}")
        return _gex_fallback()


def _gex_fallback() -> dict:
    """Return cached or empty GEX data on failure."""
    if _gex_cache["data"] is not None:
        logger.warning("Using stale GEX cache")
        return {**_gex_cache["data"], "data_source": "ThetaData (stale cache)"}
    return {
        "net_gex": 0,
        "gex_regime": "UNAVAILABLE",
        "gex_regime_label": "GEX data unavailable",
        "gamma_wall_spy": 0, "gamma_wall_spx": 0,
        "put_wall_spy": 0, "put_wall_spx": 0,
        "call_wall_spy": 0, "call_wall_spx": 0,
        "top_levels": [],
        "total_strikes": 0,
        "spy_price": 0,
        "data_source": "unavailable",
        "expiration": date.today().isoformat(),
    }


def fetch_historical_gex(trade_date: str, spy_price: float = None, spx_spy_ratio: float = 10.0) -> dict | None:
    """
    Fetches historical SPY 0DTE options chain from ThetaData for a specific date.
    Uses end-of-day greeks + OI snapshots. Returns structured GEX data or None.
    trade_date: "YYYY-MM-DD" format
    """
    client = _get_theta_client()
    if client is None:
        return None

    try:
        from datetime import datetime as dt
        d = dt.strptime(trade_date, "%Y-%m-%d")
        exp_str = d.strftime("%Y%m%d")

        # Fetch EOD greeks and OI for that date's 0DTE chain
        greeks_df = client.option_snapshot_greeks_first_order(
            "SPY", expiration=exp_str, strike="*", right="both",
            date=exp_str,  # historical date
        )
        oi_df = client.option_snapshot_open_interest(
            "SPY", expiration=exp_str, strike="*", right="both",
            date=exp_str,
        )

        if greeks_df is None or len(greeks_df) == 0:
            logger.debug(f"No historical greeks for {trade_date}")
            return None

        greeks = greeks_df.to_pandas()
        oi = oi_df.to_pandas()

        if spy_price is None:
            spy_price = greeks["underlying_price"].iloc[0] if "underlying_price" in greeks.columns else None
        if spy_price is None:
            return None

        # Mid-day approximation for T: ~3 hours remaining at typical trade time
        t_years = 3.0 / (252 * 6.5)

        merged = greeks.merge(
            oi[["strike", "right", "open_interest"]],
            on=["strike", "right"],
            how="left",
        )
        merged["open_interest"] = merged["open_interest"].fillna(0).astype(int)
        merged = merged[(merged["open_interest"] > 0) & (merged["implied_vol"] > 0)].copy()

        if len(merged) == 0:
            return None

        merged["gamma"] = merged.apply(
            lambda row: _bs_gamma(spy_price, row["strike"], row["implied_vol"], t_years),
            axis=1,
        )
        merged["gex"] = merged.apply(
            lambda row: row["gamma"] * row["open_interest"] * 100 * spy_price * (
                1.0 if row["right"] == "CALL" else -1.0
            ),
            axis=1,
        )

        gex_by_strike = merged.groupby("strike").agg(
            total_gex=("gex", "sum"),
        ).reset_index()

        net_gex = round(gex_by_strike["total_gex"].sum(), 0)
        spx_price = spy_price * spx_spy_ratio

        positive_gex = gex_by_strike[gex_by_strike["total_gex"] > 0]
        gamma_wall_spy = float(positive_gex.loc[positive_gex["total_gex"].idxmax(), "strike"]) if len(positive_gex) > 0 else spy_price
        negative_gex = gex_by_strike[gex_by_strike["total_gex"] < 0]
        put_wall_spy = float(negative_gex.loc[negative_gex["total_gex"].idxmin(), "strike"]) if len(negative_gex) > 0 else spy_price - 5

        gex_regime = "POSITIVE" if net_gex > 0 else ("NEGATIVE" if net_gex < -50000 else "NEUTRAL")

        return {
            "net_gex": net_gex,
            "gex_regime": gex_regime,
            "gamma_wall_spx": round(gamma_wall_spy * spx_spy_ratio, 0),
            "put_wall_spx": round(put_wall_spy * spx_spy_ratio, 0),
            "call_wall_spx": round(gamma_wall_spy * spx_spy_ratio, 0),  # simplified
            "total_strikes": len(gex_by_strike),
        }
    except Exception as e:
        logger.debug(f"Historical GEX fetch failed for {trade_date}: {e}")
        return None


def get_spx_spy_ratio(spy_price: float = None) -> dict:
    """Returns the current SPX/SPY ratio for use by other modules."""
    if spy_price is None:
        try:
            ticker = yf.Ticker("SPY")
            spy_price = ticker.fast_info.get("lastPrice") or ticker.fast_info.get("last_price")
        except Exception:
            return {"ratio": SPX_PROXY_MULTIPLIER, "source": "default"}

    spx_price, source = fetch_spx_live_price(spy_fallback_price=spy_price)
    if spx_price and spy_price and spy_price > 0:
        return {"ratio": round(spx_price / spy_price, 4), "source": source}
    return {"ratio": SPX_PROXY_MULTIPLIER, "source": "default"}