# 0DTE Quant Engine — AI Agent Rules & Notes
# This file provides context and rules for AI coding agents (Claude, Cursor, Copilot, etc.)
# working on this project. It mirrors `.windsurfrules` and must be kept in sync.
# Last updated: 2026-05-29 (P0-2 regime-conditional EJECT + sizing guardrail + synthetic-replay harness)

---

## MANDATORY AGENT RULES

1. **READ THIS FILE FIRST**: At the start of every task, read this file in full for environment setup, conventions, known pitfalls, and architecture. Do NOT guess Python paths, SPX behavior, or function signatures — check here first.

2. **READ `docs/implementation_progress.md` ON EVERY CONTEXT SWITCH**: This file tracks all phase status, pending tasks, completed items, key file locations, and line numbers. Read it BEFORE starting any work to know where you left off. Update it AFTER completing any feature or fix — bump the STATUS line, check off items, add to the COMPLETED ITEMS LOG, and update KEY FILE LOCATIONS if line numbers shifted.

3. **UPDATE THIS FILE AND `.windsurfrules`**: Whenever you discover a new gotcha, implement a new feature, fix a bug, or learn something the hard way — immediately update BOTH this file and `.windsurfrules` before ending your response. Add it to the appropriate section (KNOWN PITFALLS, ALGORITHM VERSION HISTORY, etc.). Update the "Last updated" date above.
3b. **KEEP `.windsurfrules` IN SYNC**: `.windsurfrules` at project root is a mirror of this file used by Windsurf/Cascade. Whenever you edit `CLAUDE.md`, apply the same change to `.windsurfrules` and vice versa. Both files must always contain identical rules, pitfalls, and architecture info.

4. **KEEP DOCS IN SYNC**: When implementing a new feature or changing algo behavior:
   - Update `docs/Algorithm_States.md` — add changelog entry, update version number, update relevant sections.
   - Update `docs/User_Manual.md` — if the change affects what the user sees on the dashboard.
   - Update `readme.md` — if the change affects setup, environment, or test count.
   - Update test count in this file AND `.windsurfrules` if tests are added/removed.

5. **NEVER SILENTLY SWALLOW ERRORS**: If you encounter a new API quirk, data format issue, or environment problem, log it in KNOWN PITFALLS below with the fix.

6. **VERIFY BEFORE CODING**: Before editing `engine.py`, `data_fetcher.py`, or `main.py`, re-read the KEY DATA FLOW and relevant function signatures below. Do not assume parameter lists from memory.

7. **RUN TESTS AFTER EVERY CHANGE**: After editing any backend file, run the test command below and confirm all tests pass before considering the change done. The import smoke tests catch syntax errors and missing attributes. Never ship code that hasn't been tested.

---

## ENVIRONMENT

- **Python**: `/Users/ativ.aggarwal/miniconda3/envs/mark/bin/python` (Python 3.13)
- **Conda env**: `mark` (NOT `0dte_env` — the readme is outdated)
- **NEVER use** `/usr/bin/python3` — that is system Python 3.9, missing all dependencies
- **Run tests**: `/Users/ativ.aggarwal/miniconda3/envs/mark/bin/python -m pytest test_engine.py test_positions.py -v --tb=short` (from `backend/`). Also run `python synthetic_replay.py` — the P0-2 regime-gate validation; GR-0513 and GR-0529 must both PASS.
- **Start backend**: `/Users/ativ.aggarwal/miniconda3/envs/mark/bin/python -m uvicorn main:app --reload` (from `backend/`)
- **Start frontend**: `npm run dev` (from `frontend/`)
- **Test count**: 80 tests as of 2026-05-29 — **54 in `test_engine.py`** (49 + 2 sizing + EST-quarantine + resolve-expired + ask-side pricing) + **26 in `test_positions.py`**. Run BOTH files. Plus `synthetic_replay.py` (P0-2 regime-gate validation: GR-0513 + GR-0529 must PASS). All must pass before any PR.

---

## PROJECT STRUCTURE

```
mark/
├── backend/
│   ├── main.py            # FastAPI endpoints, telemetry pipeline orchestrator
│   ├── engine.py           # Core algo: regime, smart moat, positions, recs (~3500 lines)
│   ├── data_fetcher.py     # Alpaca, Yahoo, ThetaData, VIX, GEX fetchers
│   ├── config.py           # All thresholds and constants
│   ├── database.py         # SQLAlchemy models (PositionDB, ClosedPositionDB)
│   ├── accuracy_tracker.py # Signal Outcome Tracker v2 (was accuracy tracker v1)
│   ├── backtester.py       # Historical trade backtester
│   ├── synthetic_replay.py # P0-2 validation harness (drives evaluate_positions bar-by-bar, injected clock)
│   ├── test_engine.py      # Unit tests (51 tests)
│   ├── test_positions.py   # evaluate_positions unit tests (26 tests)
│   └── requirements.txt
├── frontend/
│   └── src/app.jsx         # Single-file React dashboard (Tailwind v4, ~2300 lines)
├── docs/
│   ├── Algorithm_States.md # Algo spec & version log (V5.5+)
│   ├── User_Manual.md      # Dashboard user guide
│   └── trading_log_*.md    # Daily trading session logs
├── tradehistory/           # Robinhood CSV exports
├── .windsurfrules          # Windsurf-specific agent rules (mirror of this file)
├── CLAUDE.md               # This file — for Claude and other agents
└── readme.md               # Setup guide (NEEDS UPDATE — still says Python 3.9)
```

---

## KEY DATA FLOW (Telemetry Endpoint)

The main telemetry endpoint (`GET /api/telemetry`) is the core pipeline. Understanding this flow is critical before making any changes:

```
GET /api/telemetry →
  1. fetch_alpaca_market_data("SPY") → DataFrame + live_price
  2. Calculate TA indicators (EMA, RSI, CHOP, ER, VWAP)
  3. analyze_market_regime(df) → regime_data
  4. fetch_spx_live_price() → spx_price (Yahoo ^GSPC, SPY fallback)
  5. fetch_spx_day_range() → day_high, day_low, day_open (Yahoo ^GSPC)
  6. fetch_vix_data() → VIX + VIX9D
  7. compute_expected_move() → 1σ, 2σ, conditional σ, recommended moat
  8. fetch_gex_data() → GEX regime, walls
  9. compute_smart_moat() → 7-factor adjusted moat
  10. evaluate_positions() → per-position moat, status, exit strategy, reversal score
  11. generate_recommendations() → prioritized action items
```

---

## SPX / SPY CRITICAL GOTCHAS

These are the most dangerous pitfalls in this codebase. Violating any of these will cause incorrect risk calculations:

- **SPX is not directly available from Alpaca.** We use SPY as a data proxy for all TA indicators.
- **SPX live price**: Fetched from Yahoo Finance `^GSPC` via `fetch_spx_live_price()`. Falls back to `SPY × SPX_PROXY_MULTIPLIER` (default 10.0).
- **SPX day range**: Fetched from Yahoo `^GSPC` via `fetch_spx_day_range()`. Falls back to SPY × ratio.
- **SPX/SPY ratio DRIFTS over time** due to dividends and expense ratio. At SPX ~7500, a 0.1% drift = ~7.5 pts — this is significant when GAMMA_TRAP_THRESHOLD is only 10 pts.
- **NEVER assume SPX = SPY × 10 exactly.** Always use the dynamically computed `spx_spy_ratio` from main.py.
- **SPX day open**: Added in Phase 16 from Yahoo `fast_info.get("open")`. Used for move-consumed calculations.

---

## CODING CONVENTIONS

- **Timestamps**: Always Central Time (CT / UTC-5 or UTC-6) for user-facing display. Backend uses UTC internally.
- **Estimated values**: Always prefix with `~` or `Est.` in the UI. The buyback model is a rough IV proxy, NOT Black-Scholes.
- **No emojis** in code unless user explicitly requests.
- **No dollar figures without caveats** if confidence is low (estimated_pl, estimated_buyback).
- **Comments**: Do not add or delete existing comments unless asked. Follow existing style.
- **Imports**: Always at top of file. Never import mid-file.
- **Config constants**: All thresholds live in `config.py`. Never hardcode magic numbers in engine.py.

---

## KNOWN PITFALLS & LESSONS LEARNED

These are hard-won lessons from live trading and development. Read them all:

1. **Yahoo `fast_info` field names vary**: Sometimes `dayHigh` vs `day_high`, `lastPrice` vs `last_price`. Always check both with `or`.

2. **SQLite strips timezone info**: When reading `breach_start_time` from DB, always call `.replace(tzinfo=timezone.utc)` if tzinfo is None.

3. **Alpaca bars are SPY, not SPX**: All TA indicators (RSI, CHOP, ER, VWAP) are computed on SPY prices. Only the moat/strike math uses SPX.

4. **Premium estimation is NOT accurate**: The buyback fraction model (`estimate_credit()`) overestimates by ~$0.40 for far-OTM strikes. Now replaced by live SPXW pricing in both positions AND proposals. EST fallback only when ThetaData unavailable.

5. **GEX data from ThetaData can be stale**: Cache TTL is 120s. If ThetaData is down, `gex_data` will be None — all GEX-dependent code must handle None gracefully.

6. **Pydantic schemas must match engine return dicts**: If you add a field to `compute_smart_moat()` output, you MUST also add it to the `SmartMoat` class in main.py (with a default value for backward compat).

7. **`evaluate_positions` takes a SQLAlchemy session**: It commits breach_start_time changes directly. Mock it in tests with `MagicMock()`.

8. **Recommendation persistence state is global**: `_rec_state`, `_escalation_state`, etc. are module-level dicts. Call `clear_rec_state()` between test cases to avoid cross-contamination.

9. **Frontend is a single file**: `app.jsx` is the entire React app (~2300+ lines). No component decomposition yet.

10. **Range position can be 0-100**: 0% = at day low, 100% = at day high, 50% = midpoint. Used extensively in moat/risk calculations.

11. **Config imports are explicit**: engine.py uses `from config import ...` with named imports. If you reference a new config constant, you MUST add it to the import list. `SAFE_ZONE_THRESHOLD` (25) = `WARNING_ZONE_THRESHOLD` (25) — same value, different semantic intent.

12. **`.get(key, default)` does NOT protect against explicit None**: If a dict has `{"trigger_spx": None}`, `.get("trigger_spx", fallback)` returns `None`, NOT the fallback. Always use `d.get(key) or fallback` when the value can be explicitly None.

13. **SPX spread ≠ SPY spread in width**: A $5 SPX spread maps to ~$0.50 SPY (≈$1 after rounding to nearest strike). The SPY spread mid-price must be multiplied by `width_ratio` (SPX_width / SPY_width ≈ 5) to get the SPX-equivalent buyback price. `SPREAD_WIDTH_SPX = 5.0` is in config.py. Always assume $5 SPX width unless the user says otherwise.

14. **SPXW vs SPY quote source**: `fetch_live_option_quotes()` tries SPXW (direct SPX options) first, falls back to SPY. SPXW quotes use SPX strikes directly (no conversion, width_ratio=1.0). SPY quotes need SPX→SPY strike conversion + width_ratio scaling. The `quote_source` field ("SPXW" or "SPY") flows through to `get_spread_buyback_price()` and `pricing_source` on position cards.

15. **Post-event detection requires ring buffer data**: `detect_post_event_shift()` looks for pre-event snapshots in `_telemetry_snapshots`. If the system wasn't running before the event, it returns UNKNOWN shift type. Event times are hard-coded (FOMC=14:00 ET, CPI/NFP=8:30 ET).

16. **Trade proposal credits are now live-priced**: `auto_propose_positions()` receives `live_quotes` + `quote_source` and calls `get_spread_buyback_price()` for each candidate. Only falls back to `estimate_credit()` heuristic when live quotes are unavailable. Proposals with credit < $0.15 are filtered. The `credit_source` field ("SPXW"/"SPY"/"EST") is included in each proposal.

17. **ThetaData client needs threading lock**: `_get_theta_client()` uses `threading.Lock()` with double-check pattern. Without it, concurrent FastAPI requests create multiple auth sessions and ThetaData rejects all but one.

18. **Escalation ladder ignores profit state**: The `_get_escalation_level()` ratchets purely on time-in-danger, reaching CRITICAL_EJECT after ~12 min even when position is 67% profitable. Fixed: profit-aware cap in `evaluate_positions()` — caps escalation at CLOSE_RECOMMENDED when profit_pct ≥ 50%, reframes exit as TAKE_PROFIT. Also: take-profit recommendations now fire for warning-zone profitable positions (previously blocked by moat filter).

19. **Old accuracy tracker measured wrong thing**: V1 (`accuracy_log.jsonl`) counted "exit signal on losing trade = correct" — meaningless when all trades win. V2 Signal Outcome Tracker (`signal_log.jsonl`) measures dollar-valued correctness: exit_savings = final_cost - buyback_at_signal. Grades: CORRECT (saved money), JUSTIFIED (cost more but risk was real — moat hit gamma trap), PREMATURE (position recovered, signal was early), WRONG (hold that lost money). TAKE_PROFIT is now classified as EXIT signal.

20. **EJECT must be regime-conditional (P0-2, 2026-05-29)**: The final-hour / final-30-min warning-zone exit branches emitted `HOLD_FOR_EXPIRY`/`HOLD_WITH_TRIGGER` even while the escalation ladder had reached URGENT/CRITICAL — an action/escalation desync that let a with-trend short ride to the strike (the 5/13 −$1,696 setup; reproduced in `synthetic_replay.py`). Fix in `evaluate_positions()` (~line 2021): compute `mean_reverting = (gex_regime == "POSITIVE") and not surge` vs `trend_continuation`. (a) Outside a mean-reverting regime, force the action to the escalation level when it is URGENT/CRITICAL and currently a `HOLD_*` (sets `p0_2_forced`). (b) The reversal-downgrade is now gated to `mean_reverting` only — never softens a close in a trend-continuation regime. Validated by `synthetic_replay.py`: **GR-0513** (force a non-downgradable exit before breach) + **GR-0529** (hold the positive-GEX bounce, +$1,255 live on 5/29). Adds `mean_reverting`/`trend_continuation` to the position dict — add them to the `EvaluatedPosition` Pydantic model in main.py to surface in the API (else dropped — pitfall #6).

21. **Sizing is account-blind (P0-3, partial)**: The engine does not track contract count or account-level $-risk (it reasons only on per-position moat). `config.MAX_RISK_PER_TRADE` ($2,000 = 20% of `ACCOUNT_SIZE` $10k) + `engine.calculate_position_risk(contracts, width, credit)` exist and are unit-tested, but are NOT wired into `evaluate_positions` yet (positions carry no `contracts`). P0-3a: add a `contracts` column (database.py) + entry field + surface the sizing % banner in app.jsx. Today's 20-lot was 85% of account — the #1 live-session risk.

---

## ALGORITHM VERSION HISTORY (Key milestones)

- **V3.2**: Regime classification, position evaluation, range proximity risk
- **V4.0**: VIX expected move moats, intraday windows, regime transition, calendar events
- **V5.0**: GEX deep integration (6th smart moat factor), trade analyzer, backtester
- **V5.5**: Moat hysteresis, graduated exit escalation, premium history, breakeven detection
- **Phase 16**: Conditional expected move (C1), reversal-aware exits (C2), time-adjusted take profit (C3), move-consumed smart moat (C4), momentum label fix (#37)
- **Phase 2 UI**: Insights tab with traffic lights, market story, position cards, heat scores, key levels. Two-tab layout (Insights + Dashboard).
- **Phase 5**: ER-gated move_consumed (violent flush blocks moat shrink), portfolio heat banner (concentration risk).
- **Phase 6**: Rolling surge detector (TREND_SURGE/VOLATILE_SURGE), IB computation, gap rejection, fade multiplier, reversal_score cap, auto_propose surge penalty. Frontend: surge banner, gap rejection banner, IB Evidence card, gap badge.
- **Phase 7**: ThetaData live bid/ask quotes (30s cache), live spread mid-price replaces estimated_buyback, pricing_source field (LIVE/EST) per position, LIVE/EST badge in frontend. Quick fixes: #2 event reversal suppression, #3 IB breakout as 8th smart moat factor, #4 market story trending day language, #5 smart moat replaces stale recommended_moat string, #7 STRONG BULLISH/BEARISH bias level.
- **Phase 9**: Premium velocity tracker ($/min trend per position, ring buffer), SPXW direct pricing (tries ThetaData SPXW root before SPY proxy, eliminates conversion error), post-event regime shift detection (EVENT_BREAKOUT/SPIKE/REVERSAL/ABSORBED/DIGESTING in 5-30min window), live-priced trade proposals (replaces heuristic estimate_credit), profit-aware escalation cap (caps at CLOSE_RECOMMENDED when ≥50% profit, TAKE_PROFIT action), Signal Outcome Tracker v2 (replaces accuracy tracker — dollar-valued signal grading, per-action breakdown, worst-moat tracking). Frontend: velocity indicator ▲▼, SPXW badge, post-event banner, credit source badge on proposals, merged Evidence & Key Levels horizontal layout, Signal Scorecard widget.
- **P0-2 + sizing (2026-05-29, current)**: Full-codebase audit → docs/IMPLEMENTATION_PLAN.md (P0–P3 + L1–L11 live findings) + docs/VALIDATION_PLAN.md (T0/T1/T2 ladder) + docs/MONDAY_PREP.md. Synthetic-replay harness `synthetic_replay.py` reproduced the 5/13 EJECT-hold bug. **P0-2 regime-conditional EJECT** in `evaluate_positions`: forces a non-downgradable exit on a with-trend short in a trend-continuation (non-positive-GEX/surge) regime, holds in a positive-GEX mean-reverting regime — validated GR-0513 (5/13 loss) + GR-0529 (5/29 +$1,255 bounce). **Sizing guardrail (partial)**: `config.MAX_RISK_PER_TRADE`=$2,000 + `engine.calculate_position_risk()` (not yet wired — engine is contract-count-blind, P0-3a). Full live-session log: docs/trading_log_2026-05-29.md.

---

## SMART MOAT: 7 MULTIPLICATIVE FACTORS

```
combined = range × signal × time × exhaustion × event × gex × move_consumed × ib_breakout
```

1. **Range**: TIGHT (×0.70) → NORMAL (×1.0) → EXPANDING (×1.15)
2. **Signal quality**: DEAD (×0.80) → NOISE (×0.90) → WEAK (×1.0) → DIRECTIONAL (×1.10)
3. **Time decay**: 1h→×0.55, 2h→×0.65, 3h→×0.75, 4.5h→×0.85, >4.5h→×1.0
4. **Range exhaustion**: mid_zone AND tested_both AND range>30 → ×0.90
5. **Calendar events**: FOMC ×1.40, CPI/NFP ×1.30, Quarterly OPEX ×1.50
6. **GEX regime**: POSITIVE ×0.85-0.95, NEGATIVE ×1.10-1.25
7. **Move consumed** (Phase 16): >0.3σ consumed → ×0.80-0.65
8. **IB breakout** (Phase 7): 1× IB → ×1.05, 2× → ×1.10, 3×+ → ×1.15

---

## KEY THRESHOLDS (from config.py)

- `WARNING_ZONE_THRESHOLD = 25` — moat ≤ 25 pts = warning zone
- `GAMMA_TRAP_THRESHOLD = 10` — moat ≤ 10 pts = gamma trap (immediate danger)
- `REC_COOLDOWN_MINUTES = 10` — recommendation cooldown between transitions
- `SPREAD_WIDTH_SPX = 5.0` — standard $5 SPX credit spread width
- `SPX_PROXY_MULTIPLIER = 10.0` — fallback SPX/SPY ratio
- `MIN_SIGNALS_FOR_DISPLAY = 10` — signal scorecard hidden until 10+ resolved signals

---

## ESCALATION LEVELS

Positions escalate through danger levels based on time-in-danger-zone:

```
CAUTION → WARNING → CLOSE_RECOMMENDED → URGENT_CLOSE → CRITICAL_EJECT
```

- Profit-aware cap: if profit_pct ≥ 50% and moat in warning zone (not gamma trap), escalation is capped at CLOSE_RECOMMENDED and action is reframed as TAKE_PROFIT.

---

## SIGNAL OUTCOME TRACKER (accuracy_tracker.py)

The system tracks every signal with full market context and grades it on resolution:

- **EXIT signals** (CLOSE_NOW, CLOSE_SOON, URGENT_CLOSE, CRITICAL_EJECT, TAKE_PROFIT):
  - Graded by `exit_savings = final_cost - buyback_at_signal`
  - CORRECT (saved money), JUSTIFIED (cost more but risk was real), PREMATURE (position recovered), NEUTRAL (±$0.05)

- **HOLD signals** (HOLD, HOLD_WITH_TRIGGER, HOLD_FOR_EXPIRY, LET_EXPIRE):
  - CORRECT (trade profited), WRONG (trade lost money)

- **Between signals**: tracks worst_moat_after, best_moat_after, worst_buyback_after, best_buyback_after
- **Log file**: `signal_log.jsonl` (one finalized signal per line)
- **API functions**: `track_signal()`, `resolve_position()`, `clear_position_state()`, `get_accuracy_stats()`, `get_signal_log()`

---

## FRONTEND ARCHITECTURE

- Single-file React app (`app.jsx`, Tailwind v4)
- **3-layer layout**: Narrative (story + positions) → Evidence (curated indicators) → Raw Dashboard (full data)
- **Sticky header**: SPX price, regime, bias, smart moat, GEX, time remaining
- **Key widgets**: Signal Scorecard, Position Summary, Portfolio Heat, Surge Alert, Post-Event Banner, Gap Rejection Banner
- **Telemetry polling**: Fetches `/api/telemetry` every 30 seconds

---

## WHAT'S NEXT (backlog)

- RSI Reversal Warning Badge (#35): "Overbought — reversal likely" on RSI card + story
- Explain Mode toggle (inline tooltips on technical terms)
- Premium History / Velocity (#28): sparkline or last-5-values
- "What if" scenarios: premium estimation at hypothetical SPX prices
- EOD review generator: "Today you learned..."
- GEX Wall Pressure (Phase 8 — DEFERRED): time-near-wall metric, wall pressure on position cards
- Shadow Trader (DEFERRED): simulated position-taking to compare algo vs user performance
- See `docs/trading_log_2026-05-26.md` for full phased plan
