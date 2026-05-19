import pandas as pd
from config import (
    logger,
    CHOP_THRESHOLD,
    EFFICIENCY_RATIO_THRESHOLD,
    RSI_DEAD_ZONE_LOWER,
    RSI_DEAD_ZONE_UPPER,
    EMA_COMPRESSION_THRESHOLD_PCT,
    VWAP_ELASTICITY_THRESHOLD_PCT
)

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

    logger.info("Evaluating market regime metrics...")
    logger.info(f"Current price: ${latest['Close']:.2f} | EMA_9: {ema_9:.2f} | EMA_21: {ema_21:.2f} | RSI: {rsi:.2f}")
    logger.info(
        f"CHOP: {chop:.2f} (col: {chop_col}) | ER: {er:.2f} (col: {er_col}) | VWAP: {vwap_val:.2f} (col: {vwap_col}) | Dev: {vwap_deviation_pct:.4f}%")

    regime_score = 0

    if chop > CHOP_THRESHOLD:
        regime_score += 1
        logger.info(f"Penalty Triggered: High Choppiness (CHOP > {CHOP_THRESHOLD})")
    if er < EFFICIENCY_RATIO_THRESHOLD:
        regime_score += 1
        logger.info(f"Penalty Triggered: Low Efficiency (ER < {EFFICIENCY_RATIO_THRESHOLD})")
    if RSI_DEAD_ZONE_LOWER <= rsi <= RSI_DEAD_ZONE_UPPER:
        regime_score += 1
        logger.info(f"Penalty Triggered: RSI Consolidation Dead Zone ({RSI_DEAD_ZONE_LOWER} <= RSI <= {RSI_DEAD_ZONE_UPPER})")

    ema_diff = abs(ema_9 - ema_21)
    ema_threshold = latest['Close'] * EMA_COMPRESSION_THRESHOLD_PCT
    if ema_diff < ema_threshold:
        regime_score += 1
        logger.info(f"Penalty Triggered: EMA Compression (diff: {ema_diff:.4f} < threshold: {ema_threshold:.4f})")

    logger.info(f"Total Regime Score: {regime_score}")

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

    if vwap_deviation_pct > VWAP_ELASTICITY_THRESHOLD_PCT:
        state = state + " [OVERRIDE: MAX ELASTICITY]"
        stop = "SUSPEND STOPS. Wait 10 mins for Mean Reversion Bounce, then Eject."
        logger.warning(f"VWAP Elasticity Override Triggered! Deviation: {vwap_deviation_pct:.4f}% > {VWAP_ELASTICITY_THRESHOLD_PCT}%")

    logger.info(f"Final Assigned State: {state}")
    return {
        "regime_state": state,
        "regime_score": regime_score,
        "recommended_moat": moat,
        "stop_loss_rule": stop,
        "chop_value": round(chop, 2),
        "er_value": round(er, 2),
        "vwap_dev": round(vwap_deviation_pct, 3)
    }