"""
Backtesting Engine — Historical Replay of Real Trades
Takes parsed credit spreads from Robinhood CSV and replays each trade date
through the ACTUAL regime engine (evaluate_positions) using historical Alpaca
5-min bars.

For each trade date:
  1. Fetches historical SPY 5-min bars from Alpaca
  2. Runs full regime analysis + evaluate_positions bar-by-bar
  3. The REAL engine computes moat zones, exit strategies, escalation,
     hysteresis, drift, premium trend — identical to live trading
  4. Tracks every exit_strategy.action per bar to determine when
     the system would have told the user to close

Timestamp limitation:
  Robinhood CSV only has dates, not entry/exit times. The backtester replays
  the ENTIRE trading day for each date and runs every bar through the real
  engine. This shows what the system would have said at every moment of the
  day for your actual strikes — regardless of when you entered.
"""

import pandas as pd
import pandas_ta
import requests
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from config import (
    BASE_DATA_URL, HEADERS,
    GAMMA_TRAP_THRESHOLD, WARNING_ZONE_THRESHOLD, BREACH_VERIFICATION_MINUTES,
    MARKET_CLOSE_HOUR_ET,
)
from engine import (
    analyze_market_regime, compute_smart_moat, evaluate_positions,
    clear_rec_state,
)
from data_fetcher import fetch_historical_gex

logger = logging.getLogger("0DTE-QuantEngine")


class _MockPosition:
    """Lightweight mock that satisfies evaluate_positions' attribute access."""
    def __init__(self, id, type, strike, credit, breach_start_time=None):
        self.id = id
        self.type = type
        self.strike = strike
        self.credit = credit
        self.breach_start_time = breach_start_time


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


def _compute_hours_remaining(bar_time) -> float:
    """Compute hours remaining until 4 PM ET from a bar timestamp."""
    if bar_time.tzinfo is None:
        bar_et = bar_time.replace(tzinfo=ZoneInfo("America/New_York"))
    else:
        bar_et = bar_time.astimezone(ZoneInfo("America/New_York"))
    market_close = bar_et.replace(hour=MARKET_CLOSE_HOUR_ET, minute=0, second=0, microsecond=0)
    return max(0, (market_close - bar_et).total_seconds() / 3600)


# Actions from the real engine that mean "close this position"
_CLOSE_ACTIONS = {"CLOSE_NOW", "CLOSE_SOON", "URGENT_CLOSE", "CRITICAL_EJECT"}


def replay_trade_day(
    df: pd.DataFrame,
    spreads_for_day: list[dict],
    spx_spy_ratio: float = 10.0,
    gex_data: dict = None,
) -> dict:
    """
    Replays one trading day through the REAL evaluate_positions engine.

    For each 5-min bar:
      1. Computes regime via analyze_market_regime
      2. Computes smart moat via compute_smart_moat
      3. Calls evaluate_positions with mock position objects — the exact same
         function used in live trading, with all zone logic, hysteresis,
         escalation, drift tracking, premium history, and exit strategies.
      4. Records the engine's exit_strategy.action per spread per bar.

    The system verdict is derived from the REAL engine's output, not
    from reimplemented zone thresholds.
    """
    if df is None or len(df) < 30:
        return {"error": "Insufficient data", "bars": 0 if df is None else len(df)}

    df = _compute_indicators(df)
    if len(df) < 10:
        return {"error": "Not enough bars after indicator warmup", "bars": len(df)}

    # Clear all per-position state so this day's replay is isolated
    clear_rec_state()

    # Day range tracking
    day_high_spy = df['High'].iloc[0]
    day_low_spy = df['Low'].iloc[0]

    # Build mock position objects for each spread
    # SPY strikes get converted to SPX-equivalent for the engine
    mock_positions = []
    for idx, spread in enumerate(spreads_for_day):
        if spread.get("instrument") == "SPY":
            effective_strike = spread["short_strike"] * spx_spy_ratio
            effective_credit = spread.get("open_credit", 0.50) / max(spread["contracts"], 1)
        else:
            effective_strike = spread["short_strike"]
            effective_credit = spread.get("open_credit", 0.50) / max(spread["contracts"], 1)
        mock_positions.append(_MockPosition(
            id=idx + 1000,  # offset to avoid conflicts with real positions
            type=spread["type"],
            strike=effective_strike,
            credit=effective_credit,
        ))

    # Mock DB session (evaluate_positions may update breach_start_time via DB)
    mock_db = MagicMock()

    # Per-spread tracking
    spread_trackers = {}
    for idx in range(len(spreads_for_day)):
        spread_trackers[idx] = {
            "engine_actions": [],       # (bar_idx, time, action, exit_strategy) per bar
            "min_moat": 9999,
            "min_moat_time": None,
            "first_warning_time": None,
            "first_gamma_time": None,
            "first_close_signal_time": None,
            "first_close_signal_action": None,
            "bars_in_warning": 0,
            "bars_in_gamma": 0,
            "bars_below_smart_moat": 0,
            "strike_breached": False,
            "breach_time": None,
            "escalation_peak": None,
        }

    regime_timeline = []

    for bar_idx in range(len(df)):
        day_high_spy = max(day_high_spy, df['High'].iloc[bar_idx])
        day_low_spy = min(day_low_spy, df['Low'].iloc[bar_idx])

        spy_price = df['Close'].iloc[bar_idx]
        spx_price = spy_price * spx_spy_ratio
        day_high_spx = day_high_spy * spx_spy_ratio
        day_low_spx = day_low_spy * spx_spy_ratio
        day_range = day_high_spx - day_low_spx
        range_position = ((spx_price - day_low_spx) / day_range * 100) if day_range > 0 else 50.0

        bar_time = df.index[bar_idx]
        bar_time_str = str(bar_time)
        hours_remaining = _compute_hours_remaining(bar_time)

        # Run regime on bars up to this point
        df_slice = df.iloc[:bar_idx + 1]
        try:
            regime = analyze_market_regime(df_slice)
        except Exception:
            continue

        try:
            smart_moat_data = compute_smart_moat(
                regime, spx_price, day_high_spx, day_low_spx, range_position,
                gex_data=gex_data,
            )
            smart_moat = smart_moat_data["smart_moat"]
        except Exception:
            smart_moat = 35

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

        # All spreads are active for all bars (Robinhood CSV has no timestamps,
        # so we replay the full day and let the engine evaluate every bar)
        for pos in mock_positions:
            # Adjust breach_start_time so the real engine's verification timer
            # uses the bar timeline instead of wall-clock time.
            if pos.breach_start_time is not None:
                pos.breach_start_time = bar_time - timedelta(minutes=5)

        # ---- CALL THE REAL ENGINE ----
        try:
            evaluated = evaluate_positions(
                mock_positions,
                spx_price,
                mock_db,
                regime_score=regime["regime_score"],
                effective_moat_min=smart_moat,
                directional_bias=regime["directional_bias"],
                range_position=range_position,
                day_high_spx=day_high_spx,
                day_low_spx=day_low_spx,
                hours_remaining=hours_remaining,
                momentum_label=regime.get("momentum", {}).get("momentum_label", ""),
                vwap_dev=regime.get("vwap_dev", 0.0),
                gex_data=gex_data,
            )
        except Exception as e:
            logger.debug(f"evaluate_positions failed at bar {bar_idx}: {e}")
            continue

        # Map evaluated results back to spread trackers
        eval_by_id = {e["id"]: e for e in evaluated}
        for idx in range(len(spreads_for_day)):
            pos_id = mock_positions[idx].id
            ev = eval_by_id.get(pos_id)
            if not ev:
                continue

            tracker = spread_trackers[idx]
            moat = ev["moat"]
            action = ev.get("exit_strategy", {}).get("action", "HOLD")
            escalation = ev.get("exit_strategy", {}).get("escalation_level")

            # Record action
            tracker["engine_actions"].append({
                "bar": bar_idx,
                "time": bar_time_str,
                "action": action,
                "moat": moat,
                "message": ev.get("message", ""),
                "escalation_level": escalation,
                "exit_instruction": ev.get("exit_strategy", {}).get("instruction", ""),
            })

            # Track min moat
            if moat < tracker["min_moat"]:
                tracker["min_moat"] = moat
                tracker["min_moat_time"] = bar_time_str

            # Track zone entries
            if moat <= WARNING_ZONE_THRESHOLD and tracker["first_warning_time"] is None:
                tracker["first_warning_time"] = bar_time_str
            if moat <= GAMMA_TRAP_THRESHOLD and tracker["first_gamma_time"] is None:
                tracker["first_gamma_time"] = bar_time_str
            if moat <= GAMMA_TRAP_THRESHOLD:
                tracker["bars_in_gamma"] += 1
            elif moat <= WARNING_ZONE_THRESHOLD:
                tracker["bars_in_warning"] += 1
            elif moat <= smart_moat:
                tracker["bars_below_smart_moat"] += 1

            # Track first close signal from the REAL engine
            if action in _CLOSE_ACTIONS and tracker["first_close_signal_time"] is None:
                tracker["first_close_signal_time"] = bar_time_str
                tracker["first_close_signal_action"] = action

            # Track escalation peak
            if escalation and escalation in ("CLOSE_RECOMMENDED", "URGENT_CLOSE", "CRITICAL_EJECT"):
                tracker["escalation_peak"] = escalation

            # Strike breached
            if moat <= 0 and not tracker["strike_breached"]:
                tracker["strike_breached"] = True
                tracker["breach_time"] = bar_time_str

    # ---- FINALIZE SPREAD ANALYSES ----
    total_bars = len(df)
    finalized_spreads = []
    for idx, spread in enumerate(spreads_for_day):
        tracker = spread_trackers[idx]
        actions = tracker["engine_actions"]

        # Count how many bars the engine recommended closing
        close_bars = sum(1 for a in actions if a["action"] in _CLOSE_ACTIONS)
        total_active_bars = len(actions)

        # Build system verdict from the REAL engine's actions
        if tracker["first_close_signal_time"]:
            system_verdict = "EXIT_RECOMMENDED"
            # Find the strongest action the engine ever issued
            peak_action = tracker["first_close_signal_action"]
            if tracker["escalation_peak"]:
                peak_action = tracker["escalation_peak"]

            system_detail = (
                f"Engine first signaled {tracker['first_close_signal_action']} "
                f"at {tracker['first_close_signal_time']}. "
                f"Peak escalation: {peak_action or 'N/A'}. "
                f"Close signals: {close_bars}/{total_active_bars} bars. "
                f"Min moat: {tracker['min_moat']:.1f} pts at {tracker['min_moat_time']}."
            )
        elif tracker["first_warning_time"]:
            system_verdict = "CAUTION"
            system_detail = (
                f"Warning zone entered at {tracker['first_warning_time']} "
                f"({tracker['bars_in_warning']} bars in warning, "
                f"{tracker['bars_in_gamma']} in gamma), "
                f"but engine never issued a close signal. "
                f"Min moat: {tracker['min_moat']:.1f} pts."
            )
        else:
            system_verdict = "SAFE"
            system_detail = (
                f"Engine kept HOLD/LET_EXPIRE throughout. "
                f"Min moat: {tracker['min_moat']:.1f} pts at {tracker['min_moat_time']}."
            )

        system_detail += " Replayed full day (no entry timestamp in CSV)."

        # Alignment — factual labels only (no P/L estimates, not reliable
        # without entry timestamps and real options pricing data)
        if system_verdict in ("SAFE", "CAUTION"):
            if spread["won"]:
                alignment = "ALIGNED_WIN"
                alignment_label = "System agreed to hold — trade won"
            else:
                alignment = "BOTH_MISSED"
                alignment_label = "System did not flag exit — trade lost"
        elif system_verdict == "EXIT_RECOMMENDED":
            if spread["won"]:
                alignment = "EXIT_FLAGGED_WON"
                alignment_label = "System flagged exit — but trade won anyway"
            else:
                alignment = "EXIT_FLAGGED_LOST"
                alignment_label = "System flagged exit — trade lost"
        else:
            alignment = "UNKNOWN"
            alignment_label = "Insufficient data"

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
            "system_exit_time": tracker["first_close_signal_time"],
            "system_exit_reason": tracker["first_close_signal_action"],
            "alignment": alignment,
            "alignment_label": alignment_label,
            "total_bars": total_bars,
            "active_bars": total_active_bars,
            "close_signal_bars": close_bars,
            "escalation_peak": tracker["escalation_peak"],
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

    # Clean up state after this day's replay
    clear_rec_state()

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
        },
        "daily_results": daily_results,
        "skipped_dates": skipped_dates,
    }
