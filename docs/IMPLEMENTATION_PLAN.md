# 0DTE Quant Engine — Implementation Plan
# Created: 2026-05-29 — from a full-codebase audit (engine, data layer, orchestration, signal tracker, backtester, frontend, docs, and the real Robinhood trade history).
# Companions: VALIDATION_PLAN.md (how each item is proven before/after it touches real money) · implementation_progress.md (live phase status)
# Maintenance: when an item ships, check it off here, bump implementation_progress.md, and follow CLAUDE.md rules 2–4 (keep docs + .windsurfrules in sync).

---

## WHY THIS PLAN EXISTS (the reframe)

**Corrected with the full month (5/5–5/29) + the user's backtest API (2026-05-29):** the strategy is **profitable** — backtest **+$5,759.99 over 16 days, 80% win rate, profit factor 1.51** (cash-basis SPXW net ≈ **+$7,636**). The earlier "−$528" was a truncated, unlucky 5/5–5/13 window, not the verdict. **But the tail risk is systemic, not a one-off:** deep-ITM trend-throughs recurred on 5/13 (−$1,696), 5/18 (−$1,074 put), 5/19 (−$5,189 call, the worst trade), 5/20, etc. The green months are partly *size-and-offset absorbing recurring tail events*.

The backtest also graded the engine's signals: of **36 EXIT flags, 25 WON anyway** (false alarms) and **11 LOST** (correct), with **23 correct holds** and **1 miss**. So the engine catches ~all losers (high recall) but over-flags exits badly (low precision) — following it mechanically would cut the winners that produced the profit. The fix is **precision** (stop crying wolf on mean-reverting noise), which is exactly P0-2's regime gate — and note the backtester has **no GEX** (`gex: null` every day), so it CANNOT validate P0-2; that needs live GEX (P1-7 / live sessions). The smart_moat is pinned at its **30-pt floor on virtually every bar** of the backtest — confirming P1-2 (the floor binds; the moat barely discriminates).

Two problems compound this:
1. The trading logs (5/20, 5/26) both ended green and canonized "I held through CRITICAL_EJECT and was right." The engine's most recent tuning — reversal-aware exit **downgrades** and the profit-aware escalation **cap** — was calibrated on those winning days and would have *encouraged* the exact hold that lost $1,696 on 5/13.
2. The feedback layer meant to catch this is dormant: `signal_log.jsonl` has exactly one record, graded PENDING. None of the ~40 hand-tuned moat multipliers have ever been validated against outcomes.

So this plan deliberately reorders work away from "add more heuristics" toward: **(P0) prevent the tail loss + revive the meter → (P1) make the engine tunable and validate it → (P2) then build the planned product features → (P3) pay down structural debt.**

---

## PRIORITY KEY & VALIDATION GATES

- **P0** — capital-risk / correctness. Can produce a wrong risk signal or a crash. Do first.
- **P1** — validate & de-risk. Makes the engine tunable, evidence-based, and safe to operate.
- **P2** — planned product features (the existing backlog), now gated behind a working validation loop.
- **P3** — hygiene & architecture.

**Validation gate** (see VALIDATION_PLAN.md): `T0` unit/deterministic · `T1` synthetic-scenario replay (free SPY data + injected synthetic positions; includes the reconstructed 5/13 keystone and hand-built stress paths) · `T2` live session (forward confirmation) · `GR` = the 5/13 keystone fixture, now a T1 scenario. *(A dollar-accurate backtest with paid option chains is deferred — not needed to validate decisions.)*

Effort: **S** ≈ <½ day · **M** ≈ 1–2 days · **L** ≈ 3+ days.

---

## NEXT-UP — RANKED (post P0-2, 2026-05-29)

Shipped 2026-05-29: **P0-2 regime-conditional EJECT** (validated GR-0513 + GR-0529) and the **sizing config + `calculate_position_risk()` helper**. Ranked recommendation for what's next, by value × effort. Effort: S ≈ <½ day, M ≈ 1–2 days, L ≈ 3+ days.

### Tier 1 — do first (highest value, Monday-facing)
| # | Item | What ships | Value | Effort | Gate |
|---|------|-----------|-------|--------|------|
| 1 | **P0-3a + sizing banner** | `contracts` on positions (DB + entry) → live "**$X at risk = Y% of account**" banner via `calculate_position_risk()`; warn/block over the $2k cap | ★★★ the #1 live lesson (85% of acct) | M | T0 + manual UI |
| 2 | **P1-5 pricing** | Ask-side close (not mid) + editable actual-fill input + tighten cache | ★★★ untrustworthy P&L corrupts every hold/close + take-profit | M | T0 + live A/B vs broker |
| 3 | **P0-6 revive tracker** | Resolve signals on expiry (EOD sweep), grade them; the meter that proves P0-2 etc. work | ★★★ without it nothing is measurable | M | T0 + replay |
| 4 | **P0-5 quick bugs** | `p.moat ?? 999`; inverted "−X below" wording; stale-VIX-as-`live`; expired-ITM `credit*9` | ★★ cheap correctness | S | T0 |

### Tier 2 — soon
| # | Item | What ships | Value | Effort | Gate |
|---|------|-----------|-------|--------|------|
| 5 | **P1-4 / L5+L7 single-source verdict** | One verdict per position; kill the GREEN-card-vs-HIGH/CLOSE contradiction + stale/toggling rec wording | ★★★ misled in real time both ways today | M | manual |
| 6 | **Expose P0-2 fields** | Add `mean_reverting`/`trend_continuation` to the Pydantic schema + a small UI badge | ★★ makes the new logic visible | S | schema |
| 7 | **P0-1 EST quarantine** | EST pricing never drives escalation/take-profit/grading | ★★ matters on a ThetaData outage | S–M | T0 |
| 8 | **P0-7 thresholds** | Vol-scale gamma/warning from σ; flag the SPX/SPY ×10 proxy fallback | ★★ fixed 10/25 pts is noise at SPX 7500 | M | T0 |

### Tier 3 — then (soundness + scale + polish)
| # | Item | What ships | Value | Effort | Gate |
|---|------|-----------|-------|--------|------|
| 9 | **P1-1 + P1-2 moat math** | Collapse the move-consumed double-discount; bound/justify the multiplicative stack + floor | ★★ algorithmic soundness | M | T0 + replay |
| 10 | **P3-7 GEX + L8 regime stability** | Fix call-wall semantics / sign convention; smooth the flip-flopping regime-transition signal | ★★ both seen live | M | T0 |
| 11 | **P1-6 + P1-7 backtester + data** | Point-in-time replay at scale + historical option chains (ThetaData Standard) for $-accurate tuning | ★★★ long-term, enables real tuning | L | self |
| 12 | **P2 features + P3 hygiene** | RSI badge, what-if-at-SPX, sparkline, GEX wall pressure, breakeven-exit persistence (L10); decompose `evaluate_positions`, concurrency locks, DB migrations | ★ polish / debt | varies | varies |

---

## DEPENDENCY MAP (sequencing)

- **The meter must work before anything quantitative can be judged.** P0-6 (revive Signal Tracker) + P1-6 (synthetic-scenario replay harness — free, no paid data, no trade timestamps) unblock evidence-based validation of every multiplier and rule. Paid historical option chains (P1-7) are optional and only buy dollar-accurate P&L, not decision validation.
- **P0-5** (bug fixes), **P0-1** (EST quarantine), **P0-2** (EJECT carve-out) are independent and aimed squarely at the 5/13 scenario — do them first.
- **P1-3** (centralize config) should precede **P1-8** (re-tune multipliers) — you can't tune what's hardcoded.
- Frontend safety (P1-4) is independent and can run in parallel.

---

## PHASE P0 — Stop the bleeding & restore trust

### P0-1 — Quarantine EST pricing from decisions
- **What:** When `pricing_source == "EST"`, the heuristic `estimated_buyback`/`profit_pct` must be display-only. It must NOT drive the profit-aware escalation cap, take-profit recommendations, or signal grading.
- **Why:** The buyback fraction model is ~$0.40 off (CLAUDE.md pitfall #4). A position can *look* 50% profitable on a bad estimate while the real mid has blown out, downgrading an URGENT_CLOSE to a calm "take profit." It also corrupts the tracker's dollar-valued grades.
- **Files:** engine.py:1748–1819, 1998–2019, 2286; main.py:533–545; accuracy_tracker.py.
- **Depends:** none. **Effort:** M. **Gate:** T0 + GR(5/13).
- **Pass:** EST pricing never changes an escalation/take-profit decision; tracker stores `pricing_source` and flags/excludes EST-graded signals.

### P0-2 — CRITICAL_EJECT vs reversal-downgrade: make it REGIME-CONDITIONAL (revised 2026-05-29 from live evidence)
- **What:** Gate the force-close on regime instead of applying it — or the reversal-downgrade — blanket:
  - **Force the close (EJECT non-downgradable)** on the *trend-continuation* signature: negative GEX **or** active TREND_SURGE **or** (rising ER + price making a new extreme in the losing direction). ← this is 5/13.
  - **Suppress the force / let the reversal-downgrade hold** on the *mean-reverting* signature: **positive GEX + RSI extreme + no surge**. ← this is 5/29.
- **Why (two live cases now):** 5/13 (−$1,696) and 5/29 (+$1,255) are the SAME structural setup — a with-trend short pressed toward the strike — with **opposite correct actions**. The discriminator is regime. On 5/29 the engine's CLOSE_SOON (10:47) and RED card (14:14) were BOTH premature; the position bounced twice on positive GEX + RSI 33–36, and a blanket force-close would have realized −$1,320 instead of +$1,255. So P0-2 must NOT be blanket — it fires only on the negative-GEX / surge / trend signature.
- **Files:** engine.py:1475–1543 (reversal_score), 1998–2019 (profit cap), 2021–2038 (downgrade); add a `continuation_score` regime gate.
- **Depends:** none. **Effort:** M. **Gate:** T1 — must pass BOTH **GR-0513** (force a non-downgradable EJECT before strike touch) AND **GR-0529** (do NOT force-close the positive-GEX bounce; hold through).
- **Pass:** 5/13 → sustained EJECT before breach; 5/29 → no forced close, rides the bounce.

### P0-3 — Position-sizing / portfolio max-$ governor + add-to-loser block
- **What:** Pre-trade and live check on absolute dollar risk vs account size: max contracts, max % of account at risk per side, per-day loss limit. Actively warn/block adding contracts to a losing or stressed side.
- **Why:** The 5/13 loss was severity-by-**size** (10–11 lots ≈ >50% of account on one side), not strike selection. The engine tracks per-position moat and concentration "heat" but has no absolute $-risk governor. Adding to the losing side is the recurring real behavior the logs flag every session.
- **Files:** new governor in engine.py + thresholds in config.py + `auto_propose_positions` + frontend surfacing.
- **Depends:** account size / risk budget from Ativ. **Effort:** M–L. **Gate:** T0 + T1 (5/13 sizing scenario) + T2.
- **Pass:** 5/13's 10-lot is flagged over-limit; an add-to-loser action produces an explicit BLOCK recommendation.

### P0-4 — Assignment / cash-settlement awareness
- **What:** Flag end-of-day ITM/pin risk on short legs near the strike; warn that SPXW is **cash-settled** (and the AM-settled SPX vs PM-settled SPXW nuance); represent assignment/settlement in Day P&L.
- **Why:** The worst real event (OASGN 7445 put + $750 OCC) is completely unmodeled. `realized_pl = credit − close_price` can't even express it, so Day P&L mis-states 5/13.
- **Files:** engine.py (EOD pin warning) + main.py P&L + database.py (settlement field).
- **Depends:** none. **Effort:** M. **Gate:** T0 + GR(5/13 put).
- **Pass:** 5/13 7445 put flagged for pin risk before close; settlement loss reflected in P&L.

### P0-5 — Quick-win correctness bugs
- **What:** Fix the discrete bugs found in the audit:
  - Expired-ITM P&L `-credit * 9` is wrong shape & ~100× off → use `(width − credit) × 100` (engine.py:1559).
  - `Math.min(...positions.map(p => p.moat || 999))` masks `moat === 0` (max danger) as safe → `?? 999` (app.jsx:603).
  - `:.0f` format on a `None` `trigger_spx` → TypeError when reversal downgrades a gamma-trap close (engine.py:2035).
  - Stale VIX returned with `source="live"` (data_fetcher.py:202).
  - GEX uses naive `datetime.now()` assuming ET host → degenerate GEX off-ET (data_fetcher.py:545).
  - `profit_factor` can be `inf` → invalid JSON (trade_history.py:302).
  - Unreachable move-consumed fallback branch (engine.py:1061–1073).
- **Files:** as listed. **Depends:** none. **Effort:** S each. **Gate:** T0.
- **Pass:** a unit test per bug.

### P0-6 — Revive the Signal Tracker (resolve on expiry) — *the meter*
- **What:** Resolve signals on expiry (OTM/ITM), not just manual close. Make `EXPIRED` a terminal, graded action; add an EOD sweep (or scheduled close) that grades open positions; stop the unresolved-record memory leak; record `pricing_source` on each signal.
- **Why:** Expiry is the dominant 0DTE outcome and currently never resolves a signal — the grader almost never runs (one PENDING record ever). Nothing else in this plan can be validated until this works.
- **Files:** accuracy_tracker.py:40–42, 236; main.py:341–362; engine.py:1583; + a scheduled EOD job.
- **Depends:** none (this unblocks validation broadly). **Effort:** M. **Gate:** T0 + replay.
- **Pass:** expired trades produce graded CORRECT/WRONG records; `_active_signals` does not leak.

### P0-7 — Vol-scale danger thresholds + flag the proxy fallback
- **What:** Derive `GAMMA_TRAP_THRESHOLD` / `WARNING_ZONE_THRESHOLD` from `conditional_1σ` rather than fixed 10/25 points. When the SPX/SPY ratio falls back to exactly 10.0 (Yahoo `^GSPC` down), surface a "degraded — proxy price" flag and widen the moat defensively.
- **Why:** 10 pts at SPX ~7500 is ~0.13% — inside late-day noise; thresholds were tuned for SPX ~5900. The silent `ratio = 10.0000` fallback reintroduces the exact drift the system was built to avoid (±~7.5 pts), with no flag reaching the risk engine.
- **Files:** config.py:93, 96–98; data_fetcher.py:56, 1008–1019; main.py:415.
- **Depends:** none. **Effort:** M. **Gate:** T0.
- **Pass:** thresholds scale with vol; proxy fallback raises a visible degraded state.

---

## PHASE P1 — Validate, de-risk, and make tunable

### P1-1 — Collapse the move-consumed double-discount
- **What:** Apply the consumed-move discount in exactly one place. Today it's baked into `conditional_1σ` (data_fetcher.py:241–260) *and* re-applied as a smart-moat factor (engine.py:1052–1073).
- **Files:** engine.py:1052–1073; data_fetcher.py:241–260. **Effort:** M. **Gate:** T0 + T1.
- **Pass:** a high-momentum day discounts the moat once, with a documented basis.

### P1-2 — Bound the multiplicative smart-moat stack
- **What:** Add an explicit overall cap and document the floor; evaluate replacing the product-of-8-guessed-coefficients with an additive weighted scheme (`base × (1 + Σ weighted adjustments)`) bounded top and bottom.
- **Why:** correlated factors compound (range × signal × exhaustion × time can hit ×0.28); the only guard is a floor barely outside the warning zone (engine.py:1122).
- **Files:** engine.py:1077, 1121–1122. **Effort:** M. **Gate:** T0 + T1.

### P1-3 — Move all magic numbers into config.py
- **What:** Centralize every algorithmic constant currently hardcoded in engine.py (moat multipliers + band edges, reversal-score points/thresholds, IV-multiplier coefficients, `buyback_frac` curves, surge thresholds, take-profit tiers 90/80/75/50, the FOMC/CPI/NFP calendar) plus `accuracy_tracker.SPREAD_WIDTH`/`MIN_SIGNALS_FOR_DISPLAY` and `data_fetcher` `net_gex` cutoff and `r=0.05`.
- **Why:** CLAUDE.md convention #11; tuning is currently impossible without code edits + redeploy. Prerequisite for P1-8.
- **Effort:** M. **Gate:** T0 (behavior unchanged).

### P1-4 — Frontend safety pass
- **What:** Real data-age indicator tied to actual fetch time + grey-out/disable when stale; clear or visibly mark `telemetry` on fetch error (stop showing stale data as fresh under a live-ticking clock); add an error boundary; hoist the per-position eject/escalation verdict into an always-visible top strip; consolidate the five stacked banners into one priority-ranked alert; `?? 999` fix; fix the aggregate `~` estimate gate; faster poll cadence in power hour.
- **Files:** app.jsx:59–71, 200, 228, 308–411, 603, 1321, 1519–1663. **Effort:** M. **Gate:** T0 (UI logic) + manual review.

### P1-5 — Accurate pricing: ask-side close + editable actual fills — **BUMPED toward P0 (live-validated 2026-05-29)**
- **What:** (a) price the buyback at the realistic **ask-side close** (buy the short leg at its ask, sell the long leg at its bid), not the NBBO mid; (b) let the user enter the actual fill price/credit per position; (c) tighten/flag the ≤30s quote-cache staleness; (d) surface bid/ask, not a single mid.
- **Why:** Live-validated 5/29 — estimated buyback diverged from the Robinhood mark by **$0.01–0.10 all day** (10:47 $1.30 vs $1.40; 14:14 $0.38 vs $0.44; up to ~$200 on 20 lots). Root cause: quoting the **mid** when a credit spread closes near the **ask**, plus cache staleness and ThetaData-vs-broker feed differences. An untrustworthy profit %/P&L silently corrupts every hold/close decision — and the take-profit/escalation logic that reads it.
- **Files:** data_fetcher.py (`get_spread_buyback_price` — ask/bid sides; cache TTL); engine.py (`estimated_buyback`/`profit_pct`); main.py + app.jsx (actual-fill input).
- **Effort:** M. **Gate:** T0 (ask-side math) + live A/B vs the broker mark.

### P1-6 — Build the synthetic-scenario replay harness (free) — *the primary validator*
- **What:** Drive the engine bar-by-bar at **bar-time** (never `datetime.now()`) over a price path + an injected **synthetic position** (structure, strikes, contracts, credit, entry time-of-day). Path = a real day from free SPY bars (Alpaca / committed CSV, scaled to SPX) **or** a hand-built archetype. Assert the action sequence + timing vs the strike path. Reset all module-global state per scenario (incl. `_drift_history`).
- **Why:** Robinhood exports have no intraday timestamps, but the engine's exit/sizing *decisions* don't depend on entry time — only on the SPX path + moat + regime + strikes. This sidesteps the timestamp problem and the paid-data dependency, and lets us **manufacture** the 5/13-type day on demand. It also fixes the old backtester's wall-clock leak / pre-entry evaluation / today's-ratio-on-old-data flaws.
- **Files:** new `synthetic_replay.py` (reuses engine.py functions); free SPY bars via data_fetcher / committed fixture CSVs.
- **Depends:** P0-6 (tracker) for grading. **Effort:** M. **Gate:** self-validates against the reconstructed 5/13 outcome + the guard scenarios.
- **Pass:** the harness reproduces a sustained pre-breach EJECT on 5/13 and stays quiet on the calm/whipsaw guards; no wall-clock dependence.

### P1-7 — *(Deferred / optional)* Acquire historical option chains for P&L realism
- **What:** Only if/when we want **dollar-accurate** exit-cost modeling in replay (the decision logic in P1-6 does not need it). Adds a historical chain pull + historical GEX reconstruction.
- **Recommendation (when needed):** **ThetaData "Options Standard" (~$80/mo, verify current)** — reuses your existing integration; adds historical Option Chain Snapshots + OPRA NBBO quotes + tick + 8 yrs, enough to price SPXW spreads and rebuild GEX point-in-time. (The $40 "Value" tier is 1-min only, no chain snapshots — insufficient.) Alternatives: **ORATS (~$99/mo)** 25-yr EOD depth; **Polygon (~$79/mo options)** raw chains; **CBOE DataShop / Intrinio** $1k+/mo (overkill); **FlashAlpha Alpha (~$1,499/mo)** pre-computed point-in-time GEX replay.
- **Depends:** Ativ go-ahead (deferred). **Effort:** M. **Gate:** improves P&L realism only; decision gates already met at P1-6.

### P1-8 — Re-tune multipliers against the rebuilt backtester
- **What:** Replace hand-set constants (now in config.py) with values justified by replay across multiple regimes; document the basis for each.
- **Depends:** P1-3, P1-6 (decision-quality tuning runs on synthetic replay; $-precise tuning also needs the deferred P1-7). **Effort:** M–L. **Gate:** T1.
- **Pass:** every multiplier has a documented empirical basis, not a guess.

### P1-9 — Per-stage error isolation + concurrency safety
- **What:** Telemetry endpoint degrades gracefully when one source fails (don't 500 the whole dashboard); add locks around module-global state (`_rec_state`, `_escalation_state`, `_drift_history`, `_buyback_history`, `_active_signals`) or move it to a proper store.
- **Files:** main.py:381–738; engine.py globals. **Effort:** M. **Gate:** T0.

### P1-10 — Pydantic schema sync
- **What:** Stop silently dropping undeclared engine fields (`reversal_score`, `heat_score`, drift fields) — declare them or generate the schema from the engine contract (CLAUDE.md pitfall #6).
- **Files:** main.py:81, 264–324. **Effort:** S–M. **Gate:** T0.

---

## PHASE P2 — Planned product features (existing backlog, now evidence-gated)

| ID | Feature | Source | Notes |
|----|---------|--------|-------|
| P2-1 | **Time-to-breach / ETA** (SPX pts-per-min toward strike + ETA) | audit | Highest-value near-expiry number; algo + frontend |
| P2-2 | RSI Reversal Warning badge | #35 | "Overbought — reversal likely" on card + story |
| P2-3 | What-if at hypothetical SPX / "what would need to happen for ITM" | #31 | Scenario input on position card |
| P2-4 | Premium sparkline / moat-over-time per position | #28 | Ring-buffer data already exists |
| P2-5 | Explain Mode toggle (inline tooltips on technical terms) | log 5/26 | |
| P2-6 | GEX Wall Pressure (time-near-wall) | Phase 8 | Deferred; wall pressure on cards |
| P2-7 | GEX Wall Rejection Count + magnitude trend | #34, #36 | Needs price-near-wall history |
| P2-8 | Divergence / Override tracking display | #33 | Show + score user overrides vs system; ties to tracker |
| P2-9 | Conviction Score for entry | log 5/26 | |
| P2-10 | EOD review generator ("Today you learned…") | backlog | Auto from tracker + structured session log |
| P2-11 | Shadow Trader (simulated algo vs user) | deferred | Overlaps T2 paper validation; build after tracker + backtester |
| P2-12 | Live econ-calendar (Tier 1 events) | #22 | Replace hardcoded FOMC/CPI/NFP times |
| P2-13 | Position-card essentials: contracts, spread width, long strike, max loss/contract | audit | Defined-risk basics currently not shown live |

---

## PHASE P3 — Hygiene & architecture

| ID | Item | Notes |
|----|------|-------|
| P3-1 | Decompose `evaluate_positions` (640 lines) | zone classifier / pricing / exit-selector / persistence |
| P3-2 | Remove duplication | call/put mirror blocks, indicator block ×3, `analyze_trade` re-impl of pipeline, regime continuous-score dup |
| P3-3 | Database | Alembic migrations, index `closed_at`/`close_reason`, WAL + busy_timeout, tz-safe reads |
| P3-4 | Test coverage on money paths | smart-moat compounding + floor, buyback heuristic, escalation ladder (injectable clock), hysteresis, data-fetcher fallbacks, main.py pipeline smoke, reversal-score pinning; isolate global state in test_engine.py; remove/convert test_simulator.py |
| P3-5 | New analytics inputs | intraday realized vol (from SPY bars you already have), VIX term structure (VIX9D/VIX), IV skew, breadth/$TICK; persist `spx_spy_ratio` daily as a drift monitor |
| P3-6 | Reconcile docs | one version scheme + factor count + phase numbering across CLAUDE.md / Algorithm_States.md / readme; fix stale test count & Python-version notes |
| P3-7 | GEX correctness | call-wall semantics (currently `idxmax(call_gex)` ≈ gamma wall), put/call sign convention review, `net_gex` normalization to daily OI, pass `hours_remaining` into GEX instead of naive clock |

---

## LIVE-SESSION FINDINGS — 2026-05-29 (folded into the phases)

A full live session (20-lot 7550/7545 put spread, −$1,320 → +$1,255) produced these, each mapped to a plan item:

| # | Finding | Maps to |
|---|---------|---------|
| L1 | **Sizing was the real risk** — 20 lots = 85% of the $10k account; won on a mean-reversion read, not risk control. Same pattern as 5/13. | **P0-3 (confirmed #1)** |
| L2 | **Engine is contract-count-blind** — never sees size, partial closes, or realized-vs-remaining. Prerequisite for any sizing logic. | **P0-3a (new prereq):** add `contracts` to positions (DB + input) |
| L3 | **Pricing off $0.01–0.10 all day** (mid vs ask + staleness). | **P1-5 (bumped)** |
| L4 | **EJECT/close must be regime-conditional** — positive-GEX bounce vs 5/13 trend-through. | **P0-2 (rewritten)** + new **GR-0529** golden case |
| L5 | **Narrative light wrong both ways** — GREEN card downplayed real AM risk; RED card understated a winning PM position; card whipsawed GREEN↔RED on moat oscillation. | **P1-4** — single source-of-truth verdict; kill the card-vs-rec contradiction |
| L6 | **Take-profit time-aware but size-blind** — fired correctly at 77–82% in the gamma ramp, but never weighs $-at-risk. | folds into **P0-3** |
| L7 | **Stale/inverted recommendations** — HIGH/CLOSE keyed on the day-low, toggled with the shrinking recommended-min, fired on a +70% position; "−1.2 pts below" wording is inverted. | **P1-4 / P3** — recs reflect current state; fix wording |
| L8 | **Regime-transition signal unstable** — flipped SOFTENING↔FIRMING↔DETERIORATING within minutes. | **P3** — smooth/decay the transition signal |
| L9 | **smart_moat hit its hard floor (30)** late-day — recommended moat compressed to the clamp; "safe vs recommended" became meaningless. | **P1-2** — bound/justify the stack + floor |
| L10 | **Breakeven-exit nudge non-persistent** — flashed once at 10:52, gone by 11:00. | **P2** — persist the breakeven-exit opportunity |
| L11 | **Signal tracker dormant** — 0 resolved until the final manual close; the 10:47 premature signal went ungraded. | **P0-6 (confirmed)** |

---

## INPUTS NEEDED FROM ATIV

1. **Per-trade & per-day risk cap** → sets the P0-3 sizing guardrail. Account = **$10k** (known). Today's 20-lot was $8,520 = **85%** of it; need a sane per-trade max loss (see Monday prep question).
2. **Actual fill credits per trade** → P1-5, so stop math matches your broker. *(Intraday timestamps are NOT needed — synthetic replay supplies the entry time.)*
3. *(Deferred / optional)* **historical data-vendor go-ahead** (ThetaData Standard) → only for dollar-accurate P&L backtests; not required to validate decisions.
4. **Which changes to put "under test" first** → see VALIDATION_PLAN.md.

---

## SUGGESTED FIRST SPRINT

**Done 2026-05-29:** P1-6 synthetic-replay harness built + the 5/13 EJECT-hold bug reproduced (`backend/synthetic_replay.py`); a full live session validated the priorities and refined P0-2.

**Next — Monday-ready, safe & non-invasive (no change to close logic):** P0-3a contract-count + a **sizing % banner** (the day's #1 lesson), P1-5 ask-side pricing + actual-fill input, and the P0-5 quick bugs. These improve Monday's *decisions* without touching the exit algorithm.

**Then — validate-before-ship:** P0-2 regime-conditional EJECT + P0-1 EST quarantine + P0-6 tracker, each gated through the harness against **GR-0513 AND GR-0529** before going live. P1 tuning follows with evidence.
