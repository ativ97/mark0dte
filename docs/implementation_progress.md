# Implementation Progress — Phases 5-8
# Read this file at the start of every new context to resume work.
# Last updated: 2026-05-29

## STATUS: 2026-05-29 batch 2 SHIPPED — P0-1 (EST quarantine), P0-3 (sizing wiring + banner + DB contracts), P0-5 (expired-ITM P&L, stale-VIX label), P0-6 (tracker resolve-on-expiry), P1-5 (ask-side pricing) + frontend (sizing banner, contracts input, ?? 999). 80 tests + harness green; frontend esbuild-clean (run `npm run dev` to runtime-verify). NEXT: P1-4 single-source verdict; P0-7 threshold vol-scaling (needs replay); regime badge + fill-input-on-close. See docs/MONDAY_PREP.md.

### 2026-05-29 batch 2 — P0/P1 sweep (files touched)
- **engine.py**: P0-5 expired-ITM `-(width-credit)`; P0-1 profit-cap gated to LIVE/SPXW (`_price_trustworthy`); P0-3 `_pos_risk` in output + `calculate_position_risk` defensive coercion; P1-5 `estimated_buyback_ask`.
- **data_fetcher.py**: P0-5 stale-VIX `source='stale_cache'`; P1-5 `spread_ask_close` in both lookups.
- **accuracy_tracker.py**: P0-6 `resolve_expired_positions()` (grades open signals at expiry; wired in main.py at hours_remaining<=0).
- **main.py**: P0-6 wiring; `EvaluatedPosition` schema adds mean_reverting/trend_continuation/reversal_score/contracts/position_risk/estimated_buyback_ask; `PositionCreate.contracts`.
- **database.py**: `contracts` column + idempotent `_ensure_schema()` migration (ALTER existing DB).
- **config.py**: ACCOUNT_SIZE / MAX_RISK_PER_TRADE ($2,000) / MAX_RISK_PER_DAY_PCT (guidance).
- **app.jsx**: sizing %-of-account banner (from position_risk), contracts entry input, `p.moat ?? 999` fix. (esbuild-clean; runtime unverified — `npm run dev`.)
- **Tests**: +3 (EST quarantine, resolve-expired, ask-side pricing) → **80 total**. Harness GR-0513/GR-0529 PASS.

## 2026-05-29 — Live-session sprint (audit → P0-2 → sizing)
- **Full-codebase audit** → `docs/IMPLEMENTATION_PLAN.md` (P0–P3, prioritized) + `docs/VALIDATION_PLAN.md` (T0/T1/T2 ladder; synthetic-replay + live hybrid).
- **Synthetic-replay harness** `backend/synthetic_replay.py` — drives `evaluate_positions` bar-by-bar with an injected bar-time clock; reproduced the 5/13 EJECT-hold bug.
- **P0-2 regime-conditional EJECT** in `engine.py` `evaluate_positions` (~line 2021): `mean_reverting`/`trend_continuation` gate; force-stick when escalation URGENT/CRITICAL and NOT mean-reverting; reversal-downgrade gated to positive-GEX. Validated: **GR-0513 PASS** (force before breach), **GR-0529 PASS** (hold the positive-GEX bounce), calm guard clean. Adds `mean_reverting`/`trend_continuation` to the position dict (add to main.py Pydantic schema if you want them in the API — pitfall #6).
- **P0-3 (partial) sizing guardrail**: `config.py` `ACCOUNT_SIZE`/`MAX_RISK_PER_TRADE` ($2,000 = 20%, Ativ), `engine.calculate_position_risk()` + 2 tests. Engine still contract-count-blind (P0-3a: wire `contracts` into positions for the UI banner).
- **Live session 2026-05-29** fully logged in `docs/trading_log_2026-05-29.md` (−$1,320 → +$1,255; signal grades; survivorship caveat; 11 findings L1–L11 folded into the plan).
- **Tests:** `test_engine.py` 50 pass (+2 sizing), `test_positions.py` 26 pass. (`test_main_imports` needs `pandas_ta`.)

## STATUS (prior): Phase 9 COMPLETE — Phase 8 or Phase 10 NEXT

## PHASE 5: ER-Gated Move Consumed + Portfolio Heat
- [x] **5A** Gate `move_consumed_factor` on ER in `engine.py compute_smart_moat()` (lines 1017-1049)
- [x] **5B** `calculate_portfolio_heat()` function in `engine.py` (lines 1100-1135)
- [x] **5C** Wired into `main.py`: Pydantic schema + telemetry endpoint + response
- [x] **5D** Tests: 3 ER-gate + 2 portfolio heat (27 total pass)
- [x] **5E** Portfolio Heat banner in `app.jsx` (lines 303-314, above position cards)
- [x] **5F** Handled automatically — `moat_explanation` string already shows ER-gate info

## PHASE 6: Rolling Surge Detector
- [x] **6A** `detect_surge()` in `engine.py` (lines 1138-1199)
- [x] **6B** `prev_close_spx` in `data_fetcher.py fetch_spx_day_range()` (all return paths)
- [x] **6C** Gap % computed via `compute_initial_balance()` from prev_close + day_open
- [x] **6D** Surge → reversal_score cap in `evaluate_positions()` (lines 1386-1394)
- [x] **6E** TREND_SURGE → move_consumed_blocked=True in `compute_smart_moat()` (lines 1029-1031)
- [x] **6F** Implemented in Phase 7 Fix #7 — STRONG BULLISH/BEARISH bias level
- [x] **6G** `compute_initial_balance()` in `engine.py` (lines 1202-1255)
- [x] **6H** `detect_gap_rejection()` in `engine.py` (lines 1258-1297)
- [x] **6I** auto_propose_positions surge penalty (lines 2843-2867)
- [x] **6J** Pydantic schemas: surge_data, ib_data, gap_rejection in TelemetryResponse
- [x] **6K** Tests: 3 surge + 2 gap rejection (32 total pass)
- [x] **6L** Surge Alert banner in app.jsx (lines 308-330)
- [x] **6M** Deferred — bias styling not critical
- [x] **6N** IB Range card in Evidence layer (lines 643-672)
- [x] **6O** Gap % badge next to SPX price (lines 283-287)
- [x] **6P** Fade multiplier progress bar in surge banner (lines 320-327)
- [x] **6Q** Deferred — surge context on cards handled by moat_explanation
- [x] **6R** Trade proposal surge warning via auto_propose penalty

## PHASE 7: ThetaData Live Quotes + Quick Fixes
- [x] **Fix #2** Suppress reversal_score when event_moat_multiplier > 1.0 in evaluate_positions
- [x] **Fix #3** IB breakout as 8th smart moat factor in compute_smart_moat (1×→×1.05, 2×→×1.10, 3×+→×1.15)
- [x] **Fix #4** Market story language: State A + ER≥0.40 says "could extend further" instead of "unlikely"
- [x] **Fix #5** recommended_moat shows smart moat value instead of stale regime string
- [x] **Fix #7** STRONG BULLISH/BEARISH bias level (ER≥0.40 + RSI extreme + momentum)
- [x] **7A** `fetch_live_option_quotes()` in data_fetcher.py (full SPY 0DTE bid/ask chain)
- [x] **7B** Cache layer (30s TTL, `_quote_cache`)
- [x] **7C** `get_spread_buyback_price()` + override in evaluate_positions
- [x] **7D** pricing_source field (LIVE/EST) per position + Position Pydantic schema
- [x] **7E** Fallback: graceful None when ThetaData unavailable, EST model used
- [x] **7F** Tests: 3 live quote tests (call spread, put spread, missing strike)
- [x] **7G** LIVE/EST badge on position cards in Dashboard + Insights tabs
- [ ] **7H** Confidence band display (deferred)
- [x] **7I** P/L styling: LIVE removes ~ prefix, EST keeps it

## PHASE 9: Premium Velocity + SPXW Direct Pricing + Post-Event Detection ✅
- [x] **9A** Premium velocity ring buffer in main.py (`_buyback_history` per position, maxlen=10)
- [x] **9B** Velocity computation: $/min, trend direction (FALLING/RISING/STABLE/NEW)
- [x] **9C** buyback_velocity + buyback_trend + buyback_samples in Position Pydantic schema
- [x] **9D** Frontend: velocity indicator (▲▼) on position cards, shows after 3 samples
- [x] **9E** SPXW direct pricing: `_fetch_quotes_for_root("SPXW")` tried first
- [x] **9F** SPY fallback: `_lookup_spread_spy_proxy()` with width_ratio scaling
- [x] **9G** Post-event: `event_time_et` added to `_check_market_events()` return
- [x] **9H** `detect_post_event_shift()` in engine.py (5 shift types, 5-30min window)
- [x] **9I** Post-event banner in app.jsx (color-coded by shift type)
- [x] **9J** Tests: 3 SPXW direct + 2 post-event + updated import smoke (40 total)
- [x] **9K** Live-priced trade proposals: `auto_propose_positions()` uses SPXW quotes for credit, EST fallback only when unavailable. `credit_source` field added. Frontend shows SPXW/EST badge + ~ prefix.
- [x] **9L** Thread-safe ThetaData client: `threading.Lock()` prevents concurrent auth race condition
- [x] **9M** Velocity tracker only records LIVE/SPXW prices (EST noise filtered out)
- [x] **9N** Profit-aware escalation cap: positions at ≥50% profit in warning zone get TAKE_PROFIT action + CLOSE_RECOMMENDED cap (not CRITICAL_EJECT). Take-profit recs now fire for warning-zone profitable positions. Insight card shows YELLOW light with "take profit" verdict.
- [x] **9O** UI: Removed "Add Position" button from narrative, all panels expanded by default, merged Key Evidence + Key Levels into horizontal 2-column layout with GEX gamma bars on key levels, credit source badge on proposals.
- [x] **9P** Tests: 2 profit-aware escalation regression tests (42 total)
- [x] **9Q** Signal Outcome Tracker v2: replaced accuracy_tracker.py internals. Dollar-valued signal grading (CORRECT/JUSTIFIED/PREMATURE/WRONG). Tracks worst/best moat and buyback between transitions. TAKE_PROFIT classified as EXIT signal. New log: `signal_log.jsonl` (old `accuracy_log.jsonl` archived). Frontend: Signal Scorecard with correctness %, dollar values, per-action breakdown.
- [x] **9R** main.py: `track_signal()` replaces `log_recommendation()`. Passes spx_price, buyback, hours_remaining for context snapshots.
- [x] **9S** Tests: 7 signal tracker tests (grading + transitions + TAKE_PROFIT classification). 49 total.

## PHASE 8: GEX Wall Pressure + Backtester Fix (DEFERRED)
- [ ] **8A** Time-near-wall metric in engine.py
- [ ] **8B** entry_time column in backtester.py CSV parsing
- [ ] **8C** Skip bars before entry_time
- [ ] **8D** Tests
- [ ] **8E** Wall pressure on GEX Evidence card in app.jsx
- [ ] **8F** Wall pressure on position cards

## KEY FILE LOCATIONS (for context reload)
- `engine.py compute_smart_moat()` — ~line 940-1079 (7-factor smart moat)
- `engine.py move_consumed_factor` — ~line 1018-1034
- `engine.py evaluate_positions()` — ~line 1082-1663
- `engine.py generate_market_insights()` — ~line 2700+ (narrative cards)
- `engine.py auto_propose_positions()` — search for def auto_propose
- `main.py telemetry endpoint` — GET /api/telemetry, ~line 400+
- `main.py TelemetryResponse` — ~line 264-310
- `data_fetcher.py fetch_spx_day_range()` — search for def fetch_spx_day_range
- `app.jsx` — single-file React, Insights tab starts ~line 200, Evidence ~line 406
- `data_fetcher.py _lookup_spread_direct()` — SPXW direct pricing, no conversion
- `data_fetcher.py _lookup_spread_spy_proxy()` — SPY proxy with width_ratio scaling
- `engine.py detect_post_event_shift()` — ~line 1340-1435
- `main.py _buyback_history` — ~line 27-30, premium velocity ring buffer
- `main.py velocity computation` — ~line 534-576 (after evaluate_positions)
- `test_engine.py` — 40 tests currently passing
- `.windsurfrules` — test count line ~28, pitfalls ~95+, version history ~108+

## COMPLETED ITEMS LOG

### Phase 5 (completed 2026-05-28)
- **5A**: `engine.py` lines 1017-1049 — ER-gated move_consumed_factor. Added `move_consumed_blocked` bool.
- **5B**: `engine.py` lines 1100-1135 — `calculate_portfolio_heat()` function. Levels: SAFE/IMBALANCED/DANGER.
- **5C**: `main.py` — Added `calculate_portfolio_heat` import, `SmartMoat.move_consumed_blocked` field, `TelemetryResponse.portfolio_heat` field, wired call after evaluate_positions.
- **5D**: `test_engine.py` — Added `TestERGatedMoveConsumed` (3 tests) + `TestPortfolioHeat` (2 tests). 27 total pass.
- **5E**: `app.jsx` lines 303-314 — Portfolio Heat banner (red DANGER / amber IMBALANCED), hidden when SAFE.
- **5F**: No extra frontend needed — `moat_explanation` string already includes ER-gate info.
- **Tests**: 27/27 pass.

### Phase 6 (completed 2026-05-28)
- **6A**: `engine.py` — `detect_surge()` function: rolling surge from ring buffer snapshots, 0.4% threshold, ER-classified as TREND_SURGE or VOLATILE_SURGE, fade_multiplier by time.
- **6B**: `data_fetcher.py` — `prev_close_spx` added to `fetch_spx_day_range()` via Yahoo `previousClose`.
- **6D**: `engine.py` `evaluate_positions()` — TREND_SURGE caps reversal_score via fade_multiplier.
- **6E**: `engine.py` `compute_smart_moat()` — TREND_SURGE forces move_consumed_blocked=True.
- **6G**: `engine.py` — `compute_initial_balance()` function: 30-min IB from SPY bars, gap_pct from prev_close.
- **6H**: `engine.py` — `detect_gap_rejection()` function: gap>0.5% + IB breakout = rejection signal.
- **6I**: `engine.py` `auto_propose_positions()` — surge_data param, -15pt penalty for fading TREND_SURGE direction.
- **6J**: `main.py` — surge_data, ib_data, gap_rejection in TelemetryResponse schema + return.
- **6K**: `test_engine.py` — 3 surge tests + 2 gap rejection tests. 32 total pass.
- **6L/6N/6O/6P**: `app.jsx` — Surge Alert banner, IB Evidence card, Gap % badge, fade multiplier bar, Gap Rejection banner.
- **Tests**: 32/32 pass.

### Phase 7 (completed 2026-05-28)
- **Fix #2**: `engine.py` `evaluate_positions()` — event_moat_multiplier param, penalizes reversal_score up to 20 pts.
- **Fix #3**: `engine.py` `compute_smart_moat()` — ib_data param, IB breakout as 8th multiplicative factor.
- **Fix #4**: `engine.py` `generate_market_insights()` — trending day language qualified by ER.
- **Fix #5**: `main.py` — recommended_moat shows smart moat value.
- **Fix #7**: `engine.py` `analyze_market_regime()` — STRONG BULLISH/BEARISH when ER≥0.40 + RSI extreme. Downstream checks use substring matching.
- **7A/7B**: `data_fetcher.py` — `fetch_live_option_quotes()` with 30s cache, `get_spread_buyback_price()` for SPX→SPY strike conversion and spread mid-price.
- **7C**: `engine.py` `evaluate_positions()` — live_quotes + spx_spy_ratio params, overrides estimated_buyback when LIVE available.
- **7D**: `engine.py` + `main.py` — pricing_source field in position output and Pydantic schema.
- **7F**: `test_engine.py` — 3 tests (TestLiveSpreadQuoteLookup). Import smoke test updated.
- **7G/7I**: `app.jsx` — LIVE badge (green) / EST badge (grey) on Dashboard + Insights position cards. LIVE P/L removes ~ prefix.
- **Bug fix**: `InsightPositionCard` Pydantic schema was missing `pricing_source` field — Pydantic silently dropped it.
- **Bug fix**: `get_spread_buyback_price()` was using $5 SPY width instead of converting both SPX legs independently. A $5 SPX spread maps to ~$1 SPY spread. Added `width_ratio` scaling (SPX_width / SPY_width ≈ 5). `SPREAD_WIDTH_SPX = 5.0` added to config.py.
- **Bug fix**: `d is not defined` crash in app.jsx position summary — replaced `d.positions` with `telemetry.positions`.
- **Tests**: 35/35 pass.
