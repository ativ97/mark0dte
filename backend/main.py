from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from typing import Literal, Optional
import datetime
import logging
import pandas_ta  # Registers the .ta accessor on DataFrames

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("0DTE-QuantEngine")

# Import refactored modules
from data_fetcher import fetch_alpaca_market_data, fetch_spx_live_price
from engine import analyze_market_regime, evaluate_positions, generate_recommendations, compute_watch_levels, compute_position_summary, compute_smart_moat, analyze_trade_proposal
from database import Base, engine as db_engine, get_db, PositionDB, ClosedPositionDB

# Initialize Database tables
Base.metadata.create_all(bind=db_engine)

app = FastAPI(title="0DTE Quant Engine V3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API SCHEMAS ---
class PositionCreate(BaseModel):
    type: Literal["Put Spread", "Call Spread", "Iron Condor"]
    strike: float
    credit: float

    @field_validator("strike")
    @classmethod
    def strike_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Strike must be a positive number")
        return v

    @field_validator("credit")
    @classmethod
    def credit_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Credit must be a positive number")
        return v


class EvaluatedPosition(BaseModel):
    id: int
    type: str
    strike: float
    credit: float
    moat: float
    moat_pct: float
    status_color: str
    bar_color: str
    message: str
    at_risk_side: bool = False
    estimated_pl: float = 0.0
    estimated_buyback: float = 0.0
    exit_strategy: dict = {}


class SubScores(BaseModel):
    chop_intensity: float
    er_intensity: float
    rsi_intensity: float
    ema_intensity: float


class TimePressure(BaseModel):
    hours_remaining: float
    time_pressure_level: str
    time_pressure_label: str
    moat_multiplier: float


class Momentum(BaseModel):
    change_1h_pct: float
    change_2h_pct: float
    change_2h_spx_pts: float
    rsi_delta_2h: float
    day_high_spy: float
    day_low_spy: float
    range_position: float
    momentum_label: str


class Recommendation(BaseModel):
    priority: str
    category: str
    target_id: int | None = None
    message: str
    confidence: float


class CriticalLevel(BaseModel):
    price: float
    distance: float
    impact: str
    severity: str


class WatchLevels(BaseModel):
    critical_above: CriticalLevel | None = None
    critical_below: CriticalLevel | None = None


class PositionSummary(BaseModel):
    structure: str
    total_credit: float
    total_estimated_pl: float
    put_count: int
    call_count: int
    lowest_put: float | None = None
    highest_call: float | None = None
    safe_floor: float | None = None
    safe_ceiling: float | None = None
    risk_tilt: str
    positions_at_risk: int
    positions_total: int


class SmartMoat(BaseModel):
    smart_moat: int
    base_moat: int
    moat_explanation: str
    range_context: str
    signal_quality: str
    range_exhausted: bool
    combined_factor: float


class TelemetryResponse(BaseModel):
    symbol: str
    current_price: float
    spx_price: float
    spx_source: str
    day_high_spx: float
    day_low_spx: float
    range_position: float
    ema_9: float
    ema_21: float
    rsi_14: float
    chop_value: float
    er_value: float
    vwap_dev: float
    regime_state: str
    regime_score: int
    continuous_score: float
    directional_bias: str
    recommended_moat: str
    effective_moat_min: int
    stop_loss_rule: str
    sub_scores: SubScores
    time_pressure: TimePressure
    momentum: Momentum
    smart_moat_data: SmartMoat
    timestamp: str
    positions: list[EvaluatedPosition]
    recommendations: list[Recommendation]
    watch_levels: WatchLevels
    position_summary: PositionSummary | None = None


# --- API ENDPOINTS ---

@app.post("/api/positions")
def create_position(pos: PositionCreate, db: Session = Depends(get_db)):
    """Saves a new contract to the SQLite memory."""
    new_pos = PositionDB(type=pos.type, strike=pos.strike, credit=pos.credit)
    db.add(new_pos)
    db.commit()
    db.refresh(new_pos)
    logger.info(f"Created new position ID: {new_pos.id} ({pos.type} @ {pos.strike})")
    return {"status": "success", "id": new_pos.id}


@app.post("/api/positions/{pos_id}/close")
def close_position(pos_id: int, db: Session = Depends(get_db)):
    """Archives a position as closed for future analytics."""
    pos = db.query(PositionDB).filter(PositionDB.id == pos_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    closed = ClosedPositionDB(
        original_id=pos.id,
        type=pos.type,
        strike=pos.strike,
        credit=pos.credit,
        opened_at=pos.created_at,
        close_reason="manual",
    )
    db.add(closed)
    db.delete(pos)
    db.commit()
    logger.info(f"Closed and archived position ID: {pos_id} ({pos.type} @ {pos.strike})")
    return {"status": "closed", "archived_id": closed.id}


@app.delete("/api/positions/{pos_id}")
def delete_position(pos_id: int, db: Session = Depends(get_db)):
    """Hard deletes a position (for entries added by mistake)."""
    pos = db.query(PositionDB).filter(PositionDB.id == pos_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    db.delete(pos)
    db.commit()
    logger.info(f"Hard deleted position ID: {pos_id}")
    return {"status": "deleted"}


@app.get("/api/telemetry", response_model=TelemetryResponse)
def get_telemetry(db: Session = Depends(get_db)):
    """Fetches market data, calculates regime, and evaluates live positions."""
    logger.info("Processing GET request to /api/telemetry")
    df, live_price = fetch_alpaca_market_data("SPY")

    if df is None or df.empty:
        logger.error("Failed to fetch data from Alpaca API.")
        raise HTTPException(status_code=503, detail="Failed to fetch data from Alpaca API.")

    logger.info("Calculating technical indicators...")
    try:
        df.ta.ema(length=9, append=True)
        df.ta.ema(length=21, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.chop(length=14, append=True)
        df.ta.er(length=10, append=True)
        df.ta.vwap(append=True)

        df.dropna(inplace=True)
    except Exception as e:
        logger.exception("Error during indicator calculations:")
        raise HTTPException(status_code=500, detail=f"Error calculating technical indicators: {str(e)}")

    regime_data = analyze_market_regime(df)

    # Fetch authoritative SPX price (Yahoo ^GSPC with SPY proxy fallback)
    spx_price, spx_source = fetch_spx_live_price(spy_fallback_price=live_price)
    if spx_price is None:
        raise HTTPException(status_code=503, detail="Unable to determine SPX price from any source.")
    logger.info(f"SPX Price: ${spx_price:.2f} (source: {spx_source})")

    # Compute SPX-equivalent day range from SPY momentum data
    momentum_data = regime_data["momentum"]
    spx_spy_ratio = spx_price / live_price if live_price > 0 else 10.0
    day_high_spx = round(momentum_data["day_high_spy"] * spx_spy_ratio, 2)
    day_low_spx = round(momentum_data["day_low_spy"] * spx_spy_ratio, 2)
    range_position = momentum_data["range_position"]

    # Phase 4: Smart Moat — adjusts base moat using range, signal, time, exhaustion
    smart_moat_data = compute_smart_moat(
        regime_data, spx_price, day_high_spx, day_low_spx, range_position,
    )
    smart_moat = smart_moat_data["smart_moat"]
    logger.info(f"Smart Moat: {smart_moat_data['moat_explanation']}")

    # Run Phase 3.2 Enhanced Position Intelligence with SMART moat
    db_positions = db.query(PositionDB).all()
    evaluated_positions = evaluate_positions(
        db_positions, spx_price, db,
        regime_score=regime_data["regime_score"],
        effective_moat_min=smart_moat,
        directional_bias=regime_data["directional_bias"],
        range_position=range_position,
        day_high_spx=day_high_spx,
        day_low_spx=day_low_spx,
        hours_remaining=regime_data["time_pressure"]["hours_remaining"],
        momentum_label=momentum_data.get("momentum_label", ""),
        vwap_dev=regime_data.get("vwap_dev", 0.0),
    )

    # Generate actionable recommendations
    # Pass rsi_14 and er_value into regime_data so recommender can reference them
    regime_data["rsi_14"] = round(df.iloc[-1]['RSI_14'], 2)
    regime_data["er_value"] = regime_data["er_value"]
    regime_data["effective_moat_min"] = smart_moat  # override with smart moat
    recommendations = generate_recommendations(
        evaluated_positions, spx_price, regime_data,
        day_high_spx, day_low_spx, range_position,
    )

    # Compute factual price levels to watch
    watch_levels = compute_watch_levels(
        spx_price, day_high_spx, day_low_spx, evaluated_positions,
    )

    # Compute combined position summary (iron condor view) with smart moat
    position_summary = compute_position_summary(
        evaluated_positions, spx_price, smart_moat,
    )

    logger.info(f"Telemetry formulated. Tracking {len(evaluated_positions)} positions. {len(recommendations)} recommendations.")
    return TelemetryResponse(
        symbol="SPY [Alpaca V2]",
        current_price=round(live_price, 2),
        spx_price=round(spx_price, 2),
        spx_source=spx_source,
        day_high_spx=day_high_spx,
        day_low_spx=day_low_spx,
        range_position=range_position,
        ema_9=round(df.iloc[-1]['EMA_9'], 2),
        ema_21=round(df.iloc[-1]['EMA_21'], 2),
        rsi_14=round(df.iloc[-1]['RSI_14'], 2),
        chop_value=regime_data["chop_value"],
        er_value=regime_data["er_value"],
        vwap_dev=regime_data["vwap_dev"],
        regime_state=regime_data["regime_state"],
        regime_score=regime_data["regime_score"],
        continuous_score=regime_data["continuous_score"],
        directional_bias=regime_data["directional_bias"],
        recommended_moat=regime_data["recommended_moat"],
        effective_moat_min=smart_moat,
        stop_loss_rule=regime_data["stop_loss_rule"],
        sub_scores=regime_data["sub_scores"],
        time_pressure=regime_data["time_pressure"],
        momentum=regime_data["momentum"],
        smart_moat_data=smart_moat_data,
        timestamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        positions=evaluated_positions,
        recommendations=recommendations,
        watch_levels=watch_levels,
        position_summary=position_summary,
    )


class TradeProposal(BaseModel):
    type: Literal["Put Spread", "Call Spread"]
    strike: float
    credit: float

    @field_validator("strike")
    @classmethod
    def strike_positive(cls, v):
        if v <= 0:
            raise ValueError("Strike must be a positive number")
        return v

    @field_validator("credit")
    @classmethod
    def credit_positive(cls, v):
        if v <= 0:
            raise ValueError("Credit must be a positive number")
        return v


@app.post("/api/analyze-trade")
def analyze_trade(proposal: TradeProposal, db: Session = Depends(get_db)):
    """
    Phase 5: Pre-trade analysis. Scores a proposed credit spread
    against current market conditions before entry.
    """
    logger.info(f"Analyzing trade proposal: {proposal.type} @ {proposal.strike} for ${proposal.credit}")

    # Fetch fresh market data (same pipeline as telemetry)
    df, live_price = fetch_alpaca_market_data("SPY")
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="Failed to fetch market data.")

    try:
        df.ta.ema(length=9, append=True)
        df.ta.ema(length=21, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.chop(length=14, append=True)
        df.ta.er(length=10, append=True)
        df.ta.vwap(append=True)
        df.dropna(inplace=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating indicators: {str(e)}")

    regime_data = analyze_market_regime(df)

    spx_price, spx_source = fetch_spx_live_price(spy_fallback_price=live_price)
    if spx_price is None:
        raise HTTPException(status_code=503, detail="Unable to determine SPX price.")

    momentum_data = regime_data["momentum"]
    spx_spy_ratio = spx_price / live_price if live_price > 0 else 10.0
    day_high_spx = round(momentum_data["day_high_spy"] * spx_spy_ratio, 2)
    day_low_spx = round(momentum_data["day_low_spy"] * spx_spy_ratio, 2)
    range_position = momentum_data["range_position"]

    smart_moat_data = compute_smart_moat(
        regime_data, spx_price, day_high_spx, day_low_spx, range_position,
    )
    smart_moat = smart_moat_data["smart_moat"]

    # Get existing positions for portfolio impact analysis
    db_positions = db.query(PositionDB).all()
    existing_positions = [
        {"type": p.type, "strike": p.strike, "credit": p.credit}
        for p in db_positions
    ]

    result = analyze_trade_proposal(
        trade_type=proposal.type,
        strike=proposal.strike,
        credit=proposal.credit,
        spx_price=spx_price,
        regime_data=regime_data,
        smart_moat=smart_moat,
        day_high_spx=day_high_spx,
        day_low_spx=day_low_spx,
        range_position=range_position,
        existing_positions=existing_positions,
        momentum_label=momentum_data.get("momentum_label", ""),
        vwap_dev=regime_data.get("vwap_dev", 0.0),
    )

    logger.info(f"Trade analysis: {result['verdict']} (score {result['score']})")
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)