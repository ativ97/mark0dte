from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
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
from data_fetcher import fetch_alpaca_market_data, fetch_spx_live_price, fetch_spx_day_range, fetch_vix_data, compute_expected_move, fetch_gex_data, fetch_realized_move_distribution
from engine import analyze_market_regime, evaluate_positions, generate_recommendations, compute_watch_levels, compute_position_summary, compute_smart_moat, analyze_trade_proposal, clear_rec_state, auto_propose_positions, generate_market_insights
from database import Base, engine as db_engine, get_db, PositionDB, ClosedPositionDB
from accuracy_tracker import log_recommendation, resolve_position, clear_position_state, get_accuracy_stats, get_signal_log

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


class IntradayWindow(BaseModel):
    window: str
    label: str
    description: str
    entry_quality: int
    volatility_tendency: str
    advice: str


class MarketEvents(BaseModel):
    events: list[str]
    moat_multiplier: float
    risk_level: str
    day_of_week: str


class TimePressure(BaseModel):
    hours_remaining: float
    time_pressure_level: str
    time_pressure_label: str
    moat_multiplier: float
    intraday_window: IntradayWindow
    market_events: MarketEvents


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
    move_consumed_factor: float = 1.0
    move_consumed_pct: float = 0.0


class RegimeTransition(BaseModel):
    direction: str
    label: str
    confidence: float
    score_delta_30m: float
    er_trend: str
    chop_trend: str


class GexLevel(BaseModel):
    strike_spy: float
    strike_spx: int
    gex: float
    call_oi: int
    put_oi: int


class GexData(BaseModel):
    net_gex: float = 0
    gex_regime: str = "UNAVAILABLE"
    gex_regime_label: str = "GEX data unavailable"
    gamma_wall_spy: float = 0
    gamma_wall_spx: float = 0
    put_wall_spy: float = 0
    put_wall_spx: float = 0
    call_wall_spy: float = 0
    call_wall_spx: float = 0
    top_levels: list[GexLevel] = []
    total_strikes: int = 0
    spy_price: float = 0
    data_source: str = "unavailable"
    expiration: str = ""


class ExpectedMove(BaseModel):
    vix: float | None = None
    vix9d: float | None = None
    effective_vol: float | None = None
    expected_1sigma: float | None = None
    conditional_1sigma: float | None = None
    expected_2sigma: float | None = None
    recommended_moat: float | None = None
    hours_remaining: float | None = None
    move_consumed_pts: float = 0.0
    move_consumed_pct: float = 0.0
    full_day_1sigma: float | None = None
    day_open_spx: float | None = None
    explanation: str = "VIX data unavailable"


class IntradayPL(BaseModel):
    closed_pl: float = 0
    open_pl: float = 0
    total_pl: float = 0
    closed_count: int = 0
    open_count: int = 0


class RealizedDistribution(BaseModel):
    available: bool = False
    lookback_days: int | None = None
    exceedance: dict | None = None
    mean_abs_move_pct: float | None = None
    median_abs_move_pct: float | None = None
    explanation: str = "Realized distribution unavailable"


class InsightPositionCard(BaseModel):
    id: int
    light: str
    type: str
    strike: float
    summary: str
    verdict: str
    action: str
    moat: float
    profit_pct: float = 0
    reversal_score: int = 0
    heat_score: int = 0
    context: str = ""


class InsightKeyLevel(BaseModel):
    level: float
    label: str
    meaning: str


class InsightActionItem(BaseModel):
    priority: str
    message: str


class MarketInsights(BaseModel):
    market_light: str = "GREEN"
    market_headline: str = ""
    market_story: str = ""
    position_cards: list[InsightPositionCard] = []
    key_levels: list[InsightKeyLevel] = []
    action_items: list[InsightActionItem] = []
    timestamp: str = ""


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
    expected_move: ExpectedMove
    gex_data: GexData | None = None
    realized_distribution: RealizedDistribution | None = None
    regime_transition: RegimeTransition
    timestamp: str
    positions: list[EvaluatedPosition]
    recommendations: list[Recommendation]
    watch_levels: WatchLevels
    position_summary: PositionSummary | None = None
    intraday_pl: IntradayPL | None = None
    trade_proposals: list | None = None
    accuracy_stats: dict | None = None
    market_insights: MarketInsights | None = None


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
def close_position(pos_id: int, close_price: float = None, db: Session = Depends(get_db)):
    """Archives a position as closed for future analytics."""
    pos = db.query(PositionDB).filter(PositionDB.id == pos_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    realized_pl = round(pos.credit - close_price, 2) if close_price is not None else None
    won = realized_pl is not None and realized_pl >= 0
    closed = ClosedPositionDB(
        original_id=pos.id,
        type=pos.type,
        strike=pos.strike,
        credit=pos.credit,
        opened_at=pos.created_at,
        close_reason="manual",
        close_price=close_price,
        realized_pl=realized_pl,
    )
    db.add(closed)
    db.delete(pos)
    db.commit()
    clear_rec_state(pos_id)
    resolve_position(pos_id, won=won, realized_pl=realized_pl, close_reason="manual")
    logger.info(f"Closed and archived position ID: {pos_id} ({pos.type} @ {pos.strike}), close_price={close_price}, P/L={realized_pl}")
    return {"status": "closed", "archived_id": closed.id, "realized_pl": realized_pl}


@app.delete("/api/positions/{pos_id}")
def delete_position(pos_id: int, db: Session = Depends(get_db)):
    """Hard deletes a position (for entries added by mistake)."""
    pos = db.query(PositionDB).filter(PositionDB.id == pos_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    db.delete(pos)
    db.commit()
    clear_rec_state(pos_id)
    clear_position_state(pos_id)
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

    # Fetch authoritative SPX day high/low from Yahoo ^GSPC (fixes SPY-ratio drift bug)
    momentum_data = regime_data["momentum"]
    spx_spy_ratio = spx_price / live_price if live_price > 0 else 10.0
    spx_range = fetch_spx_day_range(
        spy_day_high=momentum_data["day_high_spy"],
        spy_day_low=momentum_data["day_low_spy"],
        spx_spy_ratio=spx_spy_ratio,
    )
    day_high_spx = spx_range["day_high_spx"] or round(momentum_data["day_high_spy"] * spx_spy_ratio, 2)
    day_low_spx = spx_range["day_low_spx"] or round(momentum_data["day_low_spy"] * spx_spy_ratio, 2)
    day_open_spx = spx_range.get("day_open_spx")
    range_position = momentum_data["range_position"]
    logger.info(f"SPX Day Range: High={day_high_spx}, Low={day_low_spx}, Open={day_open_spx} (source: {spx_range['source']})")

    # Phase 7: Fetch VIX data for expected move calculation
    vix_data = fetch_vix_data()
    hours_remaining = regime_data["time_pressure"]["hours_remaining"]
    expected_move_data = None
    vix_based_moat = None
    if vix_data["vix"] is not None:
        expected_move_data = compute_expected_move(
            spx_price, vix_data["vix"], vix_data.get("vix9d"),
            hours_remaining=hours_remaining,
            day_open_spx=day_open_spx,
        )
        vix_based_moat = expected_move_data["recommended_moat"]
        logger.info(f"VIX Expected Move: {expected_move_data['explanation']}")

    # Phase 11: Fetch realized daily move distribution (cached per day)
    realized_dist = fetch_realized_move_distribution()

    # Phase 9: Fetch GEX data from ThetaData (moved early so it feeds into smart moat)
    gex_data = None
    try:
        gex_raw = fetch_gex_data(spy_price=live_price, spx_spy_ratio=spx_spy_ratio)
        if gex_raw and gex_raw.get("gex_regime") != "UNAVAILABLE":
            gex_data = gex_raw
            logger.info(f"GEX: {gex_raw['gex_regime']} — net {gex_raw['net_gex']:,.0f}, "
                        f"gamma wall SPX {gex_raw['gamma_wall_spx']}, "
                        f"put wall SPX {gex_raw['put_wall_spx']}")
    except Exception as e:
        logger.warning(f"GEX fetch skipped: {e}")

    # Phase 4: Smart Moat — adjusts base moat using range, signal, time, exhaustion, GEX
    # If VIX data available, use VIX-based moat as override for the base moat
    smart_moat_data = compute_smart_moat(
        regime_data, spx_price, day_high_spx, day_low_spx, range_position,
        vix_based_moat=vix_based_moat,
        gex_data=gex_data,
        expected_move_data=expected_move_data,
        day_open_spx=day_open_spx,
    )
    smart_moat = smart_moat_data["smart_moat"]
    logger.info(f"Smart Moat: {smart_moat_data['moat_explanation']}")

    # Run Phase 3.2 Enhanced Position Intelligence with SMART moat + GEX
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
        gex_data=gex_data,
        rsi_14=round(df.iloc[-1]['RSI_14'], 2),
        er_value=regime_data["er_value"],
    )

    # Log recommendations to accuracy tracker
    for ep in evaluated_positions:
        exit_strat = ep.get("exit_strategy", {})
        log_recommendation(
            pos_id=ep["id"],
            pos_type=ep["type"],
            strike=ep["strike"],
            credit=ep["credit"],
            action=exit_strat.get("action", "UNKNOWN"),
            regime_score=regime_data["regime_score"],
            moat=ep.get("moat", 0),
            escalation=exit_strat.get("escalation_level"),
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

    # Phase 14: Intraday P/L dashboard — aggregate open + closed P/L
    today_start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    todays_closed = db.query(ClosedPositionDB).filter(ClosedPositionDB.closed_at >= today_start).all()
    closed_pl = sum(c.realized_pl for c in todays_closed if c.realized_pl is not None)
    open_pl = sum(p.get("estimated_pl", 0) for p in evaluated_positions)
    intraday_pl = {
        "closed_pl": round(closed_pl, 2),
        "open_pl": round(open_pl, 2),
        "total_pl": round(closed_pl + open_pl, 2),
        "closed_count": len(todays_closed),
        "open_count": len(evaluated_positions),
    }

    # Phase 15: Auto-propose new positions when moat allows
    trade_proposals = auto_propose_positions(
        spx_price=spx_price,
        regime_data=regime_data,
        smart_moat=smart_moat,
        day_high_spx=day_high_spx,
        day_low_spx=day_low_spx,
        range_position=range_position,
        existing_positions=evaluated_positions,
        momentum_label=regime_data["momentum"]["momentum_label"],
        vwap_dev=regime_data.get("vwap_dev", 0),
        gex_data=gex_data,
    )

    # Phase 2: Generate plain-English market insights for the Insights tab
    market_insights = generate_market_insights(
        regime_data=regime_data,
        evaluated_positions=evaluated_positions,
        smart_moat_data=smart_moat_data,
        expected_move_data=expected_move_data,
        gex_data=gex_data,
        spx_price=spx_price,
        day_high_spx=day_high_spx,
        day_low_spx=day_low_spx,
        recommendations=recommendations,
    )

    logger.info(f"Telemetry formulated. Tracking {len(evaluated_positions)} positions. {len(recommendations)} recommendations. Day P/L: ${intraday_pl['total_pl']}. {len(trade_proposals)} proposals.")
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
        expected_move=expected_move_data or {"explanation": "VIX data unavailable"},
        gex_data=gex_data,
        realized_distribution=realized_dist if realized_dist.get("available") else None,
        regime_transition=regime_data["regime_transition"],
        timestamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        positions=evaluated_positions,
        recommendations=recommendations,
        watch_levels=watch_levels,
        position_summary=position_summary,
        intraday_pl=intraday_pl,
        trade_proposals=trade_proposals if trade_proposals else None,
        accuracy_stats=get_accuracy_stats(),
        market_insights=market_insights,
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
    spx_range = fetch_spx_day_range(
        spy_day_high=momentum_data["day_high_spy"],
        spy_day_low=momentum_data["day_low_spy"],
        spx_spy_ratio=spx_spy_ratio,
    )
    day_high_spx = spx_range["day_high_spx"] or round(momentum_data["day_high_spy"] * spx_spy_ratio, 2)
    day_low_spx = spx_range["day_low_spx"] or round(momentum_data["day_low_spy"] * spx_spy_ratio, 2)
    range_position = momentum_data["range_position"]

    # Fetch GEX for trade analysis
    gex_data = None
    try:
        gex_raw = fetch_gex_data(spy_price=live_price, spx_spy_ratio=spx_spy_ratio)
        if gex_raw and gex_raw.get("gex_regime") != "UNAVAILABLE":
            gex_data = gex_raw
    except Exception:
        pass

    smart_moat_data = compute_smart_moat(
        regime_data, spx_price, day_high_spx, day_low_spx, range_position,
        gex_data=gex_data,
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
        gex_data=gex_data,
    )

    logger.info(f"Trade analysis: {result['verdict']} (score {result['score']})")
    return result


# --- TRADE HISTORY & BACKTEST ENDPOINTS ---

@app.post("/api/trade-history/upload")
async def upload_trade_history(file: UploadFile = File(...)):
    """
    Upload a Robinhood CSV export. Parses credit spreads and returns
    trade stats + individual spread details.
    """
    from trade_history import analyze_trade_history

    content = await file.read()
    csv_text = content.decode("utf-8", errors="ignore")
    logger.info(f"Trade history upload: {file.filename} ({len(csv_text)} bytes)")

    result = analyze_trade_history(csv_text)
    if result.get("error") and not result.get("spreads"):
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/trade-history/backtest")
async def backtest_trade_history(file: UploadFile = File(...)):
    """
    Upload a Robinhood CSV and replay each trade date through the regime engine
    using historical Alpaca 5-min bars. Returns per-day regime analysis showing
    what the system would have recommended for the user's actual strikes.
    """
    from trade_history import parse_csv, identify_spreads, compute_trade_stats
    from backtester import run_backtest

    content = await file.read()
    csv_text = content.decode("utf-8", errors="ignore")
    logger.info(f"Backtest upload: {file.filename} ({len(csv_text)} bytes)")

    transactions = parse_csv(csv_text)
    if not transactions:
        raise HTTPException(status_code=400, detail="No option transactions found in CSV")

    spreads = identify_spreads(transactions)
    if not spreads:
        raise HTTPException(status_code=400, detail="No credit spreads identified in CSV")

    trade_stats = compute_trade_stats(spreads)

    # Use live SPX/SPY ratio or default
    spx_spy_ratio = 10.0
    try:
        from data_fetcher import get_spx_spy_ratio
        ratio_info = get_spx_spy_ratio()
        spx_spy_ratio = ratio_info["ratio"]
    except Exception:
        pass

    logger.info(f"Running backtest on {len(spreads)} spreads across {len(set(s['iso_date'] for s in spreads))} dates")
    backtest_result = run_backtest(spreads, spx_spy_ratio=spx_spy_ratio)

    return {
        "trade_stats": trade_stats,
        "backtest": backtest_result,
        "spreads_parsed": len(spreads),
    }


@app.get("/api/accuracy/signals")
def get_accuracy_signals(limit: int = 50):
    """Returns recent accuracy tracker signals for inspection."""
    return {
        "signals": get_signal_log(limit=limit),
        "stats": get_accuracy_stats(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)