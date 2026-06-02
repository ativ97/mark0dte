# 0DTE Quant Engine — Validation Plan
# Created: 2026-05-29 · Revised: 2026-05-29 (v2 — synthetic-replay + live hybrid; paid historical-data dependency dropped)
# Companion: IMPLEMENTATION_PLAN.md (the changes) · accuracy_tracker.py (the meter)
# Purpose: prove each change works — and keep proving it — without waiting for (or paying for) a bad day, and without repeating the survivorship mistake that produced the 5/13 loss.

---

## WHAT CHANGED IN v2

- Robinhood exports have **no intraday timestamps**, so "replay and grade my exact past trades" isn't feasible.
- **It doesn't need to be.** The engine's exit/sizing *decisions* are driven by the SPX price path + moat distance + regime indicators (RSI/ER/CHOP off SPY bars) + the position's strikes — **not** by when you entered. So we validate by replaying the engine over historical or hand-built SPY price paths with **synthetic positions** injected. No trade timestamps, no paid option-chain data required.
- **Paid historical option chains (ThetaData) are now DEFERRED** — needed only for dollar-accurate P&L realism, not for validating decisions. This makes validation cheaper, faster, and runnable today.
- **Live sessions are the forward-confirmation layer** (your chosen method), not the primary proof for rare-event changes.

---

## THE PROBLEM THIS PLAN SOLVES

The old trading logs "validated" the engine by ending green and concluding "I held through CRITICAL_EJECT and was right." That's how a strategy with 80% small wins and one catastrophic loss fools you — until 5/13 (−$1,696 + a $750 assignment). Real net P&L was **−$528**. Validation here resists that: pre-registered hypotheses, dollar/tail metrics instead of hit-rate, and the rare event **manufactured on demand** instead of waited for.

---

## PRINCIPLES

1. **Validate on a ladder, cheapest/safest first** (T0 → T2 below).
2. **Manufacture the rare event; don't wait for it.** The changes that matter (EJECT carve-out, sizing) only fire on a trend-through day. We build that day synthetically rather than risk real capital to see if the safety net works.
3. **Pre-register the hypothesis and pass/fail BEFORE building.** Deciding what "worked" after seeing the result just confirms priors.
4. **Offline gate before real money.** No change reaches a live session until it passes T0 and the relevant T1 scenarios (including 5/13).
5. **Capture every session structured (machine-readable), feeding the tracker** — not prose.
6. **Measure dollars and tails, not hit-rate.** You were 80% right and lost money.

---

## THE VALIDATION LADDER (v2)

| Tier | What it validates | What it needs | Cost / risk |
|------|-------------------|---------------|-------------|
| **T0 — Deterministic** | Logic & bugs: EST quarantine, threshold scaling, tracker resolution, every P0-5 bug | Unit tests + tiny fixtures | Free, instant, zero risk |
| **T1 — Synthetic-scenario replay** *(primary quant proof)* | Behavior across regimes: EJECT carve-out, sizing governor, reversal logic, moat behavior — on reconstructed real days **and** hand-built stress paths | Free SPY bars + the replay harness + synthetic positions | Free, offline, zero capital risk |
| **T2 — Live sessions** *(your forward method)* | Everyday calibration, over-triggering, override scorecard, real-use bugs | Structured capture (below) + offline-gated changes only | Real capital — gated by T0/T1 |
| *(Deferred) P&L-realistic backtest* | Dollar-accurate exit-cost modeling | Paid historical option chains (ThetaData Standard) | Optional; only when we want $-precise backtests |

**The honest hierarchy:** the rare-event changes that caused your loss are proven at **T1 (synthetic replay)**, not in a live day. A live session tests one regime that you can't control; T1 tests the exact regimes you choose, today, for free. Live sessions confirm and calibrate — they don't prove the tail.

---

## HOW SYNTHETIC-SCENARIO REPLAY WORKS (the core method)

**Inputs:**
- A **price path** — either a real historical day (free SPY 1/5-min bars from Alpaca or a committed CSV, scaled to SPX) or a **hand-built archetype** (e.g., a steady grind up through a strike).
- A **synthetic position** — structure, short/long strikes, contracts, credit, and entry time-of-day (chosen by us, since real entry times don't exist).

**Process:**
- Drive `analyze_market_regime` → `compute_smart_moat` → `evaluate_positions` **bar-by-bar at bar-time** (this also fixes the old backtester's wall-clock leak — time comes from the bar, never `datetime.now()`).
- Record the **action sequence** (HOLD → CLOSE_SOON → CRITICAL_EJECT …) and its timing relative to the strike path.

**Asserts** are about *decisions and timing*, e.g. "EJECT fired and stayed fired before SPX touched the short strike," "the 10-lot was flagged over-limit at entry," "no close signal on the calm range day."

**What it needs:** free SPY bars + the engine running with injected bar-time. **What it does NOT need:** your entry timestamps, paid option chains, or live ThetaData. (Option pricing only affects *P&L estimates*, which we defer; it does not change the exit/sizing *decision*.)

---

## SCENARIO LIBRARY (manufacture the regimes)

**A) Reconstructed real days** (free SPY data):

| Scenario | Source | Validates |
|----------|--------|-----------|
| **5/13** *(keystone)* | real day | EJECT carve-out (P0-2), sizing (P0-3), assignment/pin (P0-4) |
| 5/20, 5/26 | the two "winning" log days | fixes do **not** over-trigger and ruin normal winning days |

**B) Synthetic archetypes** (hand-built paths that stress one rule each):

| Archetype | Path shape | Validates |
|-----------|-----------|-----------|
| Trend-through | steady grind up/down through the short strike | EJECT carve-out fires & holds (P0-2) |
| Gap-and-go | open gap then continuation | gap rejection + sizing |
| Late-day grind | slow drift into strike in final hour | time-pressure escalation |
| Whipsaw / mean-revert | spike toward strike then snap back | EJECT **not** over-triggered (guards the winners) |
| Calm range | quiet chop, never near strike | baseline — no false alarms |

Together these test **both** failure directions: *catch the loss* (trend-through, 5/13) without *ruining the winners* (whipsaw, calm, 5/20, 5/26).

---

## 5/13 KEYSTONE RECONSTRUCTION (the first harness we build)

1. Pull free SPY 1/5-min bars for **2026-05-13**, scale to SPX via the day's ratio.
2. Inject the real 5/13 positions: call spread **7440/7445 ×4**, put spread **7445/7440 ×10**, call spread **7465/7470 ×11**.
3. Assert on the *improved* engine:
   - the **7440 call** spread gets a **sustained, non-downgradable EJECT before SPX touches 7440** (P0-2);
   - the **10-lot put** is flagged **over-limit at entry** and pin/assignment risk is raised near close (P0-3, P0-4);
   - the **safe 7465 call** spread is **not** alarmed (selectivity).

This single fixture regression-guards P0-2, P0-3, and P0-4 at once, and becomes a permanent test that fails loudly if a future change re-opens the door to the 5/13 outcome.

---

## PRE-REGISTERED HYPOTHESES (set pass/fail before building each)

| Change | Hypothesis | Tier | PASS | FAIL |
|--------|-----------|------|------|------|
| P0-1 EST quarantine | EST pricing changes no escalation/take-profit decision | T0 | escalation identical regardless of EST flag (display-only) | EST flips any escalation/TP |
| P0-2 EJECT carve-out | with-trend short breaching → sustained EJECT before strike touch | T1 (5/13 + trend-through) | EJECT fired & held pre-breach | downgraded, or fired post-breach |
| P0-3 sizing governor | oversized lot flagged over-limit pre-entry; add-to-loser blocked | T0 + T1 (5/13) | over-limit flag + BLOCK rec | allowed silently |
| P0-4 assignment | short leg near strike late → pin warning; settlement in P&L | T1 (5/13 put) | warning + correct settlement P&L | silent / wrong P&L |
| P0-6 tracker | expired position → exactly one graded terminal record | T0 | graded CORRECT/WRONG, no leak | PENDING / unresolved leak |
| P0-7 thresholds | gamma-trap distance scales with vol; ratio fallback flagged | T0 | scales + degraded flag | fixed / silent |
| P1-1 double-discount | 1.5σ-consumed day discounts moat once | T0 + T1 | single documented discount | compounded |
| P1-2 stack bound | worst-case compounded factor within documented cap/floor | T0 + T1 | bounded | unbounded collapse |
| (re-tune, later) | re-tuned multipliers improve tail behavior across the scenario set | T1 | better tail-adjusted behavior, ≥2 archetypes | no improvement / overfit |

---

## LIVE-SESSION PROTOCOL (your forward method — confirmation + calibration)

Use live sessions to answer what synthetic replay can't: *do the new rails over-trigger in real use? does the moat feel right day to day? where do you override, and who's right?* Not to prove the rare-event changes — those are gated by T1 first.

**Before:** list the changes "under test," their pre-registered PASS/FAIL, the max risk budget, and which P0-3 limits are active. Confirm each change already passed T0 + its T1 scenarios.

**During:** the engine logs a structured event per decision point (it has the ring-buffer + tracker plumbing; P0-6 makes it graded). For each, record **your** decision — follow / override + a reason code. Overrides are the most valuable data.

**After:** auto EOD report from the tracker — every signal graded (CORRECT/JUSTIFIED/PREMATURE/WRONG, dollar-valued), the override scorecard, hypothesis verdicts, P&L attribution by regime, and the day's worst single-position drawdown (tail watch).

**Safety rails:** offline-gated changes only; size cap; P0-3 governor + add-to-loser block active.

---

## STRUCTURED CAPTURE SCHEMA (replaces docs/trading_log_*.md prose)

One session header + one line per decision event, JSONL so it feeds the tracker and aggregates across sessions:

```jsonc
// session header
{"type":"session","date":"2026-06-XX","changes_under_test":["P0-2","P0-3"],
 "account_size":NNNN,"max_risk_budget":NNN,"regime_open":"...","notes":""}

// decision event (one per signal / per poll where action changes)
{"type":"decision","ts":"2026-06-XXThh:mm:ssET","pos_id":"...",
 "structure":"call_spread","short_strike":7440,"long_strike":7445,"contracts":4,"credit":0.50,
 "spx":7438.2,"moat":-1.8,"smart_moat":31,"regime":"STRONG_BULLISH","er":0.46,"rsi":71,
 "gex_regime":"NEGATIVE","reversal_score":58,"escalation":"CRITICAL_EJECT",
 "pricing_source":"SPXW","buyback":3.9,"profit_pct":-680,
 "engine_action":"CLOSE_NOW","user_action":"override_hold","reason_code":"expect_meanrev",
 "hypothesis_ref":"P0-2"}

// resolution (at close or expiry — grades the signal)
{"type":"resolution","pos_id":"...","close_reason":"expired_itm","final_cost":4.24,
 "realized_pl":-1696,"grade":"WRONG","exit_savings":null}
```

This is the key upgrade over the old logs: "did the change work?" becomes a query, not a memory.

---

## METRICS THAT MATTER (and the traps)

Per change and overall:
- **exit_savings distribution** (dollars saved/lost by acting on exit signals) — not just "was it green."
- **Max single-position drawdown / tail loss** — the 5/13 number. A change that improves the average but worsens the tail is a *regression*.
- **Expectancy including the tail** across a sample that contains losing scenarios.
- **Override scorecard** — overrides vs outcomes; who's right when you disagree with the engine.
- **Per-regime / per-archetype breakdown** — so one calm scenario can't "confirm" a change that's dangerous on a trend path.
- **Moat calibration** — predicted moat vs realized adverse move; well-calibrated if breaches occur at roughly the implied frequency.

**Trap to avoid:** win-rate / "we were green." That's the metric that produced the wrong 5/13 lesson.

---

## DEFINITION OF "VALIDATED"

A change is validated when: **T0 green** + **passes its T1 scenarios (including 5/13 if it touches exit/sizing) with no regression on the whipsaw/calm guard scenarios** + (for tuning) **better tail-adjusted behavior across ≥2 archetypes** + **N live sessions with the pre-registered PASS met and no tail regression**. Record the verdict in IMPLEMENTATION_PLAN.md and implementation_progress.md.

---

## WHAT I NEED FROM YOU (v2 — much lighter)

1. **Account size + per-day/per-trade risk budget** → sets the P0-3 governor thresholds and the session header.
2. **Which changes to put under test first** → recommend **P0-2 (EJECT carve-out) + P0-3 (sizing)**, both proven at T1 against the 5/13 keystone.
3. **How many live sessions** before calling a change validated (sets N above).
4. *(Deferred / optional)* data-vendor go-ahead — only if/when we want dollar-accurate P&L backtests. **No broker timestamps needed anymore.**
