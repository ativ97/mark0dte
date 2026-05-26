# 0DTE Algorithmic Decision Support System

**System Architecture & State Rules - Version 5.6**

## 1. Core Philosophy

The objective of this algorithm is to act as a **Human-in-the-Loop Regime Classifier**. It ingests live market telemetry (Alpaca Real-Time SPY data + Yahoo Finance VIX/SPX) to determine the current operational environment (State) and outputs dynamic structural constraints (Moat Width, Stop-Loss Limits) to protect short premium positions. The system trades **SPX 0DTE options** using SPY as a data proxy.

Version 5.5 adds **Advanced Position Intelligence**: realized daily move distribution, cumulative drift tracker, position premium history, intraday P/L dashboard, auto-proposed trade candidates, moat zone hysteresis, and graduated exit escalation. Version 5.0 introduced **GEX (Gamma Exposure) Integration**, **Trade History Analysis & Backtesting**, and extends V4.0 features: **VIX-Based Expected Move Moats**, **Time-Aware Exit Strategies**, **Intraday Window Classification**, **Regime Transition Prediction**, and **Calendar Event Awareness**.

## 2. Telemetry Ingestion (The Ensemble Matrix)

The engine monitors the following metrics on a **5-Minute timeframe** and assigns a `+1` penalty score for inefficiency/chop. All thresholds are centrally configurable in `backend/config.py`.

* **Moving Average Compression:** EMA 9 and EMA 21 (Diff < 0.1% of price). Threshold: `EMA_COMPRESSION_THRESHOLD_PCT`
* **Oscillator Exhaustion:** RSI (14) stuck in 45-55. Thresholds: `RSI_DEAD_ZONE_LOWER` / `RSI_DEAD_ZONE_UPPER`
* **Trend Inefficiency:** Choppiness Index (CHOP) > 61.8. Threshold: `CHOP_THRESHOLD`
* **Price Path Inefficiency:** Kaufman's Efficiency Ratio (ER) < 0.20. Threshold: `EFFICIENCY_RATIO_THRESHOLD`

*V1.2 Addition:* **VWAP Elasticity Override.** If SPY deviation from cumulative session VWAP > 0.35%, stop-losses are suspended to absorb mean-reversion bounces. Threshold: `VWAP_ELASTICITY_THRESHOLD_PCT`

## 3. SPX Proxy Methodology

Alpaca does not provide direct SPX index data. The system derives SPX from **SPY × `SPX_PROXY_MULTIPLIER`** (default: 10.0). This ratio drifts over time due to dividends, expense ratio, and rounding. At the current multiplier, a 0.1% drift at SPX ~5900 = ~5.9 points — significant given the 10-point Gamma Trap boundary.

**Action Required:** Periodically calibrate `SPX_PROXY_MULTIPLIER` in `config.py` against the actual SPX/SPY ratio.

## 4. V3.0 Risk Boundaries & Position Intelligence

All position risk evaluation is performed **server-side** in `backend/engine.py`. Positions are persisted in a local SQLite database (`backend/database.py`). The React frontend is a "dumb" renderer — it displays the backend's computed `status_color`, `moat`, and `message` without performing its own math.

### 4.1 Asset-Boundary Zones

* **SAFE ZONE (> 25 Points):** Allow Theta decay. No action required. Threshold: `SAFE_ZONE_THRESHOLD`
* **WARNING ZONE (≤ 25 Points):** Volatility expansion likely. Stop-loss directive adapts to current Regime State (see §5). Threshold: `WARNING_ZONE_THRESHOLD`
* **GAMMA TRAP (≤ 10 Points):** Time-Delayed Verification initiated. If confirmed, mandatory eject regardless of regime. Threshold: `GAMMA_TRAP_THRESHOLD`

### 4.2 Time-Delayed Verification Stops (Whipsaw Immunity)

When a position enters the Gamma Trap boundary:

1. The engine stamps `breach_start_time` in the database.
2. A countdown of `BREACH_VERIFICATION_MINUTES` (default: 5) begins.
3. **If the price remains breached** after the timer expires → **CRITICAL EJECT** (Kill Switch).
4. **If the price recovers** before the timer expires → Timer is cleared. Position stays open. This defeats liquidity-grab flash wicks and "rubber band" V-reversals.

### 4.3 Regime-Aware Tiered Stops (Warning Zone)

When a position is in the Warning Zone (moat ≤ 25, > 10), the stop-loss directive changes based on the active Regime State:

* **State A (Score 0-1):** "Strict 200% premium stop active."
* **State B (Score 2):** "Hybrid stop: 250% premium OR 15-pt asset breach."
* **State C (Score 3-4):** "Asset-boundary stop ONLY (ignore premium spikes)."

## 5. The State Machine Routing

* **Score 0 to 1 [State A: Clean Trend]:** Directional Bias Allowed. Moat: 35-40 Points. Strict 200% Premium Hit.
* **Score 2 [State B: Moderate Chop]:** Neutral Condors. Moat: 50-60 Points. Hybrid Stop (250% Premium or 15-pt Breach).
* **Score 3 to 4 [State C: High Entropy]:** Strictly Neutral. Moat: 70+ Points. Asset Boundary Stops ONLY (Ignore premium).

## 6. Data & API Architecture

* **Data Source:** Alpaca Markets V2 (SPY 5-min bars + latest trade tick).
* **Indicator Library:** pandas-ta-classic (EMA, RSI, CHOP, ER, VWAP).
* **VWAP Handling:** Alpaca's bar-level VWAP is stored as `VWAP_BAR`. The cumulative session VWAP is calculated by pandas-ta and used for elasticity deviation.
* **Credentials:** Loaded from `backend/.env` via `python-dotenv`. Never hardcoded.
* **Database:** SQLite via SQLAlchemy. Positions table stores type, strike, credit, created_at, and breach_start_time.
* **Frontend Polling:** 30-second interval.
* **Input Validation:** Position type restricted to `Put Spread | Call Spread | Iron Condor`. Strike and credit must be positive numbers.

## 7. Phase 4: Smart Moat System

Version 4.0 introduces the **Smart Moat** — a dynamic moat adjustment engine that modifies the base regime moat using four real-time factors. The 3-state machine (A/B/C) is preserved for the trader's mental model, but the *actions within each state* are now context-aware.

### 7.1 Range Context
Evaluates the day's trading range to determine if chop is contained or expanding:
* **TIGHT** (< 40 pts): Range-bound, moat reduced 30%
* **CONTAINED** (40-70 pts): Moderate range, moat reduced 15%
* **NORMAL** (70-110 pts): Standard moat applies
* **EXPANDING** (> 110 pts): Wide swings, moat increased 15%

### 7.2 Signal Quality
Uses Efficiency Ratio and continuous score to detect if a directional move is forming:
* **DEAD** (ER < 0.05, score > 3.5): Pure noise, no threat forming. Moat reduced 20%
* **NOISE** (ER < 0.10): Low signal, moat reduced 10%
* **WEAK** (ER < 0.20): Standard
* **DIRECTIONAL** (ER ≥ 0.20): Trend forming, moat increased 10%

### 7.3 Time-Decay Survival Credit
Positions that survived the day earn lower moat requirements as theta accelerates:
* > 4.5h remaining: Full moat (morning)
* 3-4.5h: 15% reduction
* 2-3h: 25% reduction
* 1-2h: 35% reduction
* < 1h: 45% reduction (theta crushing premium)

### 7.4 Range Exhaustion Detection
If SPX has tested both extremes of the day's range (> 15 pts from each) and returned to the middle third (30-70% range position), the range is "established" — further 10% moat reduction.

### 7.5 Smart Moat Floor
The smart moat never drops below `WARNING_ZONE_THRESHOLD + 5` (30 pts) to preserve minimum safety margin.

## 8. Phase 6: Time-Aware Exit Strategies

When positions enter the Warning Zone, exit behavior adapts to time remaining until close:

* **Final 30 min (3:30-4:00 PM):** `HOLD_FOR_EXPIRY` — only exit if strike is actually breached. Premium spikes are ignored. Theta is nuclear at this point.
* **Final hour (3:00-3:30 PM):** `HOLD_WITH_TRIGGER` — premium stops suspended. Require 10-minute sustained asset breach before exiting.
* **1-2 hours left (2:00-3:00 PM):** `CLOSE_SOON` — widened 250% stop with 5-minute verification. Filters out afternoon whipsaws.
* **> 2 hours left:** Standard regime-based stops (A/B/C rules).
* **State C always uses aggressive asset-boundary stops** regardless of time.

## 9. Phase 7: VIX-Based Expected Move

The Smart Moat base is now derived from VIX math instead of static State A/B/C tables:

**Formula:** `Expected Move = SPX × (VIX / 100) × sqrt(hours_remaining / 1638)`

Where 1638 = trading hours per year (252 days × 6.5 hours).

* `VIX` and `VIX9D` (9-day VIX, preferred for 0DTE) fetched from Yahoo Finance with 120-second cache.
* If VIX9D is unavailable, system uses `VIX × 0.85` as a proxy.
* Returns: **1-sigma** (68% range), **2-sigma** (95% range), and **recommended moat** (1.5σ).
* The recommended moat overrides the static State A/B/C base moat in `compute_smart_moat()`.
* All Smart Moat adjustment factors (range, signal, time, exhaustion, events) still apply on top.

## 10. Phase 8: Intraday Window Classification & Regime Transition

### 10.1 Trading Windows
`_classify_intraday_window()` classifies the current time into known behavioral periods:

| Window | Time (ET) | Entry Quality | Volatility |
|---|---|---|---|
| Opening Drive | 9:30-10:00 | 20/100 | ELEVATED |
| Trend Establishment | 10:00-11:30 | 90/100 | MODERATE |
| Lunch Lull | 11:30-1:00 | 65/100 | LOW |
| Afternoon Session | 1:00-2:30 | 55/100 | MODERATE |
| Pre-Power Hour | 2:30-3:00 | 25/100 | RISING |
| Power Hour | 3:00-3:45 | 10/100 | HIGH |
| Final Minutes | 3:45-4:00 | 0/100 | EXTREME_THETA |

### 10.2 Regime Transition Prediction
`_compute_regime_transition()` compares sub-scores (CHOP, ER, RSI, EMA intensities) now vs 30 minutes ago (6 bars):

* **DETERIORATING** (Δ > +0.5): Chop increasing rapidly. Widen moats.
* **SOFTENING** (Δ > +0.2): Trend weakening. Monitor.
* **STABLE** (-0.2 to +0.2): No transition imminent.
* **FIRMING** (Δ < -0.2): Chop resolving. Direction forming.
* **IMPROVING** (Δ < -0.5): Strong trend returning. Tighter moats viable.

Also tracks individual ER and CHOP rate-of-change with confidence scores.

## 11. Phase 10: Calendar Event Awareness

`_check_market_events()` identifies high-volatility days and applies moat multipliers:

| Event | Multiplier | Risk Level |
|---|---|---|
| FOMC Meeting Day | ×1.40 | ELEVATED |
| CPI Release Window | ×1.30 | ELEVATED |
| NFP (First Friday) | ×1.30 | ELEVATED |
| Monthly OPEX (3rd Fri) | ×1.15 | MODERATE |
| Quarterly OPEX (3rd Fri Mar/Jun/Sep/Dec) | ×1.50 | HIGH |
| Monday gap risk | ×1.10 | NORMAL |

The event multiplier is integrated as the 5th factor in `compute_smart_moat()`:
`combined = range × signal × time × exhaustion × event`

FOMC 2026 dates are hardcoded. CPI/NFP use heuristic date ranges (10th-15th Tue/Wed, 1st Friday).

## 12. Phase 9: GEX (Gamma Exposure) Integration

### 12.1 Data Source
Real-time and historical options chain data from **ThetaData** (Standard subscription). The system fetches SPY 0DTE first-order greeks (delta, IV) and open interest, then computes gamma via Black-Scholes:

`gamma = N'(d1) / (S × σ × √T)` where `d1 = [ln(S/K) + (r + 0.5σ²)T] / (σ√T)`

Second-order greeks (gamma directly) require the Professional tier ($200+/month), so the Standard subscription uses manual BS computation from IV.

### 12.2 GEX Calculation
Per-strike GEX: `gamma × OI × 100 × spot`. Calls contribute positive GEX (dealers short calls → long gamma), puts contribute negative GEX (dealers short puts → short gamma).

### 12.3 Key Levels
* **Gamma Wall** (highest positive GEX strike): Acts as a price magnet — SPX tends to gravitate toward this level.
* **Put Wall** (most negative GEX strike): Acts as a floor / support level.
* **Call Wall** (highest call-side GEX strike): Acts as a ceiling / resistance level.

### 12.4 GEX Regime Classification
* **POSITIVE** (net GEX > 0): Dealers are long gamma → mean-reverting environment. Ranges hold, breakouts fade. Safer for credit spreads.
* **NEGATIVE** (net GEX < -50k): Dealers are short gamma → trending/volatile. Moves accelerate, ranges break. Wider moats needed.
* **NEUTRAL**: Balanced gamma exposure.

### 12.5 GEX as 6th Smart Moat Factor
The GEX regime is integrated into `compute_smart_moat()` as the 6th multiplicative factor:
`combined = range × signal × time × exhaustion × event × gex`

| GEX Regime | Factor | Rationale |
|---|---|---|
| POSITIVE | ×0.90 | Mean-reverting, tighter moat OK |
| NEUTRAL | ×1.00 | No adjustment |
| NEGATIVE | ×1.15 | Trending/volatile, widen moat |

### 12.6 GEX in Position Evaluation
`evaluate_positions()` appends GEX wall proximity context to position messages:
* Put spreads: checks distance to put wall (support) and gamma wall magnet effect.
* Call spreads: checks distance to call wall (resistance) and gamma wall magnet effect.
* Warns when strikes are at/beyond their protective wall.

### 12.7 GEX in Pre-Trade Analysis
`analyze_trade_proposal()` adds a GEX scoring component (§9):
* **Bonus** (up to +8 pts): Strike is safely beyond its protective wall.
* **Penalty** (up to -6 pts): Strike at/beyond wall + negative GEX regime.
* Positive GEX regime adds +3 bonus; negative GEX adds -3 penalty.

### 12.8 Cache & Refresh
GEX data is cached for **2 minutes** (reduced from 5 min) for more responsive wall tracking during fast moves. Falls back to stale cache on failure.

## 13. Phase 12: Trade History & Backtester

### 13.1 Trade History Parser (`trade_history.py`)
* `parse_csv()`: Parses Robinhood brokerage CSV exports, handles multi-line CUSIP fields, filters to SPXW/SPY option transactions.
* `identify_spreads()`: Greedy quantity-matched, width-filtered pairing of STO/BTO legs. Max width: 15pt SPXW, 5pt SPY.
* `compute_trade_stats()`: Win rate, P/L, profit factor, put/call splits, outcome distribution, best/worst trade.

### 13.2 Backtester (`backtester.py`)
* `fetch_historical_bars(symbol, date)`: Alpaca intraday bars for specific date.
* `replay_trade_day(df, spreads, ratio, gex_data)`: Replays full day through regime engine bar-by-bar, tracks moat to user's actual strikes.
* **Historical GEX**: For each trade date, the backtester fetches historical options data from ThetaData (8 years of history) and includes GEX regime/walls in the day summary.
* **System Verdicts**: SAFE / CAUTION / EXIT_RECOMMENDED per spread.
* **Alignment Labels**: ALIGNED_WIN / SYSTEM_CORRECT / LUCKY_WIN / BOTH_WRONG — compares user outcome vs system recommendation.
* **Time Workaround**: Robinhood CSV has no entry timestamps; the engine replays the entire day.

### 13.3 API Endpoints
* `POST /api/trade-history/upload`: Parse-only, returns stats + spreads.
* `POST /api/trade-history/backtest`: Parse + replay all dates through regime engine with historical GEX.

## 14. Phase 11: Realized Daily Move Distribution

`fetch_realized_move_distribution()` in `data_fetcher.py` fetches the last 120 trading days of ^GSPC daily closes from Yahoo Finance and computes:

* **Exceedance percentages**: What fraction of days saw moves ≥ ±0.5%, ±1.0%, ±1.5%, ±2.0%.
* **Mean absolute move %**: Average daily |%change|.
* **Median absolute move %**: Median daily |%change|.

Data is cached once per calendar day (TTL: midnight rollover). Displayed in the "VIX Expected Move" panel as a "Reality Check" against the VIX-implied expected move.

## 15. Phase 12b: Cumulative Drift Tracker

`_update_drift_tracker()` records SPX price at each telemetry refresh (30s). `compute_drift_toward_strike()` computes the net directional movement over a rolling 90-minute window.

* **Window**: 90 minutes (`DRIFT_WINDOW_MINUTES`)
* **Alert threshold**: 10 SPX points (`DRIFT_ALERT_THRESHOLD_PTS`)
* If SPX has drifted ≥ 10 pts toward a position's strike over the window, a `drift_alert` is attached to that position.
* Displayed as an orange "↗ DRIFT +Xpts" badge on position cards.
* Generates a `DRIFT_WARNING` recommendation in `generate_recommendations()` when triggered.

**Purpose**: Detects slow, steady price movement that doesn't trigger zone changes but still erodes safety over time.

## 16. Phase 13: Position Premium History

`_update_premium_history()` stores the last 10 estimated buyback values per position with timestamps.

* **Max readings**: 10 (`PREMIUM_HISTORY_MAX`)
* **Trend detection**: Compares last 3+ readings to classify as:
  * `RISING` — buyback cost increasing (position deteriorating)
  * `FALLING` — buyback cost decreasing (position improving / theta working)
  * `STABLE` — minimal change
  * `VOLATILE` — inconsistent swings
* Returns min, max, average, and full value history.
* Displayed below exit strategy on position cards.

## 17. Phase 14: Intraday P/L Dashboard

Aggregates realized + unrealized P/L across all positions for the current trading day:

* **Closed P/L**: Sum of `realized_pl` from `ClosedPositionDB` records closed today. `realized_pl = credit - close_price`.
* **Open P/L**: Sum of `estimated_pl` from all currently evaluated open positions.
* **Total P/L**: `closed_pl + open_pl`.

`ClosedPositionDB` schema extended with `close_price` (Float, nullable) and `realized_pl` (Float, nullable). The `/api/positions/{id}/close` endpoint accepts an optional `close_price` query parameter to compute P/L on archival.

Displayed as a color-coded "Day P/L" banner above the position summary in the frontend.

## 18. Phase 15: Auto-Propose New Positions

`auto_propose_positions()` in `engine.py` generates candidate credit spread entries:

* **Candidate generation**: 3 strikes per side (Put Spread + Call Spread) at 1×, 1.25×, 1.5× the current smart moat, rounded to nearest 5-pt SPX increment.
* **Credit estimation**: Rough model based on moat distance and hours remaining. Rejects candidates with estimated credit < $0.15.
* **Scoring**: Each candidate is passed through `analyze_trade_proposal()` and scored 0-100.
* **Filtering**: Only STRONG_ENTRY and ACCEPTABLE verdicts are returned. Top 4 by score.
* **Suppression**: No proposals when < 1 hour until market close.

Displayed as "Trade Ideas" cards in the frontend with score, verdict, estimated credit, moat, and key reasons.

## 19. Phase 16: Threshold Hysteresis for Moat Transitions

`_apply_moat_hysteresis()` prevents rapid zone oscillation when price hovers near a boundary:

* **Per-position tracking**: `_moat_zone_state` dict tracks the current zone for each position ID.
* **Entry threshold**: Standard (e.g., moat drops to 25 → enters WARNING).
* **Exit threshold**: Standard + 15% buffer (`HYSTERESIS_BUFFER_PCT = 0.15`). E.g., must rise above 25 × 1.15 ≈ 29 pts to exit WARNING.
* **Direction-aware**: Worsening transitions use raw thresholds; improving transitions require the buffer.

Zones: `SAFE → CAUTION → WARNING → GAMMA_TRAP`.

## 20. Phase 17: Graduated CRITICAL EJECT Levels

`_get_escalation_level()` implements time-based escalation through danger levels:

* **Escalation chain**: `CAUTION → WARNING → CLOSE_RECOMMENDED → URGENT_CLOSE → CRITICAL_EJECT`
* **Minimum hold time**: 3 minutes (`ESCALATION_MIN_HOLD_MINUTES`) at each level before escalating.
* **Entry**: Position enters danger zone (moat ≤ WARNING_ZONE_THRESHOLD) → starts at CAUTION.
* **Escalation**: Each 3 minutes of sustained danger → advance one level.
* **De-escalation buffer**: Positions at CLOSE_RECOMMENDED or higher that recover drop to WARNING (not SAFE) for one cycle.
* **Bypass**: Strike breach (moat ≤ 0) immediately triggers CRITICAL_EJECT regardless of escalation state.

The escalation level is included in exit strategy output and displayed as a colored badge in the frontend:
* Amber = CLOSE_RECOMMENDED
* Dark red = URGENT_CLOSE
* Bright red = CRITICAL_EJECT

State is cleared per-position on close and globally on market close via `clear_rec_state()`.

## 21. System Modification Log

* **[V5.6] Phase 16 — Algo Intelligence (C1-C4):**
  - C1: Conditional expected move — `compute_expected_move()` discounts remaining σ by move already consumed from open. >0.3σ consumed triggers discount (floor 0.40×).
  - C4: Move-consumed smart moat — 7th multiplicative factor in `compute_smart_moat()`. Scale: 0.3σ→1.0, 1.0σ→0.85, 2.0σ→0.70, floor 0.65.
  - C2: Reversal-aware exits — `evaluate_positions()` computes reversal_score (0-100) from RSI extreme + ER weakness + GEX wall proximity + range position. Score ≥50 in WARNING zone downgrades CLOSE → HOLD_WITH_TRIGGER.
  - C3: Time-adjusted take profit — `generate_recommendations()` threshold: >3h→90%, 2-3h→80%, 1-2h→75%, <1h→50%.
  - #37: Momentum label fix — RANGEBOUND no longer fires when ER > 0.25 (directional signal present).
  - Plumbing: `fetch_spx_day_range()` returns `day_open_spx`. `evaluate_positions()` accepts `rsi_14`, `er_value`. SmartMoat/ExpectedMove schemas updated.
  - 18 unit tests (3 original + 15 new). All passing.
* **[V5.5] Phases 11-17 — Advanced Position Intelligence:**
  - Phase 11: Realized daily move distribution from 120 days of ^GSPC closes. Cached daily. "Reality Check" display.
  - Phase 12b: Cumulative drift tracker — 90-min rolling SPX drift toward strikes. Orange badge + recommendation.
  - Phase 13: Position premium history — last 10 buyback readings with RISING/FALLING/STABLE/VOLATILE trend.
  - Phase 14: Intraday P/L dashboard — closed_pl + open_pl aggregation. ClosedPositionDB extended with close_price/realized_pl.
  - Phase 15: Auto-propose positions — 6 candidates (3 per side), scored via analyze_trade_proposal, top 4 ACCEPTABLE+ shown.
  - Phase 16: Moat zone hysteresis — 15% exit buffer prevents WARNING/CAUTION flip-flopping.
  - Phase 17: Graduated exit escalation — CAUTION→WARNING→CLOSE_RECOMMENDED→URGENT_CLOSE→CRITICAL_EJECT with 3-min holds.
  - Frontend: Day P/L banner, drift badges, premium trend, trade ideas panel, escalation level badges.
  - Pydantic schemas: IntradayPL, trade_proposals added to TelemetryResponse.
  - test_positions.py: setUp now calls clear_rec_state() to isolate hysteresis/escalation between tests.
  - Comprehensive User Manual created: `docs/User_Manual.md`.
  - 29 unit tests retained and passing.
* **[V5.0] Phases 9, 12 — GEX Integration & Trade History:**
  - Phase 9: ThetaData real-time GEX integration. BS-gamma computation from IV + OI.
  - GEX as 6th factor in `compute_smart_moat()` (×0.90 positive, ×1.15 negative).
  - GEX wall proximity in `evaluate_positions()` — put wall support, call wall resistance, gamma wall magnet.
  - GEX scoring in `analyze_trade_proposal()` — wall proximity bonus/penalty + regime bonus/penalty.
  - GEX cache reduced to 2 minutes for real-time wall updates.
  - Historical GEX in backtester via `fetch_historical_gex()` — ThetaData 8-year options history.
  - Trade History: Robinhood CSV parser, credit spread identification, P/L computation.
  - Backtester: Full-day regime replay with historical Alpaca bars + GEX context.
  - Frontend: GEX panel in dashboard sidebar. Trade History tab with upload, stats, backtest results.
  - Pydantic schemas: GexData, GexLevel added to TelemetryResponse.
  - System Manual updated with GEX and Trade History sections.
  - 29 unit tests retained and passing.
* **[V4.0] Phases 6-10:**
  - Phase 6: Time-aware exit strategies with 4 time tiers in Warning Zone.
  - Phase 7: VIX/VIX9D fetching from Yahoo Finance. Math-grounded expected move moat replaces static regime tables.
  - Phase 8a: Intraday window classification with entry quality scores.
  - Phase 8b: Regime transition prediction via sub-score rate-of-change (30-min delta).
  - Phase 10: Calendar event awareness (FOMC, CPI, NFP, OPEX) with auto-widened moats.
  - Frontend: VIX Expected Move panel, Regime Transition panel, Trading Window panel, Calendar Events alert.
  - System Manual rewritten with beginner-friendly explanations of all features.
  - Pydantic schemas: IntradayWindow, MarketEvents, RegimeTransition, ExpectedMove added.
  - 29 unit tests retained and passing.
* **[V3.5] Phase 4 - Smart Moat System:**
  - `compute_smart_moat()` adjusts base moat using range context, signal quality, time decay, and range exhaustion.
  - Range context: TIGHT / CONTAINED / NORMAL / EXPANDING based on day's SPX range.
  - Signal quality: DEAD / NOISE / WEAK / DIRECTIONAL based on ER + continuous score.
  - Time-decay survival credit: graduated moat reduction as expiry approaches.
  - Range exhaustion detection: identifies established ranges with lower breakout probability.
  - Recommendation engine refactored: time-aware deployment zones, situational alerts.
  - Position summary (iron condor view) with safe corridor, risk tilt, aggregate P/L.
  - Watch levels simplified to one ceiling + one floor with day-extreme context.
  - 29 unit tests retained and passing.
* **[V3.0] Phase 3 - Advanced Risk Protocols:**
  - Migrated position state to SQLite persistent database.
  - Server-side `evaluate_positions` engine with regime-aware tiered stop rules.
  - Time-Delayed Verification stops with `BREACH_VERIFICATION_MINUTES`.
  - Whipsaw Immunity: breach timer auto-clears on price recovery.
  - All thresholds centralized in `config.py`.
  - API keys moved to `.env`.
  - 29 unit tests covering all zones and edge cases.
* **[V2.0] Phase 2 - Smart Ledger:** Alpaca real-time API. Dynamic moat tracking and Gamma-Trap boundaries.
* **[V1.2]:** VWAP Elasticity "Rubber Band" override.
* **[V1.1]:** Multi-Factor Ensemble Model (CHOP, ER, RSI, EMA).