"""
Backtesting Engine — Historical Replay of Real Trades
Takes parsed credit spreads from Robinhood CSV and replays each trade date
through the regime engine using historical Alpaca 5-min bars.

For each trade date:
  1. Fetches historical SPY 5-min bars from Alpaca
  2. Runs regime analysis bar-by-bar across the full trading day
  3. Tracks moat distance to the user's actual strikes at each bar
  4. Identifies when the system would have flagged warnings / gamma traps
  5. Reports what the system recommended vs what actually happened

Workaround for missing timestamps:
  Robinhood CSV only has dates, not times. Instead of guessing entry time,
  we replay the ENTIRE day and show the full regime timeline. The user sees
  exactly when their strikes were safe, in warning, or in gamma trap territory.
"""

import pandas as pd
import pandas_ta
import requests
import logging
from datetime import datetime, timedelta, timezone

from config import (
    BASE_DATA_URL, HEADERS,
    GAMMA_TRAP_THRESHOLD, WARNING_ZONE_THRESHOLD,
)
from engine import analyze_market_regime, compute_smart_moat
from data_fetcher import fetch_historical_gex

logger = logging.getLogger("0DTE-QuantEngine")


def fetch_historical_bars(symbol: str, date: str, timeframe: str = "5Min") -> pd.DataFrame | None:
    """
    Fetches intraday bars for a specific date from Alpaca.
    date: "YYYY-MM-DD"
    """
    start = f"{date}T09:30:00-04:00"
    end = f"{date}T16:00:00-04:00"

    url = (
        f"{BASE_DATA_URL}/{symbol}/bars"
        f"?timeframe={timeframe}"
        f"&start={start}&end={end}"
        f"&limit=10000"
        f"&adjustment=raw"
    )

    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            logger.warning(f"Historical bars fetch failed for {date}: {res.status_code}")
            return None

        bars = res.json().get('bars', [])
        if not bars:
            logger.warning(f"No bars returned for {date}")
            return None

        df = pd.DataFrame(bars)
        df.rename(columns={
            'o': 'Open', 'h': 'High', 'l': 'Low',
            'c': 'Close', 'v': 'Volume', 'vw': 'VWAP_BAR', 't': 'Date'
        }, inplace=True)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        logger.info(f"Fetched {len(df)} bars for {date}")
        return df

    except Exception as e:
        logger.warning(f"Historical fetch error for {date}: {e}")
        return None


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Append TA indicators (same as main pipeline)."""
    df = df.copy()
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.chop(length=14, append=True)
    df.ta.er(length=10, append=True)
    df.ta.vwap(append=True)
    df.dropna(inplace=True)
    return df


def replay_trade_day(
    df: pd.DataFrame,
    spreads_for_day: list[dict],
    spx_spy_ratio: float = 10.0,
    gex_data: dict = None,
) -> dict:
    """
    Replays one trading day through the regime engine, tracking the user's
    actual strikes against the system's recommendations.

    Returns:
      - regime_timeline: regime snapshots every 15 minutes (reduced for payload)
      - per-spread analysis: moat history, warning moments, system verdict
      - day summary: SPX open/close/range, avg regime
    """
    if df is None or len(df) < 30:
        return {"error": "Insufficient data", "bars": 0 if df is None else len(df)}

    df = _compute_indicators(df)
    if len(df) < 10:
        return {"error": "Not enough bars after indicator warmup", "bars": len(df)}

    # Day range tracking
    day_high_spy = df['High'].iloc[0]
    day_low_spy = df['Low'].iloc[0]

    regime_timeline = []
    spread_analyses = {i: _init_spread_tracker(s) for i, s in enumerate(spreads_for_day)}

    for bar_idx in range(len(df)):
        day_high_spy = max(day_high_spy, df['High'].iloc[bar_idx])
        day_low_spy = min(day_low_spy, df['Low'].iloc[bar_idx])

        spy_price = df['Close'].iloc[bar_idx]
        spx_price = spy_price * spx_spy_ratio
        day_high_spx = day_high_spy * spx_spy_ratio
        day_low_spx = day_low_spy * spx_spy_ratio
        day_range = day_high_spx - day_low_spx
        range_position = ((spx_price - day_low_spx) / day_range * 100) if day_range > 0 else 50.0

        # Run regime on bars up to this point
        df_slice = df.iloc[:bar_idx + 1]
        try:
            regime = analyze_market_regime(df_slice)
        except Exception:
            continue

        try:
            smart_moat_data = compute_smart_moat(
                regime, spx_price, day_high_spx, day_low_spx, range_position
            )
            smart_moat = smart_moat_data["smart_moat"]
        except Exception:
            smart_moat = 35

        bar_time = df.index[bar_idx]
        bar_time_str = str(bar_time)

        # Record regime snapshot every 3 bars (~15 min) for timeline
        if bar_idx % 3 == 0:
            regime_timeline.append({
                "bar": bar_idx,
                "time": bar_time_str,
                "spx_price": round(spx_price, 2),
                "regime_score": regime["regime_score"],
                "continuous_score": regime["continuous_score"],
                "directional_bias": regime["directional_bias"],
                "smart_moat": smart_moat,
            })

        # Track each spread against this bar
        for idx, spread in enumerate(spreads_for_day):
            tracker = spread_analyses[idx]
            short_strike = spread["short_strike"]

            if spread["type"] == "Put Spread":
                moat = round(spx_price - short_strike, 1)
            else:
                moat = round(short_strike - spx_price, 1)

            tracker["moat_history"].append(moat)

            # Track minimum moat and when it occurred
            if moat < tracker["min_moat"]:
                tracker["min_moat"] = moat
                tracker["min_moat_time"] = bar_time_str
                tracker["min_moat_bar"] = bar_idx

            # First time entering warning zone
            if moat <= WARNING_ZONE_THRESHOLD and tracker["first_warning_time"] is None:
                tracker["first_warning_time"] = bar_time_str
                tracker["first_warning_bar"] = bar_idx

            # First time entering gamma trap
            if moat <= GAMMA_TRAP_THRESHOLD and tracker["first_gamma_time"] is None:
                tracker["first_gamma_time"] = bar_time_str
                tracker["first_gamma_bar"] = bar_idx

            # Track system recommendation at this bar
            if moat <= GAMMA_TRAP_THRESHOLD:
                tracker["bars_in_gamma"] += 1
                if regime["regime_score"] >= 3:
                    tracker["system_would_exit"] = True
                    if tracker["system_exit_time"] is None:
                        tracker["system_exit_time"] = bar_time_str
                        tracker["system_exit_reason"] = "GAMMA_TRAP + State C"
            elif moat <= WARNING_ZONE_THRESHOLD:
                tracker["bars_in_warning"] += 1
                if regime["regime_score"] >= 3 and not tracker["system_would_exit"]:
                    tracker["system_would_exit"] = True
                    if tracker["system_exit_time"] is None:
                        tracker["system_exit_time"] = bar_time_str
                        tracker["system_exit_reason"] = "WARNING + State C"
            elif moat <= smart_moat:
                tracker["bars_below_smart_moat"] += 1

            # Strike breached
            if moat <= 0 and not tracker["strike_breached"]:
                tracker["strike_breached"] = True
                tracker["breach_time"] = bar_time_str

    # Finalize spread analyses
    total_bars = len(df)
    finalized_spreads = []
    for idx, spread in enumerate(spreads_for_day):
        tracker = spread_analyses[idx]
        moat_history = tracker["moat_history"]

        # Determine system verdict
        if tracker["system_would_exit"]:
            system_verdict = "EXIT_RECOMMENDED"
            system_detail = f"System would have flagged exit at {tracker['system_exit_time']} — {tracker['system_exit_reason']}"
        elif tracker["first_warning_time"]:
            system_verdict = "CAUTION"
            system_detail = f"Warning zone entered at {tracker['first_warning_time']}, but regime allowed holding"
        else:
            system_verdict = "SAFE"
            system_detail = "Spread stayed outside danger zones all day"

        # Did user follow system? Compare outcome with system verdict
        if spread["won"] and system_verdict == "SAFE":
            alignment = "ALIGNED_WIN"
            alignment_label = "System agreed — safe trade, won"
        elif spread["won"] and system_verdict == "EXIT_RECOMMENDED":
            alignment = "LUCKY_WIN"
            alignment_label = "System would have exited early — you held and won"
        elif not spread["won"] and system_verdict == "EXIT_RECOMMENDED":
            alignment = "SYSTEM_CORRECT"
            alignment_label = "System flagged exit — following it would have helped"
        elif not spread["won"] and system_verdict == "SAFE":
            alignment = "BOTH_WRONG"
            alignment_label = "System didn't flag danger — both missed it"
        else:
            alignment = "MIXED"
            alignment_label = "Partial alignment"

        finalized_spreads.append({
            **spread,
            "min_moat": round(tracker["min_moat"], 1),
            "min_moat_time": tracker["min_moat_time"],
            "first_warning_time": tracker["first_warning_time"],
            "first_gamma_time": tracker["first_gamma_time"],
            "bars_in_warning": tracker["bars_in_warning"],
            "bars_in_gamma": tracker["bars_in_gamma"],
            "bars_below_smart_moat": tracker["bars_below_smart_moat"],
            "strike_breached": tracker["strike_breached"],
            "breach_time": tracker["breach_time"],
            "system_verdict": system_verdict,
            "system_detail": system_detail,
            "system_exit_time": tracker["system_exit_time"],
            "system_exit_reason": tracker["system_exit_reason"],
            "alignment": alignment,
            "alignment_label": alignment_label,
            "total_bars": total_bars,
        })

    # Day summary
    spx_open = round(df['Close'].iloc[0] * spx_spy_ratio, 2)
    spx_close = round(df['Close'].iloc[-1] * spx_spy_ratio, 2)
    day_range_pts = round((day_high_spy - day_low_spy) * spx_spy_ratio, 1)

    # GEX context for this day
    gex_summary = None
    if gex_data:
        gex_summary = {
            "gex_regime": gex_data.get("gex_regime", "N/A"),
            "net_gex": gex_data.get("net_gex", 0),
            "gamma_wall_spx": gex_data.get("gamma_wall_spx", 0),
            "put_wall_spx": gex_data.get("put_wall_spx", 0),
        }

    scores = [r["regime_score"] for r in regime_timeline]
    state_a_pct = round(sum(1 for s in scores if s <= 1) / max(len(scores), 1) * 100)
    state_b_pct = round(sum(1 for s in scores if s == 2) / max(len(scores), 1) * 100)
    state_c_pct = round(sum(1 for s in scores if s >= 3) / max(len(scores), 1) * 100)

    return {
        "date": spreads_for_day[0]["iso_date"] if spreads_for_day else "unknown",
        "display_date": spreads_for_day[0]["date"] if spreads_for_day else "unknown",
        "spx_open": spx_open,
        "spx_close": spx_close,
        "spx_change": round(spx_close - spx_open, 2),
        "day_range_pts": day_range_pts,
        "bars_processed": total_bars,
        "regime_distribution": {
            "state_a_pct": state_a_pct,
            "state_b_pct": state_b_pct,
            "state_c_pct": state_c_pct,
        },
        "gex": gex_summary,
        "spreads": finalized_spreads,
        "regime_timeline": regime_timeline,
    }


def _init_spread_tracker(spread: dict) -> dict:
    return {
        "moat_history": [],
        "min_moat": 9999,
        "min_moat_time": None,
        "min_moat_bar": None,
        "first_warning_time": None,
        "first_warning_bar": None,
        "first_gamma_time": None,
        "first_gamma_bar": None,
        "bars_in_warning": 0,
        "bars_in_gamma": 0,
        "bars_below_smart_moat": 0,
        "strike_breached": False,
        "breach_time": None,
        "system_would_exit": False,
        "system_exit_time": None,
        "system_exit_reason": None,
    }


def run_backtest(spreads: list[dict], spx_spy_ratio: float = 10.0) -> dict:
    """
    Runs the full backtest: for each unique trade date, fetches historical bars
    and replays all spreads for that date through the regime engine.
    """
    # Group spreads by iso_date
    by_date = defaultdict(list)
    for s in spreads:
        by_date[s["iso_date"]].append(s)

    daily_results = []
    skipped_dates = []

    for iso_date in sorted(by_date.keys(), reverse=True):
        day_spreads = by_date[iso_date]
        logger.info(f"Backtesting {iso_date} — {len(day_spreads)} spread(s)")

        df = fetch_historical_bars("SPY", iso_date)
        if df is None or len(df) == 0:
            logger.warning(f"No historical data for {iso_date}, skipping")
            skipped_dates.append(iso_date)
            continue

        # Fetch historical GEX for this date (best-effort, None if unavailable)
        hist_gex = None
        try:
            hist_gex = fetch_historical_gex(iso_date, spx_spy_ratio=spx_spy_ratio)
        except Exception as e:
            logger.debug(f"Historical GEX unavailable for {iso_date}: {e}")

        day_result = replay_trade_day(df, day_spreads, spx_spy_ratio=spx_spy_ratio, gex_data=hist_gex)
        if "error" not in day_result:
            daily_results.append(day_result)
        else:
            logger.warning(f"Replay failed for {iso_date}: {day_result['error']}")
            skipped_dates.append(iso_date)

    if not daily_results:
        return {"error": "No valid trading days found", "days_processed": 0}

    # Aggregate
    all_spreads = [s for d in daily_results for s in d["spreads"]]
    total_trades = len(all_spreads)
    wins = sum(1 for s in all_spreads if s["won"])
    losses = total_trades - wins

    alignment_counts = defaultdict(int)
    for s in all_spreads:
        alignment_counts[s["alignment"]] += 1

    system_exit_count = sum(1 for s in all_spreads if s["system_verdict"] == "EXIT_RECOMMENDED")
    system_safe_count = sum(1 for s in all_spreads if s["system_verdict"] == "SAFE")

    total_pl = round(sum(s["net_pl"] for s in all_spreads), 2)

    # How much P/L would have been saved/lost following system
    system_correct_savings = sum(
        abs(s["net_pl"]) for s in all_spreads
        if s["alignment"] == "SYSTEM_CORRECT"
    )

    return {
        "summary": {
            "days_processed": len(daily_results),
            "days_skipped": len(skipped_dates),
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            "total_pl": total_pl,
            "avg_pl_per_trade": round(total_pl / total_trades, 2) if total_trades > 0 else 0,
            "system_exit_flags": system_exit_count,
            "system_safe_flags": system_safe_count,
            "alignment": dict(alignment_counts),
            "potential_savings": round(system_correct_savings, 2),
        },
        "daily_results": daily_results,
        "skipped_dates": skipped_dates,
    }
