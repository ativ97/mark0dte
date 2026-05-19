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

    return {
        "hours_remaining": round(hours_remaining, 2),
        "time_pressure_level": level,
        "time_pressure_label": label,
        "moat_multiplier": moat_multiplier,
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


def analyze_market_regime(df: pd.DataFrame) -> dict:
    """Enhanced Regime Classifier V3.2: Continuous sub-scores + directional bias + momentum context."""
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
    }


def compute_smart_moat(regime_data: dict, spx_price: float,
                        day_high_spx: float, day_low_spx: float,
                        range_position: float) -> dict:
    """
    PHASE 4: Smart Moat System.
    Adjusts the effective moat based on:
    1. Range context: contained chop vs expanding range
    2. Signal quality: dead market (ER near 0) vs directional signal
    3. Time decay: positions that survived the day deserve lower moat
    4. Range exhaustion: if price tested both extremes and returned to center
    Returns enriched regime data with smart_moat fields.
    """
    regime_score = regime_data["regime_score"]
    continuous_score = regime_data["continuous_score"]
    base_moat = regime_data["effective_moat_min"]
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

    # ---- COMBINE FACTORS ----
    # Apply all factors to the base moat, with a floor
    combined_factor = range_moat_factor * signal_moat_factor * time_moat_factor * exhaustion_factor
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

    moat_explanation = (
        f"Base {base_moat} pts → Smart {smart_moat} pts"
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
    }


def evaluate_positions(db_positions, spx_price: float, db_session,
                       regime_score: int = 0, effective_moat_min: int = 35,
                       directional_bias: str = "NEUTRAL",
                       range_position: float = 50.0,
                       day_high_spx: float = 0.0, day_low_spx: float = 0.0,
                       hours_remaining: float = 6.5,
                       momentum_label: str = "",
                       vwap_dev: float = 0.0):
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

    # Range proximity flags (where is SPX in today's high-low range?)
    near_day_low = range_position < 20.0   # bottom 20% of day's range
    near_day_high = range_position > 80.0  # top 20% of day's range

    for pos in db_positions:
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

            if moat <= WARNING_ZONE_THRESHOLD:
                # Side-aware stop rules: at-risk side gets tighter stops
                if at_risk_side:
                    if regime_score <= 1:
                        message = "WARNING: Trend pushing toward strike. Tight 200% premium stop — close if triggered."
                    elif regime_score == 2:
                        message = "WARNING: At-risk side. Close on 200% premium OR 10-pt breach."
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

            elif moat < effective_moat_min:
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

        if moat <= 0:
            # Strike breached — immediate exit
            exit_strategy = {
                "action": "CLOSE_NOW",
                "target_price": None,
                "trigger_spx": None,
                "monitor_minutes": 0,
                "instruction": f"Strike breached. Close at market immediately.",
            }
        elif moat <= GAMMA_TRAP_THRESHOLD:
            # Gamma trap — kill switch
            exit_strategy = {
                "action": "CLOSE_NOW",
                "target_price": round(pos.credit * 1.2, 2),
                "trigger_spx": None,
                "monitor_minutes": BREACH_VERIFICATION_MINUTES,
                "instruction": (
                    f"Gamma Trap active. Close at ${pos.credit * 1.2:.2f} or less. "
                    f"If fill unavailable, monitor {BREACH_VERIFICATION_MINUTES} min — "
                    f"auto-eject if SPX stays past {gamma_trigger:.0f}."
                ),
            }
        elif moat <= WARNING_ZONE_THRESHOLD:
            # Warning zone — close soon with target
            # Buyback target based on regime: State C ignores premium, just close
            if regime_score >= 3:
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
            else:
                # State A/B: use premium-based stop
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

    # ============================================================
    # 1. CRITICAL: Strike already breached by today's range
    # ============================================================
    for pos in evaluated_positions:
        strike = pos["strike"]
        moat = pos["moat"]

        if pos["type"] == "Call Spread" and day_high_spx >= strike:
            overshoot = round(day_high_spx - strike, 1)
            # Scale priority: CRITICAL if still in danger, HIGH if recovered somewhat
            if moat <= WARNING_ZONE_THRESHOLD:
                priority = "CRITICAL"
                action = "Close or defend."
            elif moat < effective_moat_min:
                priority = "HIGH"
                action = "Close or widen. Current moat insufficient for re-test."
            else:
                priority = "MEDIUM"
                action = f"SPX has since pulled back ({moat:.0f} pts moat). Monitor for re-test."
            recs.append({
                "priority": priority,
                "category": "CLOSE" if priority != "MEDIUM" else "WATCH",
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
                recs.append({
                    "priority": "HIGH",
                    "category": "CLOSE",
                    "target_id": pos["id"],
                    "message": (
                        f"Call {strike}: Day high ({day_high_spx:.0f}) came within {gap} pts of strike. "
                        f"Insufficient buffer for State {state_label} volatility."
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
            if moat <= WARNING_ZONE_THRESHOLD:
                priority = "CRITICAL"
                action = "Close or defend immediately."
            elif moat < effective_moat_min:
                priority = "HIGH"
                action = "Close or widen. Current moat insufficient for re-test."
            else:
                priority = "MEDIUM"
                action = f"SPX has since recovered ({moat:.0f} pts moat). Monitor for re-test."
            recs.append({
                "priority": priority,
                "category": "CLOSE" if priority != "MEDIUM" else "WATCH",
                "target_id": pos["id"],
                "message": (
                    f"Put {strike}: Day low ({day_low_spx:.0f}) breached strike by "
                    f"{overshoot} pts. {action}"
                ),
            })
        elif pos["type"] == "Put Spread" and (day_low_spx - strike) < 15:
            gap = round(day_low_spx - strike, 1)
            if moat < effective_moat_min:
                recs.append({
                    "priority": "HIGH",
                    "category": "CLOSE",
                    "target_id": pos["id"],
                    "message": (
                        f"Put {strike}: Day low ({day_low_spx:.0f}) came within {gap} pts of strike. "
                        f"Insufficient buffer for State {state_label} volatility."
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
            recs.append({
                "priority": "HIGH",
                "category": "CLOSE",
                "target_id": pos["id"],
                "message": (
                    f"{pos['type']} {pos['strike']}: Moat ({moat} pts) is less than half "
                    f"the recommended minimum ({effective_moat_min} pts). "
                    f"High probability of entering warning zone on any move."
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
    hours = time_pressure.get("hours_remaining", 0)

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