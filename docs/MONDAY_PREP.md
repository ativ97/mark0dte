# Monday Prep — for 2026-06-01
# Created 2026-05-29 EOD. Companions: IMPLEMENTATION_PLAN.md · VALIDATION_PLAN.md · trading_log_2026-05-29.md
# Source of truth for "what shipped, what to verify, how to trade Monday."

---

## 1. WHAT SHIPPED TODAY (validated in-session)

> **Update (batch 2, 2026-05-29 PM):** also shipped **P0-1** (EST quarantine — EST price can't soften an eject), **P0-3** (sizing wiring + `contracts` DB column + a "% of account / over-limit" banner), **P0-5** (expired-ITM P&L, stale-VIX label), **P0-6** (Signal Tracker now resolves on expiry), **P1-5** (ask-side close pricing) + **frontend** (sizing banner, `contracts` entry input, `?? 999` fix). **80 tests + harness green; `app.jsx` esbuild-clean.** Frontend *runtime* is NOT verified here — see §2. Remaining (queued): P1-4 verdict consolidation, P0-7 threshold vol-scaling (needs replay), regime badge, fill-input-on-close.

**P0-2 — regime-conditional EJECT** (`engine.py`, in `evaluate_positions`):
- New gate: `mean_reverting = (gex_regime == "POSITIVE") and not surge` vs `trend_continuation = (gex_regime == "NEGATIVE") or surge`.
- **P0-2a:** outside a mean-reverting regime, the user-facing action can no longer be a `HOLD_*` while the escalation ladder is at URGENT/CRITICAL (fixes the 5/13 action/escalation desync).
- The reversal-downgrade is now **gated to mean-reverting (positive-GEX) regimes only** — so it can't soften a close on a trend-through.
- Two fields added to each position dict: `mean_reverting`, `trend_continuation`.

**P0-3 (partial) — sizing guardrail** (`config.py` + `engine.py`):
- `ACCOUNT_SIZE = 10000`, `MAX_RISK_PER_TRADE = $2,000` (20%, your choice), `MAX_RISK_PER_DAY_PCT = 0.30`.
- `calculate_position_risk(contracts, width, credit, ...)` → max loss, % of account, over-limit flag, max contracts allowed. Unit-tested.

**Validation** (`backend/synthetic_replay.py`):
- **GR-0513** (trend-through, no positive GEX) → **PASS**: forces a non-downgradable URGENT/EJECT at SPX 7426 (~14 pts before the 7440 breach); 0 HOLD-while-critical bars.
- **GR-0529** (positive-GEX bounce, today's regime) → **PASS**: 0 forced exits — holds the bounce, exactly like today.
- **Calm guard** → no false alarms.

**Tests:** `test_engine.py` 50 pass (+2 sizing), `test_positions.py` 26 pass. (`test_main_imports` fails only where `pandas_ta` isn't installed — fine in your `mark` env.)

---

## 2. VERIFY BEFORE MONDAY (run in your `mark` env)

```bash
cd backend
/Users/ativ.aggarwal/miniconda3/envs/mark/bin/python -m pytest test_engine.py test_positions.py -v   # expect all pass
/Users/ativ.aggarwal/miniconda3/envs/mark/bin/python synthetic_replay.py                              # expect GR-0513 PASS, GR-0529 PASS
/Users/ativ.aggarwal/miniconda3/envs/mark/bin/python -m uvicorn main:app --reload                     # confirm telemetry still serves
```

**Wiring note (safe either way):** the two new fields (`mean_reverting`, `trend_continuation`) are returned by `evaluate_positions` but will be **silently dropped** by the `EvaluatedPosition` Pydantic model unless you add them (pitfall #6). The *logic* works regardless. With no GEX data, `mean_reverting=False` → P0-2 behaves conservatively (forces on escalation) — the safe default.

---

## 3. STILL TO SHIP (safe display fixes — NOT done today)

These are the remaining "Monday-ready, no change to close logic" items from the plan:
- **P0-3 UI:** a `contracts` field on positions (DB + entry) + a **"position = X% of account / $Y max loss"** banner using `calculate_position_risk()`. (Engine helper is ready; needs `database.py` + `main.py` + `app.jsx`.)
- **P1-5 pricing:** ask-side close + actual-fill input (`data_fetcher.py` + `app.jsx`).
- **P0-5 quick bugs:** `app.jsx` `p.moat ?? 999`; the inverted "−X pts below recommended" wording; stale-VIX-as-`live`; expired-ITM `credit*9`.

---

## 4. MONDAY TRADING DISCIPLINE (until the UI enforces it)

The engine doesn't yet *enforce* sizing (P0-3 UI is pending), so self-enforce:
- **Per-trade cap: ≤ $2,000 max loss ≈ 4 lots** of a $5-wide spread. Quick check at entry: `contracts × (5 − credit) × 100 ≤ 2000`. (Today's 20 lots = $8,520 = 85% — the thing the whole plan exists to prevent.)
- **Per-day stop:** stand down after ~−$3,000 realized or **2 consecutive losers** — whichever first.
- **Off-ramp, pre-defined:** set your day-low/day-high breach line *before* entry. In the **final hour**, a with-trend short in a **non-positive-GEX** regime = exit. That's now exactly what P0-2 enforces — when it forces, trust it.
- **Trust the regime split:** positive-GEX + oversold/overbought = the bounce is real (hold); negative-GEX or surge or trend-through = don't hold into the close.
- **Capture:** keep pasting snapshots; I'll log to `trading_log_2026-06-01.md`. Note your **actual fills** — the engine's price is the mid and ran $0.05–0.10 off all day (P1-5).

---

## 5. WHAT I NEED FROM YOU

1. Confirm the tests + harness pass in your env (or paste any failures).
2. Want `mean_reverting` / `trend_continuation` exposed in the API + a small UI badge? (one-line schema add)
3. Go-ahead to build the **P0-3 sizing banner + P1-5 ask-side pricing** next (the remaining safe fixes) — these are the highest-value Monday-facing UI items.
4. Optional: a per-day-stop number you want baked into `MAX_RISK_PER_DAY_PCT` (currently 30% suggested).
