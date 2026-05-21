import pandas as pd
import logging
from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo

from config import (
    CHOP_THRESHOLD, EFFICIENCY_RATIO_THRESHOLD,
    RSI_DEAD_ZONE_LOWER, RSI_DEAD_ZONE_UPPER,
    EMA_COMPRESSION_THRESHOLD_PCT, VWAP_ELASTICITY_THRESHOLD_PCT,
    GAMMA_TRAP_THRESHOLD, WARNING_ZONE_THRESHOLD,
    MOAT_BAR_SCALE, BREACH_VERIFICATION_MINUTES,
    STATE_A_MIN_MOAT, STATE_B_MIN_MOAT, STATE_C_MIN_MOAT,
    MARKET_CLOSE_HOUR_ET, GAMMA_ACCELERATION_HOUR_ET, FINAL_HOUR_MOAT_MULTIPLIER,
)

logger = logging.getLogger("0DTE-QuantEngine")

# ---- RECOMMENDATION STATE TRACKER ----
# Tracks per-position recommendation state to prevent flip-flopping.
# Key = position_id, Value = {action, first_issued, last_seen, consecutive_count, moat_at_issue}
_rec_state: dict[int, dict] = {}
REC_COOLDOWN_MINUTES = 10     # CLOSE_NOW/CLOSE_SOON stays locked for this long
REC_HYSTERESIS_PTS = 15       # Moat must improve by this much to exit a CLOSE state


def _update_rec_state(pos_id: int, action: str, moat: float) -> dict:
    """
    Updates the recommendation state tracker for a position.
    Returns dict with: action (possibly overridden), signal_age (consecutive count),
    signal_stability label, and cooldown info.
    """
    now = datetime.now(timezone.utc)
    prev = _rec_state.get(pos_id)

    if prev is None or prev["action"] != action:
        # New recommendation or action changed
        if prev and prev["action"] in ("CLOSE_NOW", "CLOSE_SOON"):
            # Check cooldown: don't downgrade from CLOSE to HOLD too quickly
            elapsed = (now - prev["first_issued"]).total_seconds() / 60
            moat_improvement = moat - prev.get("moat_at_issue", 0)
            if elapsed < REC_COOLDOWN_MINUTES and moat_improvement < REC_HYSTERESIS_PTS:
                # Keep the previous CLOSE action (cooldown active)
                prev["last_seen"] = now
                prev["consecutive_count"] += 1
                return {
                    "action": prev["action"],
                    "signal_age": prev["consecutive_count"],
                    "signal_stability": "LOCKED" if prev["consecutive_count"] >= 3 else "COOLING",
                    "cooldown_remaining_min": round(REC_COOLDOWN_MINUTES - elapsed, 1),
                    "original_action": action,
                }

        # Record the new state
        _rec_state[pos_id] = {
            "action": action,
            "first_issued": now,
            "last_seen": now,
            "consecutive_count": 1,
            "moat_at_issue": moat,
        }
        return {
            "action": action,
            "signal_age": 1,
            "signal_stability": "NEW",
            "cooldown_remaining_min": 0,
            "original_action": action,
        }
    else:
        # Same action as before — increment counter
        prev["last_seen"] = now
        prev["consecutive_count"] += 1
        age = prev["consecutive_count"]
        if age >= 5:
            stability = "STABLE"
        elif age >= 3:
            stability = "CONFIRMING"
        else:
            stability = "NEW"
        return {
            "action": action,
            "signal_age": age,
            "signal_stability": stability,
            "cooldown_remaining_min": 0,
            "original_action": action,
        }


# ---- BREAKEVEN TOUCH TRACKER ----
# Tracks when a position's estimated buyback returns near the credit (breakeven).
# Key = position_id, Value = {touch_count, last_touch_time, peak_loss_since_entry}
_breakeven_state: dict[int, dict] = {}
BREAKEVEN_THRESHOLD_PCT = 15  # Within 15% of credit = "at breakeven"


def _update_breakeven_state(pos_id: int, credit: float, est_buyback: float,
                             estimated_pl: float) -> dict | None:
    """
    Tracks breakeven touches for a position. Returns a breakeven event dict
    if the position has returned to breakeven after being in a loss, or None.
    """
    now = datetime.now(timezone.utc)
    state = _breakeven_state.get(pos_id)

    if state is None:
        _breakeven_state[pos_id] = {
            "touch_count": 0,
            "last_touch_time": None,
            "peak_loss": 0,
            "was_in_loss": False,
        }
        state = _breakeven_state[pos_id]

    # Track peak loss
    if estimated_pl < state["peak_loss"]:
        state["peak_loss"] = estimated_pl

    # Was the position ever materially in a loss? (more than 20% of credit)
    if estimated_pl < -(credit * 0.20):
        state["was_in_loss"] = True

    # Check if at breakeven now
    at_breakeven = abs(est_buyback - credit) / max(credit, 0.01) < (BREAKEVEN_THRESHOLD_PCT / 100)

    if at_breakeven and state["was_in_loss"]:
        # Debounce: don't count the same touch within 5 minutes
        if (state["last_touch_time"] is None or
                (now - state["last_touch_time"]).total_seconds() > 300):
            state["touch_count"] += 1
            state["last_touch_time"] = now
            return {
                "touch_count": state["touch_count"],
                "peak_loss": round(state["peak_loss"], 2),
                "est_buyback": round(est_buyback, 2),
            }

    return None


# ---- PREMIUM HISTORY TRACKER ----
# Stores last N estimated_buyback readings per position to detect trends.
# Key = position_id, Value = list of (timestamp, est_buyback) tuples
_premium_history: dict[int, list[tuple[datetime, float]]] = {}
PREMIUM_HISTORY_MAX = 10


def _update_premium_history(pos_id: int, est_buyback: float) -> dict:
    """
    Records the estimated buyback and returns trend analysis.
    Returns dict with: trend (RISING/FALLING/STABLE/VOLATILE), readings count,
    min/max/avg over window, and the raw history.
    """
    now = datetime.now(timezone.utc)
    if pos_id not in _premium_history:
        _premium_history[pos_id] = []

    hist = _premium_history[pos_id]
    hist.append((now, est_buyback))

    # Keep only last N readings
    if len(hist) > PREMIUM_HISTORY_MAX:
        _premium_history[pos_id] = hist[-PREMIUM_HISTORY_MAX:]
        hist = _premium_history[pos_id]

    values = [v for _, v in hist]
    n = len(values)

    if n < 3:
        return {
            "trend": "INSUFFICIENT",
            "readings": n,
            "values": values,
        }

    # Detect trend via simple slope of last readings
    recent = values[-3:]
    diffs = [recent[i+1] - recent[i] for i in range(len(recent)-1)]
    avg_diff = sum(diffs) / len(diffs)

    min_val = round(min(values), 2)
    max_val = round(max(values), 2)
    avg_val = round(sum(values) / n, 2)
    spread = max_val - min_val

    # Classify trend
    if spread < 0.05:
        trend = "STABLE"
    elif avg_diff > 0.03:
        trend = "RISING"
    elif avg_diff < -0.03:
        trend = "FALLING"
    elif spread > 0.20:
        trend = "VOLATILE"
    else:
        trend = "STABLE"

    return {
        "trend": trend,
        "readings": n,
        "min": min_val,
        "max": max_val,
        "avg": avg_val,
        "values": [round(v, 2) for v in values],
    }


# ---- GRADUATED EXIT ESCALATION ----
# Tracks the escalation level for each position in danger zones.
# Key = position_id, Value = {level, entered_at, escalated_at}
_escalation_state: dict[int, dict] = {}
ESCALATION_LEVELS = ["CAUTION", "WARNING", "CLOSE_RECOMMENDED", "URGENT_CLOSE", "CRITICAL_EJECT"]
ESCALATION_MIN_HOLD_MINUTES = 3  # Minimum minutes at each level before escalating


def _get_escalation_level(pos_id: int, in_danger: bool) -> dict:
    """
    Returns the current escalation level for a position.
    If `in_danger` is True, escalates up (with min hold times).
    If False, de-escalates (resets).
    """
    now = datetime.now(timezone.utc)
    state = _escalation_state.get(pos_id)

    if not in_danger:
        # Position recovered — de-escalate but don't instantly reset from high levels
        if state and ESCALATION_LEVELS.index(state["level"]) >= 2:
            # Was at CLOSE_RECOMMENDED or higher — keep WARNING for 1 cycle as buffer
            _escalation_state[pos_id] = {
                "level": "WARNING",
                "entered_at": state["entered_at"],
                "escalated_at": now,
            }
            return _escalation_state[pos_id]
        _escalation_state.pop(pos_id, None)
        return {"level": "SAFE", "entered_at": None, "escalated_at": None}

    if state is None:
        # First time entering danger
        _escalation_state[pos_id] = {
            "level": "CAUTION",
            "entered_at": now,
            "escalated_at": now,
        }
        return _escalation_state[pos_id]

    # Check if enough time has passed to escalate
    elapsed = (now - state["escalated_at"]).total_seconds() / 60
    current_idx = ESCALATION_LEVELS.index(state["level"])

    if elapsed >= ESCALATION_MIN_HOLD_MINUTES and current_idx < len(ESCALATION_LEVELS) - 1:
        new_level = ESCALATION_LEVELS[current_idx + 1]
        state["level"] = new_level
        state["escalated_at"] = now

    return state


# ---- MOAT ZONE HYSTERESIS ----
# Tracks the current zone for each position to apply different entry/exit thresholds.
# Key = position_id, Value = current zone ("SAFE", "CAUTION", "WARNING", "GAMMA_TRAP")
_moat_zone_state: dict[int, str] = {}
HYSTERESIS_BUFFER_PCT = 0.15  # 15% buffer — must improve by this % above threshold to exit a zone


def _apply_moat_hysteresis(pos_id: int, moat: float,
                           warning_threshold: float,
                           caution_threshold: float) -> str:
    """
    Applies hysteresis to moat zone transitions.
    To ENTER a worse zone: use the standard threshold.
    To EXIT back to a better zone: moat must exceed threshold + buffer.
    Returns the effective zone: GAMMA_TRAP, WARNING, CAUTION, or SAFE.
    """
    prev_zone = _moat_zone_state.get(pos_id, "SAFE")

    # Compute raw zone without hysteresis
    if moat <= GAMMA_TRAP_THRESHOLD:
        raw_zone = "GAMMA_TRAP"
    elif moat <= warning_threshold:
        raw_zone = "WARNING"
    elif moat < caution_threshold:
        raw_zone = "CAUTION"
    else:
        raw_zone = "SAFE"

    zone_order = {"SAFE": 0, "CAUTION": 1, "WARNING": 2, "GAMMA_TRAP": 3}

    # Getting worse (entering a danger zone): use raw threshold
    if zone_order.get(raw_zone, 0) >= zone_order.get(prev_zone, 0):
        _moat_zone_state[pos_id] = raw_zone
        return raw_zone

    # Getting better (trying to exit a danger zone): require buffer
    if prev_zone == "GAMMA_TRAP":
        exit_threshold = GAMMA_TRAP_THRESHOLD * (1 + HYSTERESIS_BUFFER_PCT)
        if moat > exit_threshold:
            _moat_zone_state[pos_id] = raw_zone
            return raw_zone
        return "GAMMA_TRAP"
    elif prev_zone == "WARNING":
        exit_threshold = warning_threshold * (1 + HYSTERESIS_BUFFER_PCT)
        if moat > exit_threshold:
            _moat_zone_state[pos_id] = raw_zone
            return raw_zone
        return "WARNING"
    elif prev_zone == "CAUTION":
        exit_threshold = caution_threshold * (1 + HYSTERESIS_BUFFER_PCT)
        if moat > exit_threshold:
            _moat_zone_state[pos_id] = "SAFE"
            return "SAFE"
        return "CAUTION"

    _moat_zone_state[pos_id] = raw_zone
    return raw_zone


# ---- CUMULATIVE DRIFT TRACKER ----
# Records SPX price at each refresh. Computes rolling drift toward nearest strike.
# Key: list of (timestamp, spx_price) tuples, max 90 min window.
_drift_history: list[tuple[datetime, float]] = []
DRIFT_WINDOW_MINUTES = 90
DRIFT_ALERT_THRESHOLD_PTS = 10  # Alert if SPX drifted ≥10 pts toward any strike


def _update_drift_tracker(spx_price: float) -> None:
    """Record current SPX price with timestamp, trim entries older than window."""
    now = datetime.now(timezone.utc)
    _drift_history.append((now, spx_price))
    # Trim entries older than drift window
    cutoff = now - timedelta(minutes=DRIFT_WINDOW_MINUTES)
    while _drift_history and _drift_history[0][0] < cutoff:
        _drift_history.pop(0)


def compute_drift_toward_strike(strike: float, spread_type: str) -> dict | None:
    """
    Computes the cumulative drift of SPX toward a specific strike over the drift window.
    Returns dict with drift info if significant, else None.
    For calls: drift = how much SPX moved UP toward the strike.
    For puts: drift = how much SPX moved DOWN toward the strike.
    """
    if len(_drift_history) < 2:
        return None

    oldest_price = _drift_history[0][1]
    current_price = _drift_history[-1][1]
    window_minutes = (_drift_history[-1][0] - _drift_history[0][0]).total_seconds() / 60

    if window_minutes < 5:
        return None

    price_change = current_price - oldest_price

    # For calls: upward drift toward strike is dangerous
    # For puts: downward drift toward strike is dangerous
    if spread_type == "Call Spread":
        drift_toward = max(0, price_change)  # Only positive moves matter
    elif spread_type == "Put Spread":
        drift_toward = max(0, -price_change)  # Only negative moves matter
    else:
        return None

    if drift_toward >= DRIFT_ALERT_THRESHOLD_PTS:
        return {
            "drift_pts": round(drift_toward, 1),
            "window_minutes": round(window_minutes, 0),
            "start_price": round(oldest_price, 1),
            "current_price": round(current_price, 1),
        }

    return None


def clear_rec_state(pos_id: int = None):
    """Clear recommendation state for a position (on close) or all positions (on market close)."""
    global _rec_state, _breakeven_state, _drift_history, _premium_history, _moat_zone_state, _escalation_state
    if pos_id is not None:
        _rec_state.pop(pos_id, None)
        _breakeven_state.pop(pos_id, None)
        _premium_history.pop(pos_id, None)
        _moat_zone_state.pop(pos_id, None)
        _escalation_state.pop(pos_id, None)
    else:
        _rec_state.clear()
        _breakeven_state.clear()
        _drift_history.clear()
        _premium_history.clear()
        _moat_zone_state.clear()
        _escalation_state.clear()


def _compute_time_pressure() -> dict:
    """Calculates 0DTE time pressure based on hours until market close (4 PM ET)."""
    now_et = datetime.now(ZoneInfo("America/New_York"))
    market_close = now_et.replace(hour=MARKET_CLOSE_HOUR_ET, minute=0, second=0, microsecond=0)
    hours_remaining = max(0, (market_close - now_et).total_seconds() / 3600)

    if hours_remaining <= 0:
        level, label = "CLOSED", "Market closed"
        moat_multiplier = 1.0
    elif now_et.hour >= GAMMA_ACCELERATION_HOUR_ET:
        level, label = "HIGH", f"GAMMA RAMP: {hours_remaining:.1f}h to close. Tighten risk."
        moat_multiplier = FINAL_HOUR_MOAT_MULTIPLIER
    elif now_et.hour >= 12:
        level, label = "MODERATE", f"{hours_remaining:.1f}h to close. Midday — monitor."
        moat_multiplier = 1.2
    else:
        level, label = "LOW", f"{hours_remaining:.1f}h to close. Morning — theta working."
        moat_multiplier = 1.0

    # Phase 8: Intraday time window classification
    intraday_window = _classify_intraday_window(now_et)

    # Phase 10: Calendar/event awareness
    market_events = _check_market_events(now_et)

    return {
        "hours_remaining": round(hours_remaining, 2),
        "time_pressure_level": level,
        "time_pressure_label": label,
        "moat_multiplier": moat_multiplier,
        "intraday_window": intraday_window,
        "market_events": market_events,
    }


def _check_market_events(now_et: datetime) -> dict:
    """
    Phase 10: Calendar/event awareness.
    Checks if today is a known high-volatility event day.
    Returns event info and moat multiplier adjustment.
    """
    today = now_et.date()
    month, day, weekday = today.month, today.day, today.weekday()  # 0=Mon

    events = []
    moat_multiplier = 1.0
    risk_level = "NORMAL"

    # --- FOMC Meeting Days (2026 schedule - 8 meetings) ---
    # Dates: Jan 28-29, Mar 18-19, May 6-7, Jun 17-18, Jul 29-30, Sep 16-17, Nov 4-5, Dec 16-17
    fomc_dates_2026 = [
        (1, 28), (1, 29), (3, 18), (3, 19), (5, 6), (5, 7),
        (6, 17), (6, 18), (7, 29), (7, 30), (9, 16), (9, 17),
        (11, 4), (11, 5), (12, 16), (12, 17),
    ]
    if (month, day) in fomc_dates_2026:
        events.append("FOMC Meeting Day")
        moat_multiplier = max(moat_multiplier, 1.4)
        risk_level = "ELEVATED"

    # --- FOMC Minutes Release (~3 weeks after each meeting, at 2:00 PM ET) ---
    # These cause sharp intraday vol spikes around 2 PM. Different from meeting days.
    fomc_minutes_dates_2026 = [
        (2, 19), (4, 9), (5, 28), (7, 9), (8, 20), (10, 8), (11, 25),
    ]
    if (month, day) in fomc_minutes_dates_2026:
        now_hour = now_et.hour + now_et.minute / 60
        events.append("FOMC Minutes Release (2:00 PM ET) — expect vol spike")
        moat_multiplier = max(moat_multiplier, 1.3)
        risk_level = "ELEVATED"
        # Extra warning if approaching or past 2 PM
        if 13.5 <= now_hour <= 14.5:
            events.append("IMMINENT: FOMC Minutes in next 30 min — widen moats")
            moat_multiplier = max(moat_multiplier, 1.5)
            risk_level = "HIGH"

    # --- CPI Release (typically 2nd or 3rd Tuesday/Wednesday of the month) ---
    # Major months: Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec
    # We flag the 10th-15th of each month as potential CPI window
    if 10 <= day <= 15 and weekday in (1, 2):  # Tue/Wed
        events.append("Potential CPI Release Window")
        moat_multiplier = max(moat_multiplier, 1.3)
        risk_level = "ELEVATED"

    # --- NFP (Non-Farm Payrolls) — First Friday of each month ---
    if weekday == 4 and day <= 7:
        events.append("NFP Release Day (First Friday)")
        moat_multiplier = max(moat_multiplier, 1.3)
        risk_level = "ELEVATED"

    # --- PCE (Personal Consumption Expenditures) — typically last Friday of month ---
    if weekday == 4 and 25 <= day <= 31:
        events.append("Potential PCE Release — Fed's preferred inflation gauge")
        moat_multiplier = max(moat_multiplier, 1.2)
        if risk_level == "NORMAL":
            risk_level = "MODERATE"

    # --- Monthly OPEX (Options Expiration) — Third Friday ---
    if weekday == 4 and 15 <= day <= 21:
        events.append("Monthly OPEX — Gamma Pinning Effects")
        moat_multiplier = max(moat_multiplier, 1.15)
        if risk_level == "NORMAL":
            risk_level = "MODERATE"

    # --- Quarterly OPEX (Triple/Quad Witching) — Third Friday of Mar, Jun, Sep, Dec ---
    if weekday == 4 and 15 <= day <= 21 and month in (3, 6, 9, 12):
        events.append("QUARTERLY OPEX — Max Gamma / Pin Risk")
        moat_multiplier = max(moat_multiplier, 1.5)
        risk_level = "HIGH"

    # --- Monday effect: continuation from Friday moves ---
    if weekday == 0:
        events.append("Monday — gap risk from weekend news")
        moat_multiplier = max(moat_multiplier, 1.1)

    # --- Friday 0DTE — most liquid, tightest spreads ---
    if weekday == 4:
        events.append("Friday 0DTE — maximum liquidity")

    if not events:
        events.append("No special events detected")

    return {
        "events": events,
        "moat_multiplier": round(moat_multiplier, 2),
        "risk_level": risk_level,
        "day_of_week": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][weekday],
    }


def _classify_intraday_window(now_et: datetime) -> dict:
    """
    Phase 8: Classifies the current time into known intraday behavioral windows.
    Returns window name, risk characteristics, and entry quality score (0-100).
    """
    hour, minute = now_et.hour, now_et.minute
    t = hour + minute / 60  # decimal time

    if t < 9.5:  # Pre-market
        return {
            "window": "PRE_MARKET",
            "label": "Pre-Market",
            "description": "Market not yet open.",
            "entry_quality": 0,
            "volatility_tendency": "n/a",
            "advice": "Wait for open.",
        }
    elif t < 10.0:  # 9:30 - 10:00
        return {
            "window": "OPENING_DRIVE",
            "label": "Opening Drive",
            "description": "High volatility, false breakouts common. Spreads widest.",
            "entry_quality": 20,
            "volatility_tendency": "ELEVATED",
            "advice": "Avoid new entries. Let the opening range establish. Watch for fakeouts.",
        }
    elif t < 11.5:  # 10:00 - 11:30
        return {
            "window": "TREND_ESTABLISHMENT",
            "label": "Trend Establishment",
            "description": "Directional bias forms. Best entry window for 0DTE.",
            "entry_quality": 90,
            "volatility_tendency": "MODERATE",
            "advice": "Prime entry window. Regime signal most reliable. Deploy with confidence.",
        }
    elif t < 13.0:  # 11:30 - 1:00
        return {
            "window": "LUNCH_LULL",
            "label": "Lunch Lull",
            "description": "Lower volume, tighter ranges, choppy. Good for tight iron condors.",
            "entry_quality": 65,
            "volatility_tendency": "LOW",
            "advice": "Lower risk entries. Range-bound strategies favored. Tighter moats acceptable.",
        }
    elif t < 14.5:  # 1:00 - 2:30
        return {
            "window": "AFTERNOON_SESSION",
            "label": "Afternoon Session",
            "description": "Trend resumption or reversal. Institutional rebalancing begins.",
            "entry_quality": 55,
            "volatility_tendency": "MODERATE",
            "advice": "Caution on new entries. Watch for trend reversal signals. Close weak positions.",
        }
    elif t < 15.0:  # 2:30 - 3:00
        return {
            "window": "PRE_POWER_HOUR",
            "label": "Pre-Power Hour",
            "description": "Institutional positioning. Gamma acceleration beginning.",
            "entry_quality": 25,
            "volatility_tendency": "RISING",
            "advice": "Avoid new positions. Manage existing. Tighten risk on warning-zone positions.",
        }
    elif t < 15.75:  # 3:00 - 3:45
        return {
            "window": "POWER_HOUR",
            "label": "Power Hour",
            "description": "Maximum volume. Gamma dominates. Fast moves, fast reversals.",
            "entry_quality": 10,
            "volatility_tendency": "HIGH",
            "advice": "NO new entries. Hold safe positions for expiry. Time-gated stops only.",
        }
    elif t < 16.0:  # 3:45 - 4:00
        return {
            "window": "FINAL_MINUTES",
            "label": "Final Minutes",
            "description": "Theta nuclear. Pin risk. Last chance to close unsafe positions.",
            "entry_quality": 0,
            "volatility_tendency": "EXTREME_THETA",
            "advice": "Let winners expire. Close anything in WARNING zone at market. Theta dominant.",
        }
    else:
        return {
            "window": "AFTER_HOURS",
            "label": "After Hours",
            "description": "Market closed.",
            "entry_quality": 0,
            "volatility_tendency": "n/a",
            "advice": "Review closed positions. Prepare for next session.",
        }


def _compute_momentum_context(df: pd.DataFrame) -> dict:
    """
    Analyzes recent bar history (1h and 2h lookback) to detect
    trends that the current-snapshot indicators may miss.
    """
    close = df['Close']
    current_close = close.iloc[-1]

    # 2-hour lookback (24 five-minute bars)
    lookback_2h = min(24, len(df) - 1)
    close_2h_ago = close.iloc[-(lookback_2h + 1)]
    change_2h_pct = ((current_close - close_2h_ago) / close_2h_ago) * 100
    change_2h_pts = (current_close - close_2h_ago) * 10  # approx SPX points

    # 1-hour lookback (12 five-minute bars)
    lookback_1h = min(12, len(df) - 1)
    close_1h_ago = close.iloc[-(lookback_1h + 1)]
    change_1h_pct = ((current_close - close_1h_ago) / close_1h_ago) * 100

    # RSI trajectory (how RSI has moved over 2h)
    rsi_delta_2h = 0.0
    if 'RSI_14' in df.columns and len(df) > lookback_2h:
        rsi_now = df['RSI_14'].iloc[-1]
        rsi_2h = df['RSI_14'].iloc[-(lookback_2h + 1)]
        rsi_delta_2h = rsi_now - rsi_2h

    # Intraday range: where is price relative to today's high/low?
    has_hl = 'High' in df.columns and 'Low' in df.columns
    if has_hl:
        try:
            last_ts = df.index[-1]
            if hasattr(last_ts, 'date'):
                today = last_ts.date() if not hasattr(last_ts, 'tz_convert') else last_ts.tz_convert('America/New_York').date()
            else:
                today = None
            if today:
                today_mask = df.index.map(lambda t: t.date() if not hasattr(t, 'tz_convert') else t.tz_convert('America/New_York').date()) == today
                today_bars = df[today_mask]
            else:
                today_bars = df.tail(78)
        except Exception:
            today_bars = df.tail(78)
        day_high = round(float(today_bars['High'].max()), 2)
        day_low = round(float(today_bars['Low'].min()), 2)
    else:
        day_high = round(float(close.max()), 2)
        day_low = round(float(close.min()), 2)

    day_range = day_high - day_low
    range_position = round(((current_close - day_low) / day_range) * 100, 1) if day_range > 0 else 50.0

    # Momentum label
    if change_2h_pct < -0.5:
        label = "SELLOFF RECOVERY" if change_1h_pct > 0.1 else "ACTIVE SELLOFF"
    elif change_2h_pct > 0.5:
        label = "FADING RALLY" if change_1h_pct < -0.1 else "ACTIVE RALLY"
    elif abs(change_2h_pct) < 0.15:
        label = "RANGEBOUND"
    else:
        label = "MILD DRIFT UP" if change_2h_pct > 0 else "MILD DRIFT DOWN"

    return {
        "change_1h_pct": round(change_1h_pct, 3),
        "change_2h_pct": round(change_2h_pct, 3),
        "change_2h_spx_pts": round(change_2h_pts, 1),
        "rsi_delta_2h": round(rsi_delta_2h, 2),
        "day_high_spy": day_high,
        "day_low_spy": day_low,
        "range_position": range_position,
        "momentum_label": label,
    }


def _compute_regime_transition(df: pd.DataFrame, chop_col: str, er_col: str,
                                current_continuous_score: float) -> dict:
    """
    Phase 8b: Predicts regime transition by comparing sub-scores now vs 30 min ago.
    Uses rate-of-change in CHOP, ER, and continuous_score to forecast state shift.
    6 bars back = 30 min at 5-min intervals.
    """
    lookback = 6  # 30 min
    if len(df) < lookback + 1:
        return {
            "direction": "STABLE",
            "label": "Insufficient data",
            "confidence": 0.0,
            "score_delta_30m": 0.0,
            "er_trend": "n/a",
            "chop_trend": "n/a",
        }

    past = df.iloc[-(lookback + 1)]
    latest = df.iloc[-1]

    # Compute past sub-scores the same way
    past_chop = past[chop_col] if chop_col and chop_col in past.index else 50.0
    past_er = past[er_col] if er_col and er_col in past.index else 0.5
    past_rsi = past['RSI_14'] if 'RSI_14' in past.index else 50.0
    past_close = past['Close']
    past_ema9 = past['EMA_9'] if 'EMA_9' in past.index else past_close
    past_ema21 = past['EMA_21'] if 'EMA_21' in past.index else past_close

    past_chop_i = max(0.0, min(1.0, (past_chop - 38.2) / (61.8 - 38.2)))
    past_er_i = max(0.0, min(1.0, (0.50 - past_er) / 0.30))
    past_rsi_i = max(0.0, 1.0 - abs(past_rsi - 50.0) / 15.0)
    past_ema_diff = abs(past_ema9 - past_ema21)
    past_ema_thresh = past_close * EMA_COMPRESSION_THRESHOLD_PCT
    past_ema_i = max(0.0, min(1.0, 1.0 - (past_ema_diff / (past_ema_thresh * 3))))

    past_continuous = past_chop_i + past_er_i + past_rsi_i + past_ema_i

    # Delta: positive = becoming choppier, negative = becoming trendier
    score_delta = round(current_continuous_score - past_continuous, 3)

    # ER trend (key signal: rising ER = trend forming, falling = chop incoming)
    now_er = latest[er_col] if er_col and er_col in latest.index else 0.5
    er_delta = round(now_er - past_er, 4)
    if er_delta > 0.05:
        er_trend = "RISING"
    elif er_delta < -0.05:
        er_trend = "FALLING"
    else:
        er_trend = "FLAT"

    # CHOP trend
    now_chop = latest[chop_col] if chop_col and chop_col in latest.index else 50.0
    chop_delta = round(now_chop - past_chop, 2)
    if chop_delta > 3:
        chop_trend = "RISING"
    elif chop_delta < -3:
        chop_trend = "FALLING"
    else:
        chop_trend = "FLAT"

    # Transition direction and confidence
    if score_delta > 0.5:
        direction = "DETERIORATING"
        label = "Regime degrading → chop increasing. Widen moats."
        confidence = min(0.95, 0.5 + abs(score_delta) * 0.3)
    elif score_delta > 0.2:
        direction = "SOFTENING"
        label = "Trend weakening. Monitor for State transition."
        confidence = min(0.80, 0.4 + abs(score_delta) * 0.3)
    elif score_delta < -0.5:
        direction = "IMPROVING"
        label = "Regime improving → trend strengthening. Tighter moats viable."
        confidence = min(0.95, 0.5 + abs(score_delta) * 0.3)
    elif score_delta < -0.2:
        direction = "FIRMING"
        label = "Chop resolving. Directional signal forming."
        confidence = min(0.80, 0.4 + abs(score_delta) * 0.3)
    else:
        direction = "STABLE"
        label = "Regime stable. No imminent transition."
        confidence = 0.3

    return {
        "direction": direction,
        "label": label,
        "confidence": round(confidence, 2),
        "score_delta_30m": score_delta,
        "er_trend": er_trend,
        "chop_trend": chop_trend,
    }


def analyze_market_regime(df: pd.DataFrame) -> dict:
    """Enhanced Regime Classifier V4.0: Continuous sub-scores + directional bias + momentum + transition prediction."""
    latest = df.iloc[-1]
    close = latest['Close']
    ema_9 = latest['EMA_9']
    ema_21 = latest['EMA_21']
    rsi = latest['RSI_14']

    chop_col = next((col for col in latest.index if 'CHOP' in col), None)
    er_col = next((col for col in latest.index if 'ER' in col), None)
    chop = latest[chop_col] if chop_col else 50.0
    er = latest[er_col] if er_col else 0.5

    vwap_col = next((col for col in latest.index if col.startswith('VWAP') and col != 'VWAP_BAR'), None)
    vwap_val = latest[vwap_col] if vwap_col else close
    vwap_deviation_pct = (abs(close - vwap_val) / vwap_val) * 100

    # --- Binary score (determines state routing, backward compatible) ---
    regime_score = 0
    if chop > CHOP_THRESHOLD: regime_score += 1
    if er < EFFICIENCY_RATIO_THRESHOLD: regime_score += 1
    if RSI_DEAD_ZONE_LOWER <= rsi <= RSI_DEAD_ZONE_UPPER: regime_score += 1
    ema_diff = abs(ema_9 - ema_21)
    if ema_diff < (close * EMA_COMPRESSION_THRESHOLD_PCT): regime_score += 1

    # --- Continuous sub-scores (0.0 = perfectly trending, 1.0 = max chop) ---
    # CHOP: linear ramp from 38.2 (strong trend) to 61.8 (max chop)
    chop_intensity = round(max(0.0, min(1.0, (chop - 38.2) / (61.8 - 38.2))), 3)
    # ER: inverted — 0.50+ = efficient, 0.0 = total noise
    er_intensity = round(max(0.0, min(1.0, (0.50 - er) / 0.30)), 3)
    # RSI: peaks at 50 (dead center), fades toward 35/65
    rsi_intensity = round(max(0.0, 1.0 - abs(rsi - 50.0) / 15.0), 3)
    # EMA: compression relative to threshold
    ema_threshold = close * EMA_COMPRESSION_THRESHOLD_PCT
    ema_intensity = round(max(0.0, min(1.0, 1.0 - (ema_diff / (ema_threshold * 3)))), 3)

    continuous_score = round(chop_intensity + er_intensity + rsi_intensity + ema_intensity, 2)

    # --- Phase 8b: Regime Transition Prediction ---
    # Compare sub-scores now vs 30 min ago (6 bars @ 5-min) to detect regime shifts
    regime_transition = _compute_regime_transition(df, chop_col, er_col, continuous_score)

    # --- Momentum context (historical lookback) ---
    momentum = _compute_momentum_context(df)

    # --- Directional Bias (snapshot + momentum) ---
    if close > ema_9 > ema_21 and rsi > 55:
        directional_bias = "BULLISH"
    elif close < ema_9 < ema_21 and rsi < 45:
        directional_bias = "BEARISH"
    elif close > ema_21 and rsi > 50:
        directional_bias = "LEAN BULLISH"
    elif close < ema_21 and rsi < 50:
        directional_bias = "LEAN BEARISH"
    else:
        directional_bias = "NEUTRAL"

    # Override: if current indicators look neutral but recent history shows a
    # strong move, use momentum to augment the bias. This catches the case
    # where RSI has mean-reverted after a selloff but the move just happened.
    if directional_bias == "NEUTRAL":
        if momentum["change_2h_pct"] < -0.3:
            directional_bias = "LEAN BEARISH"
        elif momentum["change_2h_pct"] > 0.3:
            directional_bias = "LEAN BULLISH"
    # Escalate lean to full if momentum strongly confirms
    if directional_bias == "LEAN BEARISH" and momentum["change_2h_pct"] < -0.5:
        directional_bias = "BEARISH"
    elif directional_bias == "LEAN BULLISH" and momentum["change_2h_pct"] > 0.5:
        directional_bias = "BULLISH"

    # --- State routing ---
    if regime_score <= 1:
        state = "STATE A: TRENDING"
        moat_label, stop = "35-40 Points", "Strict 200% Premium Hit"
        recommended_moat_min = STATE_A_MIN_MOAT
    elif regime_score == 2:
        state = "STATE B: MODERATE CHOP"
        moat_label, stop = "50-60 Points", "250% Premium OR 15-pt Asset Breach"
        recommended_moat_min = STATE_B_MIN_MOAT
    else:
        state = "STATE C: HIGH ENTROPY / WHIPSAW"
        moat_label, stop = "70+ Points", "Strict Asset Boundary ONLY (Ignore premium spikes)"
        recommended_moat_min = STATE_C_MIN_MOAT

    if vwap_deviation_pct > VWAP_ELASTICITY_THRESHOLD_PCT:
        state = state + " [OVERRIDE: MAX ELASTICITY]"
        stop = "SUSPEND STOPS. Wait 10 mins for Mean Reversion Bounce, then Eject."

    # --- Time pressure ---
    time_pressure = _compute_time_pressure()
    effective_moat_min = round(recommended_moat_min * time_pressure["moat_multiplier"])

    return {
        "regime_state": state, "regime_score": regime_score,
        "continuous_score": continuous_score,
        "recommended_moat": moat_label, "stop_loss_rule": stop,
        "recommended_moat_min": recommended_moat_min,
        "effective_moat_min": effective_moat_min,
        "chop_value": round(chop, 2), "er_value": round(er, 2),
        "vwap_dev": round(vwap_deviation_pct, 3),
        "directional_bias": directional_bias,
        "sub_scores": {
            "chop_intensity": chop_intensity,
            "er_intensity": er_intensity,
            "rsi_intensity": rsi_intensity,
            "ema_intensity": ema_intensity,
        },
        "time_pressure": time_pressure,
        "momentum": momentum,
        "regime_transition": regime_transition,
    }


def compute_smart_moat(regime_data: dict, spx_price: float,
                        day_high_spx: float, day_low_spx: float,
                        range_position: float,
                        vix_based_moat: float = None,
                        gex_data: dict = None) -> dict:
    """
    PHASE 4: Smart Moat System.
    Adjusts the effective moat based on:
    1. Range context: contained chop vs expanding range
    2. Signal quality: dead market (ER near 0) vs directional signal
    3. Time decay: positions that survived the day deserve lower moat
    4. Range exhaustion: if price tested both extremes and returned to center
    5. (Phase 7) VIX-based expected move: replaces static base moat with math-grounded value
    6. (Phase 9) GEX regime: positive GEX (mean-reverting) tightens, negative widens
    Returns enriched regime data with smart_moat fields.
    """
    regime_score = regime_data["regime_score"]
    continuous_score = regime_data["continuous_score"]
    regime_base_moat = regime_data["effective_moat_min"]
    # If VIX data available, use it as base; otherwise fall back to regime table
    base_moat = round(vix_based_moat) if vix_based_moat is not None else regime_base_moat
    er_value = regime_data["er_value"]
    hours = regime_data["time_pressure"]["hours_remaining"]

    day_range = day_high_spx - day_low_spx if day_high_spx > day_low_spx else 0

    # ---- 1. RANGE CONTEXT ----
    # How wide is the day's range relative to what we'd expect?
    # In State C, a 50-pt range is "contained", 80+ is "normal", 120+ is "expanding"
    if day_range < 40:
        range_context = "TIGHT"
        range_moat_factor = 0.70  # chop is in a small box, safe
    elif day_range < 70:
        range_context = "CONTAINED"
        range_moat_factor = 0.85  # moderate range, somewhat safe
    elif day_range < 110:
        range_context = "NORMAL"
        range_moat_factor = 1.0   # standard moat applies
    else:
        range_context = "EXPANDING"
        range_moat_factor = 1.15  # wide swings, need more buffer

    # ---- 2. SIGNAL QUALITY ----
    # ER < 0.05 = absolute noise, no directional threat forming
    # ER 0.05-0.15 = weak signal, potential move brewing
    # ER > 0.15 = directional signal present
    if er_value < 0.05 and continuous_score > 3.5:
        signal_quality = "DEAD"
        signal_moat_factor = 0.80  # no signal = lower threat
    elif er_value < 0.10:
        signal_quality = "NOISE"
        signal_moat_factor = 0.90
    elif er_value < 0.20:
        signal_quality = "WEAK"
        signal_moat_factor = 1.0
    else:
        signal_quality = "DIRECTIONAL"
        signal_moat_factor = 1.10  # actual trend forming, need more room

    # ---- 3. TIME-DECAY SURVIVAL CREDIT ----
    # Positions that have survived State C for hours deserve a lower moat.
    # At open (6.5h), full moat. Each hour survived reduces requirement.
    # At 2h left, theta is aggressively decaying premium.
    if hours <= 1.0:
        time_moat_factor = 0.55  # theta crushing, minimal moat needed
    elif hours <= 2.0:
        time_moat_factor = 0.65
    elif hours <= 3.0:
        time_moat_factor = 0.75
    elif hours <= 4.5:
        time_moat_factor = 0.85
    else:
        time_moat_factor = 1.0  # morning, full moat

    # ---- 4. RANGE EXHAUSTION ----
    # If price has tested both extremes and returned to middle third,
    # the range is "established" — less likely to break out.
    mid_zone = 30 <= range_position <= 70
    tested_both = (day_high_spx - spx_price > 15) and (spx_price - day_low_spx > 15)
    range_exhausted = mid_zone and tested_both and day_range > 30
    exhaustion_factor = 0.90 if range_exhausted else 1.0

    # ---- 5. CALENDAR EVENT FACTOR ----
    # FOMC, CPI, NFP, OPEX days require wider moats
    market_events = regime_data["time_pressure"].get("market_events", {})
    event_factor = market_events.get("moat_multiplier", 1.0)

    # ---- 6. GEX REGIME FACTOR ----
    # Positive GEX = dealers long gamma = mean-reverting = tighter moat OK
    # Negative GEX = dealers short gamma = trending/volatile = widen moat
    # Scale factor by net_gex magnitude for granularity
    gex_factor = 1.0
    gex_label = "N/A"
    if gex_data and gex_data.get("gex_regime") not in (None, "UNAVAILABLE"):
        gex_regime = gex_data["gex_regime"]
        net_gex = gex_data.get("net_gex", 0)

        if gex_regime == "POSITIVE":
            # Scale: small positive = 0.95, large positive = 0.85
            gex_strength = min(1.0, abs(net_gex) / 500000)  # normalize to 0-1
            gex_factor = 0.95 - gex_strength * 0.10  # 0.95 → 0.85
            gex_label = f"POSITIVE (×{gex_factor:.2f})"
        elif gex_regime == "NEGATIVE":
            # Scale: mild negative = 1.10, extreme negative = 1.25
            gex_strength = min(1.0, abs(net_gex) / 500000)
            gex_factor = 1.10 + gex_strength * 0.15  # 1.10 → 1.25
            gex_label = f"NEGATIVE (×{gex_factor:.2f})"
        else:
            gex_label = "NEUTRAL"

    # ---- COMBINE FACTORS ----
    # Apply all factors to the base moat, with a floor
    combined_factor = range_moat_factor * signal_moat_factor * time_moat_factor * exhaustion_factor * event_factor * gex_factor
    smart_moat = max(WARNING_ZONE_THRESHOLD + 5, round(base_moat * combined_factor))

    # Build explanation for the UI
    adjustments = []
    if range_moat_factor != 1.0:
        direction = "reduced" if range_moat_factor < 1 else "increased"
        adjustments.append(f"Range {range_context.lower()} ({direction})")
    if signal_moat_factor != 1.0:
        direction = "reduced" if signal_moat_factor < 1 else "increased"
        adjustments.append(f"Signal {signal_quality.lower()} ({direction})")
    if time_moat_factor != 1.0:
        adjustments.append(f"{hours:.1f}h survived (theta credit)")
    if range_exhausted:
        adjustments.append("Range exhausted (mid-range reversion)")
    if event_factor > 1.0:
        adjustments.append(f"Event day ×{event_factor} ({market_events.get('risk_level', 'ELEVATED')})")
    if gex_factor != 1.0:
        direction = "tightened" if gex_factor < 1 else "widened"
        adjustments.append(f"GEX {gex_label}")

    vix_note = f" (VIX-based)" if vix_based_moat is not None else f" (regime)"
    moat_explanation = (
        f"Base {base_moat} pts{vix_note} → Smart {smart_moat} pts"
        + (f" [{', '.join(adjustments)}]" if adjustments else "")
    )

    return {
        "smart_moat": smart_moat,
        "base_moat": base_moat,
        "moat_explanation": moat_explanation,
        "range_context": range_context,
        "signal_quality": signal_quality,
        "range_exhausted": range_exhausted,
        "combined_factor": round(combined_factor, 3),
        "gex_factor": gex_factor,
        "gex_label": gex_label,
    }


def evaluate_positions(db_positions, spx_price: float, db_session,
                       regime_score: int = 0, effective_moat_min: int = 35,
                       directional_bias: str = "NEUTRAL",
                       range_position: float = 50.0,
                       day_high_spx: float = 0.0, day_low_spx: float = 0.0,
                       hours_remaining: float = 6.5,
                       momentum_label: str = "",
                       vwap_dev: float = 0.0,
                       gex_data: dict = None):
    """
    PHASE 3.2: Enhanced Position Intelligence.
    - Calculates live moats and handles Time-Delayed Verification stops.
    - Applies regime-aware tiered stop rules (side-aware).
    - CAUTION zone when moat is below the regime's recommended minimum.
    - Directional risk flags (bearish bias → puts at higher risk).
    - Range proximity: price near day high/low amplifies risk for the exposed side.
    - IV proxy: inflates premium estimates during strong moves, high VWAP dev, range extremes.
    """
    evaluated = []

    # Record SPX price for cumulative drift tracking
    _update_drift_tracker(spx_price)

    # Market-close awareness: when hours_remaining <= 0, positions have expired
    market_closed = hours_remaining <= 0

    # Range proximity flags (where is SPX in today's high-low range?)
    near_day_low = range_position < 20.0   # bottom 20% of day's range
    near_day_high = range_position > 80.0  # top 20% of day's range

    for pos in db_positions:
        # --- MARKET CLOSED: Show expired state ---
        if market_closed:
            if pos.type == 'Put Spread':
                moat = spx_price - pos.strike
            elif pos.type == 'Call Spread':
                moat = pos.strike - spx_price
            else:
                moat = abs(spx_price - pos.strike)

            expired_itm = moat <= 0
            moat_pct = max(0, min(100, (moat / MOAT_BAR_SCALE) * 100))

            if expired_itm:
                estimated_pl = round(-pos.credit * 9, 2)  # max loss on $5-wide spread
                message = f"EXPIRED IN-THE-MONEY. Max loss realized. SPX closed past strike."
                status_color = "text-red-500 font-bold"
                bar_color = "bg-red-500"
            else:
                estimated_pl = round(pos.credit, 2)  # full credit retained
                message = f"EXPIRED WORTHLESS ✓ Full credit ${pos.credit:.2f} retained."
                status_color = "text-emerald-400 font-semibold"
                bar_color = "bg-emerald-500"

            evaluated.append({
                "id": pos.id,
                "type": pos.type,
                "strike": pos.strike,
                "credit": pos.credit,
                "moat": round(moat, 1),
                "moat_pct": moat_pct,
                "status_color": status_color,
                "bar_color": bar_color,
                "message": message,
                "at_risk_side": False,
                "estimated_pl": estimated_pl,
                "estimated_buyback": 0.0,
                "exit_strategy": {
                    "action": "EXPIRED",
                    "target_price": None,
                    "trigger_spx": None,
                    "monitor_minutes": 0,
                    "instruction": "Market closed. Position expired. Move to closed trades.",
                },
            })
            continue
        # 1. Moat Calculation
        if pos.type == 'Put Spread':
            moat = spx_price - pos.strike
        elif pos.type == 'Call Spread':
            moat = pos.strike - spx_price
        else:
            moat = abs(spx_price - pos.strike)  # Iron Condor proxy

        status_color = "text-slate-400"
        bar_color = "bg-slate-600"
        message = "Calculating..."

        # 2. Directional risk: is this position on the at-risk side?
        at_risk_side = False
        if pos.type == 'Put Spread' and directional_bias in ("BEARISH", "LEAN BEARISH"):
            at_risk_side = True
        elif pos.type == 'Call Spread' and directional_bias in ("BULLISH", "LEAN BULLISH"):
            at_risk_side = True

        # 2b. Range proximity risk: price pressing toward your side's extreme
        range_risk = False
        if pos.type == 'Put Spread' and near_day_low:
            range_risk = True
            at_risk_side = True  # override: day-low proximity is a strong signal
        elif pos.type == 'Call Spread' and near_day_high:
            range_risk = True
            at_risk_side = True

        # 3. Zone classification
        if moat <= GAMMA_TRAP_THRESHOLD:
            # --- GAMMA TRAP: All regimes eject ---
            if pos.breach_start_time is None:
                pos.breach_start_time = datetime.now(timezone.utc)
                db_session.commit()
                message = f"WARNING: Gamma Trap. Verification in {BREACH_VERIFICATION_MINUTES} min(s)."
                status_color = "text-amber-500 font-bold"
                bar_color = "bg-amber-500"
                logger.warning(
                    f"Position {pos.id} ({pos.type} {pos.strike}) breached Gamma Trap boundary. Timer started.")
            else:
                # SQLite strips timezone info; ensure both sides are aware
                breach_time = pos.breach_start_time.replace(tzinfo=timezone.utc) if pos.breach_start_time.tzinfo is None else pos.breach_start_time
                elapsed_time = datetime.now(timezone.utc) - breach_time
                if elapsed_time > timedelta(minutes=BREACH_VERIFICATION_MINUTES):
                    message = "CRITICAL EJECT: Trap Verified. Close immediately."
                    status_color = "text-red-500 font-bold animate-pulse"
                    bar_color = "bg-red-500"
                    logger.critical(f"Position {pos.id} ({pos.type} {pos.strike}) KILL SWITCH ACTIVE.")
                else:
                    time_left = BREACH_VERIFICATION_MINUTES - int(elapsed_time.total_seconds() / 60)
                    message = f"WARNING: Gamma Trap. Verification in {time_left} min(s)."
                    status_color = "text-amber-500 font-bold"
                    bar_color = "bg-amber-500"
        else:
            # Whipsaw Immunity: If price recovered, clear the breach timer
            if pos.breach_start_time is not None:
                pos.breach_start_time = None
                db_session.commit()
                logger.info(f"Position {pos.id} ({pos.type} {pos.strike}) recovered. Timer cleared.")

            # Apply hysteresis to prevent zone oscillation
            effective_zone = _apply_moat_hysteresis(
                pos.id, moat, WARNING_ZONE_THRESHOLD, effective_moat_min
            )

            if effective_zone == "WARNING":
                # Time-aware + side-aware stop messages
                if hours_remaining < 0.5:
                    message = "WARNING: Final 30 min — theta dominant. Hold unless strike breached. Ignore premium spikes."
                elif hours_remaining < 1.0:
                    message = "WARNING: Final hour — premium stops suspended. Close only on 10-min sustained breach."
                elif at_risk_side:
                    if regime_score <= 1:
                        message = "WARNING: Trend pushing toward strike. Tight 200% premium stop — close if triggered."
                    elif regime_score == 2:
                        message = "WARNING: At-risk side. Close on 250% premium OR sustained 10-pt breach."
                    else:
                        message = "WARNING: At-risk in whipsaw. Close on any further approach."
                else:
                    if regime_score <= 1:
                        message = "WARNING: Boundary approach. 200% premium stop — trend favors this side."
                    elif regime_score == 2:
                        message = "WARNING: Boundary approach. Hybrid stop: 250% premium OR 15-pt breach."
                    else:
                        message = "WARNING: Boundary approach. Asset-boundary stop ONLY (ignore premium)."
                status_color = "text-amber-400 font-semibold"
                bar_color = "bg-amber-400"

            elif effective_zone == "CAUTION":
                # --- CAUTION: Above warning zone but below recommended moat ---
                deficit = round(effective_moat_min - moat, 1)
                message = f"CAUTION: Moat {deficit} pts below recommended minimum ({effective_moat_min} pts)."
                if range_risk:
                    message += f" SPX near day {'low' if near_day_low else 'high'} — pressing toward strike."
                if at_risk_side and not range_risk:
                    message += f" Bias is {directional_bias} — this side at higher risk."
                status_color = "text-amber-300 font-semibold"
                bar_color = "bg-amber-400"
            else:
                # --- SAFE ---
                if range_risk:
                    # Moat is adequate but price is pressing toward this side's day extreme
                    message = f"SAFE but SPX near day {'low' if near_day_low else 'high'} ({round(range_position)}% range). Monitor actively."
                    status_color = "text-emerald-300 font-medium"
                    bar_color = "bg-emerald-500"
                elif at_risk_side:
                    message = f"SAFE: Theta Decay Active. Note: {directional_bias} bias — monitor."
                    status_color = "text-emerald-400 font-semibold"
                    bar_color = "bg-emerald-500"
                else:
                    message = "SAFE: Theta Decay Active."
                    status_color = "text-emerald-400 font-semibold"
                    bar_color = "bg-emerald-500"

        # ---- GEX WALL PROXIMITY CONTEXT ----
        # Context for SHORT credit spreads: we want price to stay AWAY from our strike.
        # Put wall = support floor (good if ABOVE our put strike).
        # Call wall = resistance ceiling (good if BELOW our call strike).
        gex_context = None
        if gex_data and gex_data.get("gex_regime") not in (None, "UNAVAILABLE"):
            put_wall_spx = gex_data.get("put_wall_spx", 0)
            call_wall_spx = gex_data.get("call_wall_spx", 0)
            gamma_wall_spx = gex_data.get("gamma_wall_spx", 0)

            if pos.type == "Put Spread":
                # For short put spread: put wall ABOVE strike = support protects us
                dist_to_put_wall = abs(pos.strike - put_wall_spx)
                if dist_to_put_wall < 15 and put_wall_spx > 0:
                    if put_wall_spx > pos.strike:
                        # Put wall is ABOVE our strike — dealers support price before reaching us
                        gex_context = f"Put wall at {put_wall_spx} SPX — floor {dist_to_put_wall:.0f} pts above strike. GEX protects this position."
                    else:
                        # Put wall is AT or BELOW our strike — no support above us
                        gex_context = f"Put wall ({put_wall_spx}) at/below strike — no GEX floor protecting position."
                elif spx_price < gamma_wall_spx and gamma_wall_spx > 0:
                    # Price below gamma wall = magnet pulling price back up = good for short puts
                    gex_context = f"Gamma wall {gamma_wall_spx} above SPX — magnet pulls price up, reduces downside risk."
            elif pos.type == "Call Spread":
                # For short call spread: call wall BELOW strike = resistance protects us
                dist_to_call_wall = abs(pos.strike - call_wall_spx)
                if dist_to_call_wall < 15 and call_wall_spx > 0:
                    if call_wall_spx < pos.strike:
                        # Call wall is BELOW our strike — dealers resist price before reaching us
                        gex_context = f"Call wall at {call_wall_spx} SPX — ceiling {dist_to_call_wall:.0f} pts below strike. GEX protects this position."
                    else:
                        # Call wall is AT or ABOVE our strike — no resistance below us
                        gex_context = f"Call wall ({call_wall_spx}) at/above strike — no GEX ceiling protecting position."
                elif spx_price > gamma_wall_spx and gamma_wall_spx > 0:
                    # Price above gamma wall = magnet pulling price back down = good for short calls
                    gex_context = f"Gamma wall {gamma_wall_spx} below SPX — magnet pulls price down, reduces upside risk."

            # Append GEX context to message if we have useful info
            if gex_context:
                message += f" GEX: {gex_context}"

        moat_pct = max(0, min(100, (moat / MOAT_BAR_SCALE) * 100))

        # P/L estimation for 0DTE credit spread
        # Models real-world premium behavior: options near the money with time
        # remaining are worth significantly MORE than credit, not less.
        safety_ratio = max(0, moat) / max(1, effective_moat_min)
        time_factor = hours_remaining / 6.5  # 0=close, 1=open
        time_decay = max(0, 1 - time_factor)

        # --- IV Proxy ---
        # During strong moves, implied volatility spikes and premiums inflate
        # 30-60%+ above static moat-based estimates. We proxy IV from observables.
        iv_multiplier = 1.0

        # 1. Range extremity: SPX near day high inflates call premiums, near low inflates put premiums
        if pos.type == "Call Spread" and range_position > 50:
            range_stress = (range_position - 50) / 50  # 0 at midpoint, 1 at day high
            iv_multiplier += range_stress * 0.4  # up to +40% at day high
        elif pos.type == "Put Spread" and range_position < 50:
            range_stress = (50 - range_position) / 50  # 0 at midpoint, 1 at day low
            iv_multiplier += range_stress * 0.4

        # 2. Momentum: strong directional moves spike IV on the threatened side
        if at_risk_side:
            if "SURGE" in momentum_label or "ACTIVE" in momentum_label:
                iv_multiplier += 0.35  # aggressive move toward this side
            elif "RALLY" in momentum_label or "SELLOFF" in momentum_label:
                iv_multiplier += 0.2   # clear directional pressure
            elif "DRIFT" in momentum_label:
                iv_multiplier += 0.1   # mild but persistent pressure

        # 3. VWAP deviation: high deviation = market extended = elevated IV
        if vwap_dev > 0.3:
            iv_multiplier += min(0.25, (vwap_dev - 0.3) * 0.5)  # up to +25% extra

        if moat <= 0:
            # Strike breached — approaching max loss territory
            buyback_frac = 2.5 + abs(moat) * 0.15 + time_factor * 0.5
        elif moat <= GAMMA_TRAP_THRESHOLD:
            # Gamma trap — spread is deep in danger, premium is expanding
            proximity = 1 - (moat / GAMMA_TRAP_THRESHOLD)  # 0=edge, 1=at strike
            buyback_frac = 1.8 + proximity * 0.8 + time_factor * 0.4
        elif moat <= WARNING_ZONE_THRESHOLD:
            # Warning zone — premium often EXCEEDS credit received
            proximity = 1 - (moat / WARNING_ZONE_THRESHOLD)  # 0=edge, 1=gamma
            buyback_frac = 0.6 + proximity ** 0.7 * 1.5 + time_factor * 0.4
            if at_risk_side:
                buyback_frac += 0.3
        elif safety_ratio >= 1.0:
            # Safe — theta is crushing premium toward zero
            buyback_frac = max(0.03, 0.15 * (1 - time_decay * 0.9))
        else:
            # Caution — moderate risk, some premium remains
            deficit_pct = 1 - safety_ratio
            buyback_frac = 0.15 + deficit_pct * 0.5 + time_factor * 0.15

        # Apply IV proxy to danger zones (safe positions aren't affected by IV spikes)
        if moat < effective_moat_min:
            buyback_frac *= iv_multiplier

        buyback_frac = max(0.02, buyback_frac)
        estimated_buyback = round(pos.credit * buyback_frac, 2)
        estimated_pl = round(pos.credit - estimated_buyback, 2)

        # ---- PREMIUM HISTORY ----
        premium_trend = _update_premium_history(pos.id, estimated_buyback)

        # ---- BREAKEVEN TOUCH DETECTION ----
        breakeven_event = _update_breakeven_state(pos.id, pos.credit, estimated_buyback, estimated_pl)

        # ---- EXIT STRATEGY ----
        # Actionable close/hold recommendation per position
        if pos.type == "Put Spread":
            warning_trigger = pos.strike + WARNING_ZONE_THRESHOLD
            gamma_trigger = pos.strike + GAMMA_TRAP_THRESHOLD
        elif pos.type == "Call Spread":
            warning_trigger = pos.strike - WARNING_ZONE_THRESHOLD
            gamma_trigger = pos.strike - GAMMA_TRAP_THRESHOLD
        else:
            warning_trigger = pos.strike
            gamma_trigger = pos.strike

        # Graduated escalation: track how long position has been in danger
        in_danger = moat <= WARNING_ZONE_THRESHOLD
        esc = _get_escalation_level(pos.id, in_danger)
        esc_level = esc["level"]

        if moat <= 0:
            # Strike breached — immediate exit (bypasses escalation)
            exit_strategy = {
                "action": "CRITICAL_EJECT",
                "target_price": None,
                "trigger_spx": None,
                "monitor_minutes": 0,
                "instruction": f"Strike breached. Close at market immediately.",
                "escalation_level": "CRITICAL_EJECT",
            }
        elif moat <= GAMMA_TRAP_THRESHOLD:
            # Gamma trap — use escalation level for action name
            action = esc_level if esc_level in ("URGENT_CLOSE", "CRITICAL_EJECT") else "CLOSE_NOW"
            exit_strategy = {
                "action": action,
                "target_price": round(pos.credit * 1.2, 2),
                "trigger_spx": None,
                "monitor_minutes": BREACH_VERIFICATION_MINUTES,
                "instruction": (
                    f"Gamma Trap [{esc_level}]. Close at ${pos.credit * 1.2:.2f} or less. "
                    f"If fill unavailable, monitor {BREACH_VERIFICATION_MINUTES} min — "
                    f"auto-eject if SPX stays past {gamma_trigger:.0f}."
                ),
                "escalation_level": esc_level,
            }
        elif moat <= WARNING_ZONE_THRESHOLD:
            # Warning zone — time-aware exit strategies
            # Late in the day, theta decay makes premium stops counterproductive.
            # A position that briefly spikes to 200% at 3:15pm decays to near-zero by 3:50.
            if regime_score >= 3:
                # State C: always close aggressively regardless of time
                exit_strategy = {
                    "action": "CLOSE_SOON",
                    "target_price": round(estimated_buyback, 2),
                    "trigger_spx": gamma_trigger,
                    "monitor_minutes": 5,
                    "instruction": (
                        f"Close at ~${estimated_buyback:.2f}. "
                        f"If SPX {'drops below' if pos.type == 'Put Spread' else 'rises above'} "
                        f"{gamma_trigger:.0f}, close at any price within 5 min."
                    ),
                }
            elif hours_remaining < 0.5:
                # FINAL 30 MIN: Theta is nuclear. Hold unless strike is actually breached.
                # Premium stops are counterproductive — a $1 option decays to $0.05 in 20 min.
                exit_strategy = {
                    "action": "HOLD_FOR_EXPIRY",
                    "target_price": round(estimated_buyback * 0.3, 2),
                    "trigger_spx": pos.strike,  # only exit if strike breached
                    "monitor_minutes": 0,
                    "instruction": (
                        f"Final 30 min — theta dominant. HOLD unless SPX {'drops below' if pos.type == 'Put Spread' else 'rises above'} "
                        f"{pos.strike:.0f} (actual strike). Ignore premium spikes. "
                        f"Expected to decay to ~${estimated_buyback * 0.3:.2f} at expiry."
                    ),
                }
            elif hours_remaining < 1.0:
                # FINAL HOUR: Widen stops, require sustained breach
                # Replace premium stop with time-gated asset-boundary check
                exit_strategy = {
                    "action": "HOLD_WITH_TRIGGER",
                    "target_price": round(estimated_buyback * 0.5, 2),
                    "trigger_spx": gamma_trigger,
                    "monitor_minutes": 10,
                    "instruction": (
                        f"Final hour — theta accelerating. Suspend premium stops. "
                        f"Close ONLY if SPX sustains past {gamma_trigger:.0f} for 10 min. "
                        f"Expected decay to ~${estimated_buyback * 0.5:.2f} if SPX stabilizes."
                    ),
                }
            elif hours_remaining < 2.0:
                # 1-2 HOURS: Extend stops + require 5-min verification
                premium_stop = round(pos.credit * 2.5, 2)  # 250% regardless of state
                exit_strategy = {
                    "action": "CLOSE_SOON",
                    "target_price": round(min(estimated_buyback, premium_stop), 2),
                    "trigger_spx": gamma_trigger,
                    "monitor_minutes": 5,
                    "instruction": (
                        f"Close at ~${estimated_buyback:.2f} or 250% stop (${premium_stop:.2f}). "
                        f"Require 5-min sustained breach of {gamma_trigger:.0f} before exit — "
                        f"spikes often revert with {hours_remaining:.1f}h left."
                    ),
                }
            else:
                # >2 HOURS: Standard premium stops
                premium_stop = round(pos.credit * 2.0 if regime_score <= 1 else pos.credit * 2.5, 2)
                exit_strategy = {
                    "action": "CLOSE_SOON",
                    "target_price": round(min(estimated_buyback, premium_stop), 2),
                    "trigger_spx": gamma_trigger,
                    "monitor_minutes": 5,
                    "instruction": (
                        f"Close at ~${estimated_buyback:.2f} or if premium hits "
                        f"${premium_stop:.2f} ({'200%' if regime_score <= 1 else '250%'} stop)."
                    ),
                }
        elif moat < effective_moat_min:
            # Caution zone — hold but set conditional exit
            exit_strategy = {
                "action": "HOLD_WITH_TRIGGER",
                "target_price": round(estimated_buyback * 0.5, 2),
                "trigger_spx": warning_trigger,
                "monitor_minutes": 10,
                "instruction": (
                    f"Hold. Close at ${estimated_buyback * 0.5:.2f} to lock profit. "
                    f"If SPX {'drops to' if pos.type == 'Put Spread' else 'rises to'} "
                    f"{warning_trigger:.0f}, close within 10 min at ~${estimated_buyback:.2f}."
                ),
            }
        else:
            # Safe zone — let theta work
            if hours_remaining < 1.0:
                exit_strategy = {
                    "action": "LET_EXPIRE",
                    "target_price": 0.05,
                    "trigger_spx": warning_trigger,
                    "monitor_minutes": 0,
                    "instruction": (
                        f"Let expire. Close at $0.05 if available to lock ${pos.credit - 0.05:.2f} profit."
                    ),
                }
            elif hours_remaining < 2.5:
                exit_strategy = {
                    "action": "LET_EXPIRE",
                    "target_price": 0.05,
                    "trigger_spx": warning_trigger,
                    "monitor_minutes": 0,
                    "instruction": (
                        f"Theta accelerating. Hold for expiry. "
                        f"Close at $0.05-0.10 if offered."
                    ),
                }
            else:
                target = round(max(0.05, estimated_buyback * 0.3), 2)
                exit_strategy = {
                    "action": "HOLD",
                    "target_price": target,
                    "trigger_spx": warning_trigger,
                    "monitor_minutes": 0,
                    "instruction": (
                        f"Safe. Hold for theta decay. "
                        f"Book profit at ${target:.2f} if available. "
                        f"Alert if SPX {'drops to' if pos.type == 'Put Spread' else 'rises to'} "
                        f"{warning_trigger:.0f}."
                    ),
                }

        # Add escalation level to exit strategy if not already set
        if "escalation_level" not in exit_strategy:
            exit_strategy["escalation_level"] = esc_level

        # ---- RECOMMENDATION PERSISTENCE ----
        # Apply cooldown + hysteresis to prevent flip-flopping
        rec_state = _update_rec_state(pos.id, exit_strategy["action"], moat)
        if rec_state["action"] != exit_strategy["action"]:
            # Cooldown overrode the action — keep the previous CLOSE signal
            exit_strategy["action"] = rec_state["action"]
            exit_strategy["instruction"] = (
                f"[COOLDOWN ACTIVE — {rec_state['cooldown_remaining_min']:.0f} min remaining] "
                + exit_strategy["instruction"]
            )
        exit_strategy["signal_age"] = rec_state["signal_age"]
        exit_strategy["signal_stability"] = rec_state["signal_stability"]

        # ---- CUMULATIVE DRIFT CHECK ----
        drift_alert = compute_drift_toward_strike(pos.strike, pos.type)

        evaluated.append({
            "id": pos.id,
            "type": pos.type,
            "strike": pos.strike,
            "credit": pos.credit,
            "moat": round(moat, 1),
            "moat_pct": moat_pct,
            "status_color": status_color,
            "bar_color": bar_color,
            "message": message,
            "at_risk_side": at_risk_side,
            "estimated_pl": estimated_pl,
            "estimated_buyback": estimated_buyback,
            "exit_strategy": exit_strategy,
            "breakeven_event": breakeven_event,
            "drift_alert": drift_alert,
            "premium_trend": premium_trend,
        })

    return evaluated


def generate_recommendations(evaluated_positions: list, spx_price: float,
                             regime_data: dict,
                             day_high_spx: float, day_low_spx: float,
                             range_position: float) -> list:
    """
    Analyzes all positions holistically and generates prioritized,
    actionable recommendations: close, watch, adjust, or open.
    """
    recs = []
    regime_score = regime_data["regime_score"]
    effective_moat_min = regime_data["effective_moat_min"]
    directional_bias = regime_data["directional_bias"]
    momentum = regime_data["momentum"]
    time_pressure = regime_data["time_pressure"]
    day_range = day_high_spx - day_low_spx

    # Market-close awareness: suppress live recommendations after market close
    if time_pressure.get("time_pressure_level") == "CLOSED" or time_pressure.get("hours_remaining", 0) <= 0:
        expired_otm = [p for p in evaluated_positions if p.get("moat", 0) > 0]
        expired_itm = [p for p in evaluated_positions if p.get("moat", 0) <= 0]
        total_pl = sum(p.get("estimated_pl", 0) for p in evaluated_positions)
        recs.append({
            "priority": "LOW",
            "category": "WATCH",
            "target_id": None,
            "confidence": 1.0,
            "message": (
                f"Market closed. {len(expired_otm)} position(s) expired worthless (profit), "
                f"{len(expired_itm)} expired ITM (loss). "
                f"Net estimated P/L: {'+'if total_pl >= 0 else ''}${total_pl:.2f}. "
                f"Move positions to closed trades for record-keeping."
            ),
        })
        return recs

    # Correct state label mapping (score 0-1=A, 2=B, 3-4=C)
    if regime_score <= 1:
        state_label = "A"
        revisit_context = "trending momentum can push further"
    elif regime_score == 2:
        state_label = "B"
        revisit_context = "moderate chop means revisit probability is elevated"
    else:
        state_label = "C"
        revisit_context = "whipsaw conditions mean revisit probability is HIGH"

    put_positions = [p for p in evaluated_positions if p["type"] == "Put Spread"]
    call_positions = [p for p in evaluated_positions if p["type"] == "Call Spread"]

    hours = time_pressure.get("hours_remaining", 0)
    final_30_min = hours < 0.5
    final_hour = hours < 1.0

    # ============================================================
    # 1. CRITICAL: Strike already breached by today's range
    #    Final-30-min override: theta is nuclear — downgrade CLOSE
    #    recommendations on positions that have since recovered.
    #    Only keep CRITICAL for positions currently in gamma trap.
    # ============================================================
    for pos in evaluated_positions:
        strike = pos["strike"]
        moat = pos["moat"]

        if pos["type"] == "Call Spread" and day_high_spx >= strike:
            overshoot = round(day_high_spx - strike, 1)
            # Scale priority: CRITICAL if still in danger, HIGH if recovered somewhat
            if moat <= GAMMA_TRAP_THRESHOLD:
                priority = "CRITICAL"
                action = "Close or defend immediately."
            elif moat <= WARNING_ZONE_THRESHOLD:
                if final_30_min:
                    priority = "MEDIUM"
                    action = f"Final 30 min — theta dominant. Hold unless strike breached again. Moat {moat:.0f} pts."
                elif final_hour:
                    priority = "HIGH"
                    action = f"Final hour — close only on sustained re-breach. Moat {moat:.0f} pts."
                else:
                    priority = "CRITICAL"
                    action = "Close or defend."
            elif moat < effective_moat_min:
                if final_30_min:
                    priority = "LOW"
                    action = f"Final 30 min — moat {moat:.0f} pts. Theta favors hold. Monitor only."
                else:
                    priority = "HIGH"
                    action = "Close or widen. Current moat insufficient for re-test."
            else:
                priority = "MEDIUM" if not final_30_min else "LOW"
                action = f"SPX has since pulled back ({moat:.0f} pts moat). Monitor for re-test."
            recs.append({
                "priority": priority,
                "category": "CLOSE" if priority in ("CRITICAL", "HIGH") else "WATCH",
                "target_id": pos["id"],
                "message": (
                    f"Call {strike}: Day high ({day_high_spx:.0f}) exceeded strike by "
                    f"{overshoot} pts. In State {state_label}, {revisit_context}. {action}"
                ),
            })
        elif pos["type"] == "Call Spread" and (strike - day_high_spx) < 15:
            gap = round(strike - day_high_spx, 1)
            # Only HIGH if position is actually in danger; MEDIUM if moat is healthy
            if moat < effective_moat_min:
                near_miss_priority = "MEDIUM" if final_30_min else ("HIGH" if not final_hour else "MEDIUM")
                recs.append({
                    "priority": near_miss_priority,
                    "category": "CLOSE" if near_miss_priority == "HIGH" else "WATCH",
                    "target_id": pos["id"],
                    "message": (
                        f"Call {strike}: Day high ({day_high_spx:.0f}) came within {gap} pts of strike. "
                        f"{'Final 30 min — theta favors hold.' if final_30_min else f'Insufficient buffer for State {state_label} volatility.'}"
                    ),
                })
            else:
                recs.append({
                    "priority": "LOW",
                    "category": "WATCH",
                    "target_id": pos["id"],
                    "message": (
                        f"Call {strike}: Day high ({day_high_spx:.0f}) reached within {gap} pts of strike. "
                        f"Currently safe ({moat:.0f} pts moat). Watch for re-test."
                    ),
                })

        if pos["type"] == "Put Spread" and day_low_spx <= strike:
            overshoot = round(strike - day_low_spx, 1)
            if moat <= GAMMA_TRAP_THRESHOLD:
                priority = "CRITICAL"
                action = "Close or defend immediately."
            elif moat <= WARNING_ZONE_THRESHOLD:
                if final_30_min:
                    priority = "MEDIUM"
                    action = f"Final 30 min — theta dominant. Hold unless strike breached again. Moat {moat:.0f} pts."
                elif final_hour:
                    priority = "HIGH"
                    action = f"Final hour — close only on sustained re-breach. Moat {moat:.0f} pts."
                else:
                    priority = "CRITICAL"
                    action = "Close or defend immediately."
            elif moat < effective_moat_min:
                if final_30_min:
                    priority = "LOW"
                    action = f"Final 30 min — moat {moat:.0f} pts. Theta favors hold. Monitor only."
                else:
                    priority = "HIGH"
                    action = "Close or widen. Current moat insufficient for re-test."
            else:
                priority = "MEDIUM" if not final_30_min else "LOW"
                action = f"SPX has since recovered ({moat:.0f} pts moat). Monitor for re-test."
            recs.append({
                "priority": priority,
                "category": "CLOSE" if priority in ("CRITICAL", "HIGH") else "WATCH",
                "target_id": pos["id"],
                "message": (
                    f"Put {strike}: Day low ({day_low_spx:.0f}) breached strike by "
                    f"{overshoot} pts. {action}"
                ),
            })
        elif pos["type"] == "Put Spread" and (day_low_spx - strike) < 15:
            gap = round(day_low_spx - strike, 1)
            if moat < effective_moat_min:
                near_miss_priority = "MEDIUM" if final_30_min else ("HIGH" if not final_hour else "MEDIUM")
                recs.append({
                    "priority": near_miss_priority,
                    "category": "CLOSE" if near_miss_priority == "HIGH" else "WATCH",
                    "target_id": pos["id"],
                    "message": (
                        f"Put {strike}: Day low ({day_low_spx:.0f}) came within {gap} pts of strike. "
                        f"{'Final 30 min — theta favors hold.' if final_30_min else f'Insufficient buffer for State {state_label} volatility.'}"
                    ),
                })
            else:
                recs.append({
                    "priority": "LOW",
                    "category": "WATCH",
                    "target_id": pos["id"],
                    "message": (
                        f"Put {strike}: Day low ({day_low_spx:.0f}) reached within {gap} pts of strike. "
                        f"Currently safe ({moat:.0f} pts moat). Watch for re-test."
                    ),
                })

    # ============================================================
    # 2. HIGH: Moat far below recommended minimum
    # ============================================================
    for pos in evaluated_positions:
        moat = pos["moat"]
        if moat > WARNING_ZONE_THRESHOLD and moat < effective_moat_min * 0.5:
            moat_deficit_priority = "MEDIUM" if final_30_min else "HIGH"
            moat_deficit_suffix = " Final 30 min — theta decay may save this position." if final_30_min else ""
            recs.append({
                "priority": moat_deficit_priority,
                "category": "CLOSE" if moat_deficit_priority == "HIGH" else "WATCH",
                "target_id": pos["id"],
                "message": (
                    f"{pos['type']} {pos['strike']}: Moat ({moat} pts) is less than half "
                    f"the recommended minimum ({effective_moat_min} pts). "
                    f"High probability of entering warning zone on any move.{moat_deficit_suffix}"
                ),
            })

    # ============================================================
    # 2b. TAKE-PROFIT: Auto-recommend locking in gains
    # ============================================================
    for pos in evaluated_positions:
        credit = pos.get("credit", 0)
        est_buyback = pos.get("estimated_buyback", credit)
        moat = pos.get("moat", 0)
        if credit <= 0:
            continue

        profit_pct = (credit - est_buyback) / credit * 100

        if profit_pct >= 80 and moat > WARNING_ZONE_THRESHOLD:
            recs.append({
                "priority": "MEDIUM",
                "category": "CLOSE",
                "target_id": pos["id"],
                "message": (
                    f"TAKE PROFIT: {pos['type']} {pos['strike']} at ~{profit_pct:.0f}% of max gain. "
                    f"Est. buyback ~${est_buyback:.2f} (credit ${credit:.2f}). "
                    f"Close to lock ${credit - est_buyback:.2f}/contract profit."
                ),
            })
        elif profit_pct >= 50 and moat >= effective_moat_min and hours < 2.0:
            recs.append({
                "priority": "LOW",
                "category": "OPPORTUNITY",
                "target_id": pos["id"],
                "message": (
                    f"Profit opportunity: {pos['type']} {pos['strike']} at ~{profit_pct:.0f}% gain "
                    f"with {hours:.1f}h left. Consider closing at ~${est_buyback:.2f} to lock profit."
                ),
            })

    # ============================================================
    # 2c. BREAKEVEN TOUCH: Flag positions returning to breakeven as exit opportunities
    # ============================================================
    for pos in evaluated_positions:
        be_event = pos.get("breakeven_event")
        if be_event:
            touch = be_event["touch_count"]
            peak = be_event["peak_loss"]
            ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(touch, f"{touch}th")
            priority = "HIGH" if touch >= 2 else "MEDIUM"
            recs.append({
                "priority": priority,
                "category": "CLOSE",
                "target_id": pos["id"],
                "confidence": min(0.95, 0.6 + touch * 0.1),
                "message": (
                    f"BREAKEVEN EXIT: {pos['type']} {pos['strike']} returned to ~breakeven "
                    f"({ordinal} time). Peak loss was ${abs(peak):.2f}. "
                    f"Close at ~${be_event['est_buyback']:.2f} to exit flat. "
                    f"{'Each return to breakeven is a gift — take it.' if touch >= 2 else 'Consider closing to avoid another drawdown cycle.'}"
                ),
            })

    # ============================================================
    # 2d. CUMULATIVE DRIFT: Flag slow, steady drift toward strikes
    # ============================================================
    for pos in evaluated_positions:
        drift = pos.get("drift_alert")
        if drift:
            moat = pos.get("moat", 100)
            priority = "HIGH" if moat < effective_moat_min else "MEDIUM"
            recs.append({
                "priority": priority,
                "category": "WATCH" if priority == "MEDIUM" else "CLOSE",
                "target_id": pos["id"],
                "message": (
                    f"DRIFT WARNING: SPX has moved {drift['drift_pts']} pts toward "
                    f"{pos['type']} {pos['strike']} over the last {drift['window_minutes']:.0f} min "
                    f"({drift['start_price']}→{drift['current_price']}). "
                    f"{'Moat now thin — consider exit.' if moat < effective_moat_min else 'Trend forming — watch closely.'}"
                ),
            })

    # ============================================================
    # 3. OPPORTUNITY: Time-decay-aware, day-history-aware advice
    # ============================================================
    # NOTE: Indicator-specific watches (ER, RSI, VWAP, day range extremes)
    # are intentionally NOT generated as recommendations — they are surfaced
    # on indicator card hovers and in the ceiling/floor watch levels.
    # Position-specific trigger prices are also in the ceiling/floor.
    # Only generate ACTIONABLE, NON-REDUNDANT text recommendations here.

    er_val = regime_data.get("er_value", 0)

    # Time-decay factor: how much of the day has elapsed (0=open, 1=close)
    time_decay_pct = max(0, 1 - hours / 6.5) * 100
    # Adjusted moat: in the final hours, theta works hard — positions need less buffer
    # But gamma also ramps, so we only reduce moat requirement modestly
    if hours < 1.5:
        # Final 90 min: gamma dominates, NO new positions
        time_adjusted_moat = None  # signal: do not deploy
    elif hours < 3:
        # Afternoon: theta accelerating, moat can be tighter
        time_adjusted_moat = round(effective_moat_min * 0.75)
    else:
        time_adjusted_moat = effective_moat_min

    # Day range history context
    # How much of the day's range has already been used
    day_range_used = round(day_range)
    # Has the market already tested our positions?
    calls_tested = any(day_high_spx >= p["strike"] for p in call_positions)
    puts_tested = any(day_low_spx <= p["strike"] for p in put_positions)

    # Weakest positions — suggest adjustments
    if call_positions:
        weakest_call = min(call_positions, key=lambda p: p["moat"])
        if weakest_call["moat"] < effective_moat_min:
            redeploy_strike = round(spx_price + (time_adjusted_moat or effective_moat_min))
            # Ensure redeploy is always above the current weakest strike
            redeploy_strike = max(redeploy_strike, round(weakest_call["strike"] + 5))
            reason = ""
            if calls_tested:
                reason = f" Day high already breached {weakest_call['strike']:.0f}."
            recs.append({
                "priority": "MEDIUM",
                "category": "ADJUST",
                "target_id": weakest_call["id"],
                "message": (
                    f"Weakest call: {weakest_call['type']} {weakest_call['strike']} "
                    f"(moat {weakest_call['moat']} pts).{reason} "
                    f"Redeploy above {redeploy_strike} for buffer."
                ),
            })

    if put_positions:
        weakest_put = min(put_positions, key=lambda p: p["moat"])
        if weakest_put["moat"] < effective_moat_min:
            redeploy_strike = round(spx_price - (time_adjusted_moat or effective_moat_min))
            # Ensure redeploy is always below the current weakest strike
            redeploy_strike = min(redeploy_strike, round(weakest_put["strike"] - 5))
            reason = ""
            if puts_tested:
                reason = f" Day low already breached {weakest_put['strike']:.0f}."
            recs.append({
                "priority": "MEDIUM",
                "category": "ADJUST",
                "target_id": weakest_put["id"],
                "message": (
                    f"Weakest put: {weakest_put['type']} {weakest_put['strike']} "
                    f"(moat {weakest_put['moat']} pts).{reason} "
                    f"Redeploy below {redeploy_strike} for buffer."
                ),
            })

    # Smart deployment opportunity — accounts for time, range history, regime
    if time_adjusted_moat is None:
        # Final 90 min: gamma ramp, no new deployments
        recs.append({
            "priority": "HIGH",
            "category": "WATCH",
            "target_id": None,
            "message": (
                f"GAMMA RAMP: {hours:.1f}h to close. Theta accelerating but gamma "
                f"dominates. Do NOT open new positions. Manage existing only."
            ),
        })
    else:
        safe_put = round(spx_price - time_adjusted_moat)
        safe_call = round(spx_price + time_adjusted_moat)
        # state_label already computed above with correct mapping

        # Factor in day's range to give context on probability
        pct_label = f"{time_decay_pct:.0f}% of day elapsed"
        range_context = f"Today's range: {day_range_used} pts."

        # Warn if day range already covers potential strikes
        call_warning = ""
        if day_high_spx >= safe_call:
            call_warning = f" Day high ({day_high_spx:.0f}) already reached safe call zone — deploy further out."
            safe_call = round(day_high_spx + 30)

        put_warning = ""
        if day_low_spx <= safe_put:
            put_warning = f" Day low ({day_low_spx:.0f}) already reached safe put zone — deploy further out."
            safe_put = round(day_low_spx - 30)

        recs.append({
            "priority": "LOW",
            "category": "OPPORTUNITY",
            "target_id": None,
            "message": (
                f"State {state_label} | {pct_label} | {range_context} "
                f"Safe put below {safe_put}. Safe call above {safe_call}."
                f"{call_warning}{put_warning}"
            ),
        })

    # ============================================================
    # 4. SITUATIONAL: High-value alerts not shown elsewhere
    # ============================================================
    # Only add if genuinely new information not covered by other UI elements

    # All positions in CAUTION + both sides tested today = high-risk structure
    all_caution = all(p["moat"] < effective_moat_min for p in evaluated_positions)
    if all_caution and evaluated_positions and (calls_tested or puts_tested):
        sides_hit = []
        if calls_tested:
            sides_hit.append("calls")
        if puts_tested:
            sides_hit.append("puts")
        recs.append({
            "priority": "HIGH",
            "category": "WATCH",
            "target_id": None,
            "message": (
                f"All {len(evaluated_positions)} positions below recommended moat. "
                f"Day range already tested {' and '.join(sides_hit)}. "
                f"Consider reducing exposure."
            ),
        })

    # Assign confidence scores based on recommendation type
    for rec in recs:
        cat = rec["category"]
        pri = rec["priority"]
        msg = rec["message"].lower()

        if cat == "CLOSE" and pri == "CRITICAL":
            rec["confidence"] = 0.95  # factual: day range breached strike
        elif cat == "CLOSE" and pri == "HIGH":
            rec["confidence"] = 0.90 if "less than half" in msg else 0.85
        elif cat == "WATCH" and "gamma ramp" in msg:
            rec["confidence"] = 0.90
        elif cat == "WATCH" and "positions below" in msg:
            rec["confidence"] = 0.90  # factual: all positions under moat
        elif cat == "ADJUST":
            rec["confidence"] = 0.80 if "day high" in msg or "day low" in msg else 0.70
        elif cat == "OPPORTUNITY":
            rec["confidence"] = 0.80
        else:
            rec["confidence"] = 0.75

    # Sort: CRITICAL > HIGH > MEDIUM > LOW
    priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    recs.sort(key=lambda r: priority_order.get(r["priority"], 99))

    return recs


def compute_watch_levels(spx_price: float, day_high_spx: float,
                         day_low_spx: float,
                         evaluated_positions: list) -> dict:
    """
    Computes the SINGLE most critical price level above and below current SPX.
    Prioritizes position-derived triggers over day extremes (closer = more critical).
    Returns exactly 2 levels: critical_above and critical_below.
    """
    above_candidates = []
    below_candidates = []

    # Position-derived trigger levels
    for pos in evaluated_positions:
        strike = pos["strike"]
        moat = pos["moat"]

        if pos["type"] == "Call Spread":
            if moat > WARNING_ZONE_THRESHOLD:
                trigger = strike - WARNING_ZONE_THRESHOLD
                if trigger > spx_price:
                    above_candidates.append((
                        trigger,
                        f"Call Spread {int(strike)} enters WARNING zone",
                        "warning",
                    ))
            elif moat > GAMMA_TRAP_THRESHOLD:
                trigger = strike - GAMMA_TRAP_THRESHOLD
                if trigger > spx_price:
                    above_candidates.append((
                        trigger,
                        f"Call Spread {int(strike)} enters GAMMA TRAP — close immediately",
                        "gamma",
                    ))

        elif pos["type"] == "Put Spread":
            if moat > WARNING_ZONE_THRESHOLD:
                trigger = strike + WARNING_ZONE_THRESHOLD
                if trigger < spx_price:
                    below_candidates.append((
                        trigger,
                        f"Put Spread {int(strike)} enters WARNING zone",
                        "warning",
                    ))
            elif moat > GAMMA_TRAP_THRESHOLD:
                trigger = strike + GAMMA_TRAP_THRESHOLD
                if trigger < spx_price:
                    below_candidates.append((
                        trigger,
                        f"Put Spread {int(strike)} enters GAMMA TRAP — close immediately",
                        "gamma",
                    ))

    # Day extremes as fallback
    if day_high_spx > spx_price:
        above_candidates.append((
            day_high_spx,
            "New intraday high — all call spreads face renewed pressure",
            "day_extreme",
        ))

    if day_low_spx < spx_price:
        below_candidates.append((
            day_low_spx,
            "New intraday low — all put spreads face renewed pressure",
            "day_extreme",
        ))

    # Pick closest on each side, enriched with day-extreme context
    critical_above = None
    if above_candidates:
        above_candidates.sort(key=lambda t: t[0])
        best = above_candidates[0]
        impact = best[1]
        # If primary trigger is position-derived, append day high context
        if best[2] != "day_extreme" and day_high_spx > spx_price:
            impact += f" (Day high {day_high_spx:.0f} is {round(day_high_spx - spx_price)} pts above)"
        critical_above = {
            "price": round(best[0], 1),
            "distance": round(best[0] - spx_price, 1),
            "impact": impact,
            "severity": best[2],
        }

    critical_below = None
    if below_candidates:
        below_candidates.sort(key=lambda t: t[0], reverse=True)
        best = below_candidates[0]
        impact = best[1]
        # If primary trigger is position-derived, append day low context
        if best[2] != "day_extreme" and day_low_spx < spx_price:
            impact += f" (Day low {day_low_spx:.0f} is {round(spx_price - day_low_spx)} pts below)"
        critical_below = {
            "price": round(best[0], 1),
            "distance": round(spx_price - best[0], 1),
            "impact": impact,
            "severity": best[2],
        }

    return {"critical_above": critical_above, "critical_below": critical_below}


def compute_position_summary(evaluated_positions: list, spx_price: float,
                             effective_moat_min: int) -> dict | None:
    """
    Computes combined iron condor / position correlation summary.
    Gives the trader a single-glance view of their entire structure.
    """
    if not evaluated_positions:
        return None

    puts = [p for p in evaluated_positions if p["type"] == "Put Spread"]
    calls = [p for p in evaluated_positions if p["type"] == "Call Spread"]

    total_credit = sum(p["credit"] for p in evaluated_positions)
    total_estimated_pl = sum(p["estimated_pl"] for p in evaluated_positions)

    lowest_put = min((p["strike"] for p in puts), default=None)
    highest_put = max((p["strike"] for p in puts), default=None)
    lowest_call = min((p["strike"] for p in calls), default=None)
    highest_call = max((p["strike"] for p in calls), default=None)

    # Safe corridor: range where ALL positions stay above recommended moat
    safe_floor = (highest_put + effective_moat_min) if puts else None
    safe_ceiling = (lowest_call - effective_moat_min) if calls else None

    # Risk tilt: which side has more positions in trouble
    put_at_risk = sum(1 for p in puts if p["moat"] < effective_moat_min)
    call_at_risk = sum(1 for p in calls if p["moat"] < effective_moat_min)

    if put_at_risk > call_at_risk:
        risk_tilt = "PUT_HEAVY"
    elif call_at_risk > put_at_risk:
        risk_tilt = "CALL_HEAVY"
    else:
        risk_tilt = "BALANCED"

    structure = "IRON_CONDOR" if puts and calls else ("PUT_WING" if puts else "CALL_WING")

    return {
        "structure": structure,
        "total_credit": round(total_credit, 2),
        "total_estimated_pl": round(total_estimated_pl, 2),
        "put_count": len(puts),
        "call_count": len(calls),
        "lowest_put": lowest_put,
        "highest_call": highest_call,
        "safe_floor": round(safe_floor, 1) if safe_floor else None,
        "safe_ceiling": round(safe_ceiling, 1) if safe_ceiling else None,
        "risk_tilt": risk_tilt,
        "positions_at_risk": put_at_risk + call_at_risk,
        "positions_total": len(evaluated_positions),
    }


# ================================================================
# PHASE 5: PRE-TRADE ANALYSIS
# ================================================================
def analyze_trade_proposal(
    trade_type: str,
    strike: float,
    credit: float,
    spx_price: float,
    regime_data: dict,
    smart_moat: int,
    day_high_spx: float,
    day_low_spx: float,
    range_position: float,
    existing_positions: list,
    momentum_label: str = "",
    vwap_dev: float = 0.0,
    gex_data: dict = None,
) -> dict:
    """
    Scores a proposed credit spread BEFORE entry.
    Returns a verdict (STRONG_ENTRY / ACCEPTABLE / CAUTION / REJECT),
    a 0-100 score, and detailed reasons for/against.
    """
    hours_remaining = regime_data["time_pressure"]["hours_remaining"]
    directional_bias = regime_data["directional_bias"]
    regime_score = regime_data["regime_score"]
    day_range = day_high_spx - day_low_spx

    # Moat of proposed trade
    if trade_type == "Put Spread":
        moat = spx_price - strike
    else:
        moat = strike - spx_price

    moat = round(moat, 1)
    reasons_for = []
    reasons_against = []

    # ---- 1. MOAT ADEQUACY (0-30 pts) ----
    if moat >= smart_moat * 1.5:
        moat_score = 30
        reasons_for.append(f"Excellent buffer: {moat} pts moat (×1.5 above {smart_moat} smart moat)")
    elif moat >= smart_moat:
        moat_score = 22
        reasons_for.append(f"Adequate buffer: {moat} pts moat (meets {smart_moat} smart moat)")
    elif moat >= WARNING_ZONE_THRESHOLD:
        moat_score = 10
        reasons_against.append(f"Marginal buffer: {moat} pts moat (below {smart_moat} smart moat)")
    elif moat >= GAMMA_TRAP_THRESHOLD:
        moat_score = 3
        reasons_against.append(f"Dangerously close: {moat} pts moat (WARNING zone)")
    else:
        moat_score = 0
        reasons_against.append(f"Unacceptable: {moat} pts moat (GAMMA TRAP zone)")

    # ---- 2. DAY RANGE SAFETY (0-20 pts) ----
    if trade_type == "Call Spread":
        day_extreme_gap = strike - day_high_spx
        extreme_label = f"Day high ({day_high_spx:.0f})"
    else:
        day_extreme_gap = day_low_spx - strike
        extreme_label = f"Day low ({day_low_spx:.0f})"

    day_extreme_gap = round(day_extreme_gap, 1)

    if day_extreme_gap < 0:
        range_score = 0
        reasons_against.append(f"{extreme_label} already exceeded this strike by {abs(day_extreme_gap)} pts. Market has proven it can reach here.")
    elif day_extreme_gap < 15:
        range_score = 5
        reasons_against.append(f"{extreme_label} came within {day_extreme_gap} pts of strike. Tight.")
    elif day_extreme_gap < 30:
        range_score = 12
        reasons_for.append(f"{extreme_label} is {day_extreme_gap} pts away. Moderate day-range buffer.")
    else:
        range_score = 20
        reasons_for.append(f"{extreme_label} is {day_extreme_gap} pts away. Strong day-range buffer.")

    # ---- 3. DIRECTIONAL ALIGNMENT (0-15 pts) ----
    at_risk_side = False
    if trade_type == "Put Spread" and directional_bias in ("BEARISH", "LEAN BEARISH"):
        at_risk_side = True
    elif trade_type == "Call Spread" and directional_bias in ("BULLISH", "LEAN BULLISH"):
        at_risk_side = True

    if directional_bias == "NEUTRAL":
        direction_score = 10
        reasons_for.append("Neutral bias — no directional headwind.")
    elif at_risk_side:
        direction_score = 0
        reasons_against.append(f"Against the trend: {directional_bias} bias threatens {trade_type.split()[0].lower()} side.")
    else:
        direction_score = 15
        reasons_for.append(f"With the trend: {directional_bias} bias favors this side.")

    # ---- 4. TIME WINDOW (0-15 pts) ----
    if hours_remaining >= 4:
        time_score = 15
        reasons_for.append(f"{hours_remaining:.1f}h remaining — full theta runway.")
    elif hours_remaining >= 2.5:
        time_score = 10
        reasons_for.append(f"{hours_remaining:.1f}h remaining — adequate theta window.")
    elif hours_remaining >= 1.5:
        time_score = 4
        reasons_against.append(f"{hours_remaining:.1f}h remaining — late entry, gamma accelerating.")
    else:
        time_score = 0
        reasons_against.append(f"{hours_remaining:.1f}h remaining — GAMMA RAMP. Do NOT enter new positions.")

    # ---- 5. CREDIT QUALITY (0-10 pts) ----
    if credit >= 1.0:
        credit_score = 10
        reasons_for.append(f"${credit:.2f} credit — strong premium collected.")
    elif credit >= 0.50:
        credit_score = 7
        reasons_for.append(f"${credit:.2f} credit — decent premium.")
    elif credit >= 0.30:
        credit_score = 4
        reasons_against.append(f"${credit:.2f} credit — thin premium for the risk.")
    else:
        credit_score = 1
        reasons_against.append(f"${credit:.2f} credit — very thin. Risk/reward unfavorable.")

    # ---- 6. PORTFOLIO IMPACT (0-10 pts) ----
    existing_puts = [p for p in existing_positions if p.get("type") == "Put Spread"]
    existing_calls = [p for p in existing_positions if p.get("type") == "Call Spread"]

    if not existing_positions:
        portfolio_score = 5
        portfolio_note = "First position — no portfolio context."
    else:
        put_heavy = len(existing_puts) > len(existing_calls)
        call_heavy = len(existing_calls) > len(existing_puts)

        if (trade_type == "Put Spread" and call_heavy) or (trade_type == "Call Spread" and put_heavy):
            portfolio_score = 10
            portfolio_note = "Balances portfolio — improves iron condor structure."
            reasons_for.append(portfolio_note)
        elif (trade_type == "Put Spread" and put_heavy) or (trade_type == "Call Spread" and call_heavy):
            portfolio_score = 2
            portfolio_note = "Adds to already-heavy side — increases directional exposure."
            reasons_against.append(portfolio_note)
        else:
            portfolio_score = 6
            portfolio_note = "Maintains balanced structure."

    # ---- 7. REGIME PENALTY ----
    # State C whipsaw is dangerous for new entries
    regime_penalty = 0
    if regime_score >= 3:
        regime_penalty = 10
        reasons_against.append("State C whipsaw — high reversal risk for new entries.")
    elif regime_score == 2:
        regime_penalty = 5
        reasons_against.append("State B moderate chop — some reversal risk.")

    # ---- 8. RANGE POSITION STRESS ----
    # Entering a call spread when SPX is at 90%+ of day range is risky
    range_stress_penalty = 0
    if trade_type == "Call Spread" and range_position > 80:
        range_stress_penalty = min(8, round((range_position - 80) / 20 * 8))
        reasons_against.append(f"SPX at {range_position:.0f}% of day range — elevated call premium risk.")
    elif trade_type == "Put Spread" and range_position < 20:
        range_stress_penalty = min(8, round((20 - range_position) / 20 * 8))
        reasons_against.append(f"SPX at {range_position:.0f}% of day range — elevated put premium risk.")

    # ---- 9. GEX WALL PROXIMITY (0-8 bonus, 0-5 penalty) ----
    gex_score = 0
    if gex_data and gex_data.get("gex_regime") not in (None, "UNAVAILABLE"):
        put_wall_spx = gex_data.get("put_wall_spx", 0)
        call_wall_spx = gex_data.get("call_wall_spx", 0)
        gamma_wall_spx = gex_data.get("gamma_wall_spx", 0)
        gex_regime = gex_data.get("gex_regime")

        if trade_type == "Put Spread":
            # Strike below put wall = GEX support acting as floor
            if put_wall_spx > 0 and strike < put_wall_spx:
                wall_gap = put_wall_spx - strike
                gex_score = min(8, round(wall_gap / 5))
                reasons_for.append(f"Strike is {wall_gap:.0f} pts below put wall ({put_wall_spx} SPX) — GEX floor support.")
            elif put_wall_spx > 0 and strike >= put_wall_spx:
                gex_score = -3
                reasons_against.append(f"Strike at/above put wall ({put_wall_spx} SPX) — no GEX floor support.")
        else:
            # Strike above call wall = GEX resistance acting as ceiling
            if call_wall_spx > 0 and strike > call_wall_spx:
                wall_gap = strike - call_wall_spx
                gex_score = min(8, round(wall_gap / 5))
                reasons_for.append(f"Strike is {wall_gap:.0f} pts above call wall ({call_wall_spx} SPX) — GEX ceiling resistance.")
            elif call_wall_spx > 0 and strike <= call_wall_spx:
                gex_score = -3
                reasons_against.append(f"Strike at/below call wall ({call_wall_spx} SPX) — no GEX ceiling resistance.")

        # GEX regime bonus/penalty
        if gex_regime == "POSITIVE":
            gex_score += 3
            reasons_for.append("Positive GEX — mean-reverting environment favors credit spreads.")
        elif gex_regime == "NEGATIVE":
            gex_score -= 3
            reasons_against.append("Negative GEX — trending/volatile, dealers short gamma.")

    # ---- TOTAL SCORE ----
    raw_score = moat_score + range_score + direction_score + time_score + credit_score + portfolio_score + max(0, gex_score)
    penalties = regime_penalty + range_stress_penalty + abs(min(0, gex_score))
    total_score = max(0, min(100, raw_score - penalties))

    # ---- VERDICT ----
    if total_score >= 75:
        verdict = "STRONG_ENTRY"
        verdict_label = "Strong Entry"
        verdict_color = "emerald"
    elif total_score >= 55:
        verdict = "ACCEPTABLE"
        verdict_label = "Acceptable"
        verdict_color = "blue"
    elif total_score >= 35:
        verdict = "CAUTION"
        verdict_label = "Caution — Consider Alternatives"
        verdict_color = "amber"
    else:
        verdict = "REJECT"
        verdict_label = "Reject — Do Not Enter"
        verdict_color = "red"

    # ---- SUGGESTED ALTERNATIVE ----
    suggested_strike = None
    if total_score < 75:
        ideal_moat = round(smart_moat * 1.3)
        if trade_type == "Call Spread":
            suggested_strike = round(spx_price + ideal_moat)
            # Must be above day high
            suggested_strike = max(suggested_strike, round(day_high_spx + 10))
        else:
            suggested_strike = round(spx_price - ideal_moat)
            # Must be below day low
            suggested_strike = min(suggested_strike, round(day_low_spx - 10))

    return {
        "verdict": verdict,
        "verdict_label": verdict_label,
        "verdict_color": verdict_color,
        "score": total_score,
        "moat": moat,
        "breakdown": {
            "moat_score": moat_score,
            "range_score": range_score,
            "direction_score": direction_score,
            "time_score": time_score,
            "credit_score": credit_score,
            "portfolio_score": portfolio_score,
            "regime_penalty": regime_penalty,
            "range_stress_penalty": range_stress_penalty,
            "gex_score": gex_score,
        },
        "reasons_for": reasons_for,
        "reasons_against": reasons_against,
        "suggested_strike": suggested_strike,
        "context": {
            "smart_moat": smart_moat,
            "regime_state": regime_data["regime_state"],
            "directional_bias": directional_bias,
            "hours_remaining": hours_remaining,
            "day_range": round(day_range, 1),
            "range_position": range_position,
        },
    }


def auto_propose_positions(
    spx_price: float,
    regime_data: dict,
    smart_moat: int,
    day_high_spx: float,
    day_low_spx: float,
    range_position: float,
    existing_positions: list,
    momentum_label: str = "",
    vwap_dev: float = 0.0,
    gex_data: dict = None,
) -> list:
    """
    Auto-proposes new credit spread candidates using analyze_trade_proposal.
    Generates 3 strike candidates per side (put + call) at 1×, 1.25×, 1.5× smart_moat,
    rounds to nearest 5-pt increment, scores each, and returns proposals
    with verdict ACCEPTABLE or better sorted by score.
    """
    hours_remaining = regime_data["time_pressure"]["hours_remaining"]

    # Don't propose if < 1 hour left or market closed
    if hours_remaining < 1.0:
        return []

    proposals = []
    # Estimated credit based on moat distance (rough model)
    # Closer strikes = higher premium, farther = lower
    def estimate_credit(moat_pts: float) -> float:
        # Rough 0DTE credit model: credit drops exponentially with distance
        base = 0.50 * max(0, 1 - moat_pts / 150) * (1 + hours_remaining / 6.5)
        return round(max(0.10, base), 2)

    for side in ["Put Spread", "Call Spread"]:
        for mult in [1.0, 1.25, 1.5]:
            offset = round(smart_moat * mult)
            if side == "Put Spread":
                strike = round((spx_price - offset) / 5) * 5  # Round to 5-pt increments
            else:
                strike = round((spx_price + offset) / 5) * 5

            moat = abs(spx_price - strike)
            credit = estimate_credit(moat)

            # Skip if premium too low to be worth it
            if credit < 0.15:
                continue

            try:
                result = analyze_trade_proposal(
                    trade_type=side,
                    strike=strike,
                    credit=credit,
                    spx_price=spx_price,
                    regime_data=regime_data,
                    smart_moat=smart_moat,
                    day_high_spx=day_high_spx,
                    day_low_spx=day_low_spx,
                    range_position=range_position,
                    existing_positions=existing_positions,
                    momentum_label=momentum_label,
                    vwap_dev=vwap_dev,
                    gex_data=gex_data,
                )

                if result["verdict"] in ("STRONG_ENTRY", "ACCEPTABLE"):
                    proposals.append({
                        "type": side,
                        "strike": strike,
                        "estimated_credit": credit,
                        "moat": round(moat, 1),
                        "score": result["score"],
                        "verdict": result["verdict"],
                        "reasons_for": result["reasons_for"][:2],
                        "reasons_against": result["reasons_against"][:1],
                    })
            except Exception as e:
                logger.warning(f"Auto-propose failed for {side} @ {strike}: {e}")
                continue

    # Sort by score descending, return top 4
    proposals.sort(key=lambda x: x["score"], reverse=True)
    return proposals[:4]