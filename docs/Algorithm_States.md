# 0DTE Algorithmic Decision Support System

**System Architecture & State Rules - Version 3.0 (Advanced Risk Protocols)**

## 1. Core Philosophy

The objective of this algorithm is to act as a **Human-in-the-Loop Regime Classifier**. It ingests live market telemetry (Alpaca Real-Time SPY data) to determine the current operational environment (State) and outputs dynamic structural constraints (Moat Width, Stop-Loss Limits) to protect short premium positions. The system trades **SPX 0DTE options** using SPY as a data proxy.

Version 3.0 introduces **Persistent State Management**, **Server-Side Risk Evaluation**, **Regime-Aware Tiered Stops**, and **Time-Delayed Verification** to defeat whipsaw stop-outs.

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

## 8. System Modification Log

* **[V4.0] Phase 4 - Smart Moat System:**
  - `compute_smart_moat()` adjusts base moat using range context, signal quality, time decay, and range exhaustion.
  - Range context: TIGHT / CONTAINED / NORMAL / EXPANDING based on day's SPX range.
  - Signal quality: DEAD / NOISE / WEAK / DIRECTIONAL based on ER + continuous score.
  - Time-decay survival credit: graduated moat reduction as expiry approaches.
  - Range exhaustion detection: identifies established ranges with lower breakout probability.
  - Recommendation engine refactored: removed redundant indicator/day-range watches (surfaced in UI), time-aware deployment zones, situational alerts.
  - Position summary (iron condor view) with safe corridor, risk tilt, aggregate P/L.
  - P/L estimation per position using moat, time decay, and zone classification.
  - Watch levels simplified to one ceiling + one floor with day-extreme context.
  - Frontend: Smart Moat panel with tagged badges, position sort by strike, upper/lower bound labels.
  - 29 unit tests retained and passing.
* **[V3.0] Phase 3 - Advanced Risk Protocols:**
  - Migrated position state from browser `useState` to SQLite persistent database.
  - Server-side `evaluate_positions` engine with regime-aware tiered stop rules.
  - Time-Delayed Verification stops with configurable `BREACH_VERIFICATION_MINUTES`.
  - Whipsaw Immunity: breach timer auto-clears on price recovery.
  - All engine thresholds centralized in `config.py` and consumed by `engine.py`.
  - API keys moved to `.env` file (removed from source code).
  - VWAP column collision resolved (`VWAP_BAR` vs cumulative `VWAP`).
  - SPX proxy multiplier made configurable (`SPX_PROXY_MULTIPLIER`).
  - Input validation on position creation (type enum, positive strike/credit).
  - Deprecated `datetime.utcnow()` replaced with `datetime.now(timezone.utc)`.
  - Frontend polling reduced from 60s to 30s.
  - Unit tests added for position evaluator (15 test cases covering all zones and edge cases).
* **[V2.0] Phase 2 - Smart Ledger:** Migrated data ingestion to Alpaca real-time API. Deployed dynamic UI contract moat tracking and Gamma-Trap boundary rules.
* **[V1.2]:** Added VWAP Elasticity "Rubber Band" override.
* **[V1.1]:** Upgraded to Multi-Factor Ensemble Model (CHOP, ER, RSI, EMA).