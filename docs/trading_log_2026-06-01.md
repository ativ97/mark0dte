# Live Trading Session — 2026-06-01 (Monday) — CHECKPOINT VALIDATION
# Structured capture per docs/VALIDATION_PLAN.md. Goal: validate the 2026-05-29 batch LIVE.
# This is the first live run of P0-1/P0-2/P0-3/P0-5/P0-6/P1-5 + the frontend changes.

## SESSION HEADER
- **Date:** 2026-06-01 (Mon)
- **Changes under test:** P0-2 (regime-conditional EJECT), P0-3 (sizing banner + contracts), P1-5 (ask-side pricing), P0-6 (tracker resolve-on-expiry), P0-1 (EST quarantine).
- **Account size:** $15,000. Sizing guardrail = **informational only** (amber notice ≥25% / $3,750; never blocks).
- **Pre-flight done before trading?** [ ]  (commands in §PRE-FLIGHT below)
- **Regime at open:** _____  | VIX/VIX9D: _____ | GEX: _____

## PRE-FLIGHT (run once before the open)
```bash
cd backend
/Users/ativ.aggarwal/miniconda3/envs/mark/bin/python -m pytest test_engine.py test_positions.py -q   # expect 81 passed
/Users/ativ.aggarwal/miniconda3/envs/mark/bin/python synthetic_replay.py | grep ">>>"                 # GR-0513/0518/0519 PASS, GR-0529 PASS
/Users/ativ.aggarwal/miniconda3/envs/mark/bin/python -m uvicorn main:app --reload                     # boots clean; watch log for "_ensure_schema migration skipped" (should NOT appear)
# In the browser (npm run dev): hard-refresh, add a multi-lot position, confirm the AMBER size banner shows.
```

## PRE-REGISTERED HYPOTHESES (decide pass/fail BEFORE the session)
| # | Change | What to observe live | PASS | FAIL |
|---|--------|----------------------|------|------|
| H1 | **P0-2** | Telemetry now carries `mean_reverting` / `trend_continuation` per position; in positive-GEX dips it reads mean_reverting=true and does NOT force a close; in a negative-GEX/surge trend-through it forces (action ≠ HOLD_* once escalation is URGENT/CRITICAL). | regime fields present + behave per regime | fields missing, or forces in positive-GEX / holds in trend-through |
| H2 | **P0-3** | A multi-lot position shows the amber "Position size: X% of account" banner with the right %; never red/blocks. | banner shows, % correct, informational | banner missing or wrong % |
| H3 | **P1-5** | `estimated_buyback_ask` is closer to your real broker mark than `estimated_buyback` (mid). Log both vs broker at ~3 points. | ask-side closer to broker | no improvement / field missing |
| H4 | **P0-6** | At/after the close, `accuracy_stats.total_resolved` increments and `signal_log.jsonl` gains graded records (not just PENDING). | signals graded at expiry | still 0 resolved / leak |
| H5 | **P0-1** | If ThetaData drops (pricing_source=EST), no escalation is softened to TAKE_PROFIT on a bad estimate. | EST never caps an eject | EST softens an eject |

## DECISION LOG
| time (ET) | SPX | pos | moat | engine action | esc | regime (mr/tc) | broker mark | your decision | reason |
|-----------|-----|-----|------|---------------|-----|----------------|-------------|---------------|--------|
| | | | | | | | | | |

_(append a row each time you paste a snapshot / take action)_

## P1-5 PRICING CHECK (log a few points)
| time | engine mid (estimated_buyback) | engine ask (estimated_buyback_ask) | your broker mark |
|------|--------------------------------|-------------------------------------|------------------|
| | | | |

## EOD REVIEW — fill at close
- **Outcome / realized P&L:** _____
- **H1–H5 verdicts:** _____
- **Signal precision (the key metric):** of the engine's CLOSE/EXIT flags today, how many were on trades that WON vs LOST? (the backtest showed 25 win / 11 lose — did P0-2 reduce the false alarms?)
- **Did P0-2 fire? Was it right?** _____
- **Pricing:** ask-side vs mid vs broker gap: _____
- **Lesson / what to tune next:** _____
