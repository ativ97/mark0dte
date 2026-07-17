# Implementation Progress
# Read this file at the start of every new context to resume work.
# Last updated: 2026-06-03 (validation #2 + edge analysis, THEN build: 3 features — tail-day preview, contract-weighted P&L, ΔGEX velocity — + 5 reporting/display fixes + proper gamma-flip; +15 tests → 127. See method_analysis_2026-06-03.md.)

## STATUS: 2026-06-03 (BUILD) — 3 priority features + 5 bug fixes SHIPPED (+15 tests → 127; engine suite + synthetic_replay GREEN in sandbox). Frontend esbuild-unverified → `npm run dev`; full stack (main import, uvicorn, npm) to confirm in the `mark` env.
- **Sizing tail-day preview** (#1 leak): `engine.compute_tail_day_preview()` → book max-loss $ + % of account + "= N good days" + worst leg + over-warn/over-cap; `config.AVG_WIN_DAY_REFERENCE`=1300 (informational/tunable); `main` free-dict `tail_day_preview` + `TelemetryResponse` field; app.jsx banner under the heat banner. +4 tests.
- **Contract-weighted P&L** (reporting bug): `intraday_pl` summed PER-SHARE (contract-blind) → 6/3 showed $0.95 vs real +$1,550. Added `database.ClosedPositionDB.contracts` + idempotent migration; `close_position` stores `pos.contracts`; `main` P&L now `per_share × contracts × 100`. Pre-migration closed rows default contracts=1 (historical $ understated; forward-correct).
- **ΔGEX velocity + distance-to-zero** (GEX-flip read): `engine.compute_gex_velocity(history,…)` → least-squares net-GEX slope (M/min), trend, toward-flip + projected min-to-flip, spot-to-flip; `main._gex_history` deque(30) + free-dict `gex_velocity`; app.jsx gauge in the GEX panel. +4 tests.
- **Proper gamma flip**: replaced cumulative-by-strike `_compute_zero_gamma` (sign-inconsistent — 6/3 bug) with `data_fetcher._compute_gamma_flip()` (net GEX recomputed vs spot) + invariant guard (spot>flip ⟺ net_gex>0, else suppress). +3 tests.
- **Display fixes**: neg-GEX "wall protecting you" → "unreliable / no firm magnet support"; "all positions safe" + GREEN market light gated on open HIGH CLOSE recs; `regime_transition` "improving/degrading" reworded position-neutral.
- **Analysis**: `docs/method_analysis_2026-06-03.md` (what's worked + over/underfitting discipline — freeze the core, measure out-of-sample, separate edge from size, prune don't add). **NEXT:** confirm full stack in `mark` env; watch ΔGEX live before wiring to the core gate; accumulate ~30–50 fixed-size data-era trades for expectancy + the first tail day.

## STATUS: 2026-06-03 — VALIDATION SESSION #2 COMPLETE (live validation + edge analysis). Full log: docs/trading_log_2026-06-03.md.
- **Live (Robinhood): +$1,550 realized**, 5 trade-rounds, flat by midday; $2k cap never threatened. Range-bound / mean-reverting day with deeply NEGATIVE & DEEPENING GEX (−29M→−98M); regime cycled A/B/C.
- **★ H7 P0-2 FORCE-PATH FIRED LIVE, FIRST TIME EVER** (AM trend-through: mr=FALSE/tc=TRUE, trend_dominant 90, 7565 breached → non-downgradable CRITICAL_EJECT). The 5/13 setup appeared and the engine flagged it correctly. **STILL UNPROVEN BY OUTCOME** — user overrode ~38 min then exited green on a bounce; tail didn't materialize, so the path is proven to *fire*, not yet to *save*.
- **Validated where exercised:** H1 (single-source), H2 (cry-wolf gate — standout), H4 (hysteresis), H5 (RED-while-profit / RSI-basis). NOT exercised: H3, H6 (no auto-proposals fired). **H8 flip vs GEX-sign = FAIL → do NOT wire flip→regime** (calc broken: null + sign-inconsistent).
- **★ EDGE-VS-LUCK (trade history 5/11–6/2 via `edge_analysis.py`):** edge is REAL and coincides with the 5/20 data-driven switch — **discretionary era −$725 / 57% win / both blow-ups, vs data-driven era +$12,093 / 9-of-9 / no down day.** BUT the data era has had ZERO tail tests and lot size TRIPLED (10→30) over the streak → the inevitable tail day is now −$4k to −$13.5k (3–10 green days). **SIZE is the #1 lever for this account, not signal.**
- **5 display/reporting bugs found** (detailed in trading-log EOD): contract-blind `closed_pl`/`intraday_pl`; "all positions safe" headline vs open HIGH CLOSE recs; trend-follower-centric `regime_transition` wording; broken `zero_gamma_flip`; neg-GEX "wall protecting you" false comfort.
- **NEXT (re-prioritized post-validation):** (1) ★ **sizing prominence** — book "tail-day preview" ($ + % of account + "= N avg green days" + soft alert when today's lot > recent median); (2) fix the 5 display/reporting bugs (contract-weighted P&L FIRST — it misreports the scoreboard); (3) fix `zero_gamma_flip` (enforce spot>flip ⟺ net_gex>0), then re-evaluate wiring it; (4) confirm exit-grade #24 JUSTIFIED logic (over_limit + tc) so mean-revert-day exits aren't mis-scored; (5) **ΔGEX velocity + distance-to-zero gauge** (the GEX-flip predictor); (6) out-of-sample: log ~30-50 data-era trades at FIXED 10 lots → expectancy + capture first data-era tail day; (7) harden data layer (fetch timeouts, ET-correct GEX expiry, frontend stale-guard); (8) (gated, after #3 + data) core-gate rewire to flip/trend_dominant. **When these fixes ship, mirror the bug→pitfall notes into CLAUDE.md + .windsurfrules.**

## STATUS: 2026-06-02 — wasted-signals build #1–#6 + signal-wiring SHIPPED (+18 tests → 112): magnet touch%, narrative single-source, direction/size-aware exits, hysteresis, range/RR/profit display, zero-gamma flip, and RSI-50/FADE/gap-rejection/premium-trend wired into proposals & exit nudges. **109 pass + synthetic_replay GR-PASS confirmed in the `mark` env; live payload verified (rsi_basis, zero_gamma_spx, SPX range%).** NEXT: validate the new behavior live (tomorrow) + harden the data layer. Prior 2026-06-01 below.

### 2026-06-02 — live session (chat-driven, decision-GUIDE reframe) + wasted-signals build increment #1
- **Live session:** flat → **+$1,125** on Robinhood (backtester books +$1,162.8); a positive-GEX grind-up that died into lunch chop — **P0-2 force-path STILL not exercised**. Full structured capture + EOD in `docs/trading_log_2026-06-02.md`. The 20-lot call entry into the rally (74% book DANGER) was bailed by +GEX mean-reversion — survivorship, not validation. Reframe locked: the app is a decision **GUIDE** (trades on Robinhood) → sizing stays informational, never blocks.
- **Build increment #1** (`engine.py` + `main.py` + `test_engine.py`, +4 tests → **98**):
  - `compute_magnet_forces` no longer overclaims: added `day_high`/`day_low` params; a predicted level **already inside today's range** (`already_touched`) or **hugging spot** (`near_spot`, `< max(8, 0.12σ)`) suppresses `touch_prob`→None and reframes the headline ("already tagged … not a fresh target") instead of the vacuous "~95% touch". New free-dict keys `touch_basis`/`already_touched` (native bool). Backward-compatible (no day range → prior behavior). Wired `day_high_spx`/`day_low_spx` into the main.py call (~L726).
  - Fixed the inverted CAUTION moat wording (was "−2.2 pts below recommended minimum" when moat ≥ min) — sign-guarded; preserves the "below recommended" string when truly below (keeps the existing test contract).
  - Verified via direct calls + `TestMagnetTouchProb` (4). Sandbox `python -m unittest test_engine test_positions` → 97 logic tests pass; only the `main`-import smoke test errors there (no fastapi/pandas_ta) — run the full **98** in the `mark` env.
- **NEXT increments (ranked from the session):** (2) **narrative single-source-of-truth** (card ↔ recs ↔ exit_strategy → one verdict); (3) **direction/size-aware exit conviction** (don't CLOSE when price trends away from the strike; stop the stale day-low rec; cap the reversal-downgrade by book size); (4) **hysteresis layer** (escalation / regime_transition / trend_dominant); (5) **display cluster** (RSI feed label+staleness, range_position on SPX not SPY, RED-card-while-+profit, stale "wall protecting you", STRONG_ENTRY on thin credit); (6) **zero-gamma flip level** (top InsiderFinance gap).

### 2026-06-02 (cont.) — wasted-signals build #2–#6 SHIPPED (+11 tests → 109; engine-verified)
- **#2 narrative single-source-of-truth** (`engine.generate_market_insights`): a position with an open HIGH CLOSE rec can no longer render a GREEN "hold" card — reconciled to YELLOW "open close alert"; cards carry `close_alerts`/`close_alert_msg`. (`recommendations` already passed in at main.py.) +2 tests.
- **#3 direction/size-aware exit conviction** (`engine.generate_recommendations` + reversal-downgrade in `evaluate_positions`): the near-miss "day high/low came within X" and "less than half the recommended moat" CLOSE recs now require GENUINE danger (warning-zone moat OR `at_risk_side`); price trending AWAY is a WATCH, not a HIGH CLOSE (kills the 6/2 winning-put cry-wolf + the stale day-low rec). The reversal-downgrade is size-capped — an over-warn leg (6/2 10-lot calls = 30%) can't be soothed eject→hold. +2 tests.
- **#4 hysteresis**: `trend_dominant` sticky (ON ≥55 / OFF <45) via `prev_trend_dominant` (threaded through main.py `_magnet_trend_prev`); `_compute_regime_transition` widened deadband — weak ±0.2–0.5 reads collapse to "stable, leaning" instead of flipping SOFTENING/FIRMING. +3 tests.
- **#5 display cluster**: `range_position` computed on SPX not SPY (the 6/2 100%-vs-88%); `analyze_trade_proposal` STRONG_ENTRY gated by an 8% return-on-risk floor (the $0.18 spread that scored 86 is now ACCEPTABLE); RED-card-while-profit reframed to "close to lock ~X% gain"; `rsi_basis` label field + frontend RSI caption (5-min SPY/Alpaca ≠ Robinhood). +2 tests.
- **#6 zero-gamma flip level** (delegated): `data_fetcher._compute_zero_gamma` (interpolated cumulative signed-GEX zero crossing) → `gex_data.zero_gamma_spx/spy` (native floats) + `GexData` schema fields + surfaced as a "Zero-Gamma Flip" Key Level in main.py. +2 tests.
- **Signal wiring (same day, +3 → 112 tests; `TestProposalSignalWiring`)**: the previously display-only signals are now decision inputs — RSI-50 mean-reversion level is a buffer/hazard factor in `analyze_trade_proposal`; `auto_propose_positions` de-rates fade proposals when FADE is OFF (strong trend) and penalizes the side a confirmed `gap_rejection` presses; a RISING buyback adds an early exit-tell to at-risk/caution legs in `evaluate_positions`. RSI-50 is now computed early in main.py to feed `auto_propose`. **Core exit-force gate (P0-2) deliberately NOT rewired to trend_dominant/flip — deferred to live validation** (the 6/2 live data showed the flip level and net-GEX sign disagreeing on regime side).
- **Verification**: every changed engine fn exercised directly + **109 unit tests green in the sandbox** (only the `main`-import smoke test errors there — no fastapi/pandas_ta). **Run the full 109 + `synthetic_replay` + `uvicorn` in the `mark` env** to confirm live serialization. app.jsx (RSI caption) is esbuild-unverified → `npm run dev`. **NEXT:** the remaining strategic priorities — prove P0-2 on a real trend day; revive the expectancy scorecard (~50 graded trades); intraday ΔGEX + max-pain (further IF gaps).

## STATUS: 2026-06-01 — LIVE CHECKPOINT + 8 post-session fixes SHIPPED.
First live run of the 5/29 batch (~+$1,500 realized; full session in docs/trading_log_2026-06-01.md). **H1 (P0-2 fields), H2 (sizing banner), H4 (tracker resolve) validated live. P0-2 FORCE-PATH NOT EXERCISED** — 6/1 was a chop/mean-reverting day with no trend-through, so the 5/13 fix is still UNPROVEN live (needs a genuine trend day). Shipped 8 fixes + 3 follow-on features — RSI-50 Key Level, `gex_regime_raw`, Price Magnet panel + a numpy→native serialization fix (**94 tests + synthetic_replay green**): GEX hysteresis deadband, side-aware `mean_reverting`, portfolio-heat exposure + any-RED-leg, FADE-REGIME read (`mean_reversion_status`), escalation moat-floor, EXIT-grade JUSTIFIED, + 2 display fixes (neg-GEX wall message, expected-move card likelihood). Frontend esbuild-clean (run `npm run dev` to runtime-verify the FADE REGIME badge + book-risk chip). **NEXT:** prove P0-2 on a real trend day; build the **Price-Magnet outcome-validation log** (predicted magnet/touch% vs actual close — turns the panel from heuristic into measured); tune `GEX_REGIME_BAND` from live obs; expectancy scorecard after ~50 graded trades; P1-7 GEX in backtester.

### 2026-06-01 — live checkpoint + 8 fixes (files touched)
- **engine.py**: `stabilize_gex_regime()` (±`GEX_REGIME_BAND` deadband + sticky); `mean_reversion_status()` (FADE REGIME ON/OFF); side-aware `mean_reverting`/`trend_continuation` in `evaluate_positions` (magnet protects only when between spot & strike); `_get_escalation_level(..., moat=)` moat-floor (Bug E); `calculate_portfolio_heat(..., evaluated_positions=)` total $-risk + any-RED-leg + `_bump_level` (Bug C); neg-GEX gating of the wall-pull message (Bug A); expected-move-based card likelihood (Bug B).
- **config.py**: `GEX_REGIME_BAND = 20_000_000.0` (tune live).
- **accuracy_tracker.py**: `_grade_signal` JUSTIFIED when worst_moat<WARNING_ZONE OR over_limit OR trend_continuation; `track_signal` captures `over_limit`/`trend_continuation`.
- **main.py**: import + wire `stabilize_gex_regime` (module state `_gex_regime_prev`) after `fetch_gex_data`; `mean_reversion_status` → `TelemetryResponse.mean_reversion`; pass `evaluated_positions` + sizing/regime flags to heat & tracker.
- **Follow-on features:** `engine.compute_rsi_50_price()` (moving RSI-50 price → Key Level + `rsi_50_price`); `GexData.gex_regime_raw` (raw sign vs stabilized); `engine.compute_magnet_forces()` (GEX-wall / RSI-50 / Trend pull-strengths 0-100 + predicted magnet + touch% → `magnet_forces`).
- **app.jsx**: FADE REGIME badge + header FADE pill + book-risk chip on heat banner + **Price Magnet panel** (3 strength bars + predicted level + touch%). (esbuild-clean.)
- **Tests**: +13 (2 heat exposure, 1 EXIT-grade, 4 hysteresis/side-aware, 3 RSI-50-price, 2 magnet-forces, 1 serialization-native-types regression) → **94 total**. Harness GR-0513/0518/0519 force + GR-0529 hold PASS.

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
# Re-derived 2026-06-02 against current engine.py (~3888 lines) / app.jsx (~2454 lines). Use as anchors, not exact.
- `engine.py calculate_position_risk()` — ~line 23 (P0-3 sizing; wired into evaluate_positions, see below)
- `engine.py _get_escalation_level()` — ~line 255 (moat-floor param `moat=`)
- `engine.py compute_smart_moat()` — ~line 982 (7/8-factor smart moat)
- `engine.py move_consumed_factor` — ~line 1105-1116
- `engine.py stabilize_gex_regime()` — ~line 1205; `mean_reversion_status()` ~1223; `compute_rsi_50_price()` ~1258; `compute_magnet_forces()` ~1288
- `engine.py calculate_portfolio_heat()` — ~line 1398 (total_max_loss / pct_of_account / any-RED-leg)
- `engine.py detect_post_event_shift()` — ~line 1648
- `engine.py evaluate_positions()` — ~line 1745 (_pos_risk wired ~2431-2462; P0-2 mean_reverting/trend_continuation gate)
- `engine.py auto_propose_positions()` — ~line 3365
- `engine.py generate_market_insights()` — ~line 3492 (narrative cards)
- `main.py telemetry endpoint` — GET /api/telemetry, ~line 403-404
- `main.py TelemetryResponse` — ~line 300; `GexData` (gex_regime_raw) ~211; `EvaluatedPosition` (contracts/position_risk/mean_reverting) ~88-99
- `data_fetcher.py fetch_spx_day_range()` — ~line 68
- `data_fetcher.py _lookup_spread_direct()` — ~line 912 (SPXW direct pricing, no conversion)
- `data_fetcher.py _lookup_spread_spy_proxy()` — ~line 960 (SPY proxy with width_ratio scaling)
- `main.py _buyback_history` — ~line 27-29, premium velocity ring buffer
- `main.py velocity computation` — ~line 589-633 (after evaluate_positions)
- `app.jsx` — single-file React; Key Evidence & Levels section ~line 492-498
- `test_engine.py` — 68 tests; `test_positions.py` — 26 tests (94 total + synthetic_replay.py)
- `.windsurfrules` — test count line ~29, pitfalls ~93+, version history ~127+

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
