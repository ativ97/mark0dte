# Goals & Metrics — 0DTE Quant Engine
# Created 2026-05-29. Not financial advice — a framework; you set the actual numbers.
# Companion: VALIDATION_PLAN.md (how changes are proven) · trading_log_*.md (daily capture).

## CORE PRINCIPLE
**Set goals you control (risk, process, sample), not P&L targets you don't.** P&L is the lagging
output. Targeting a dollar number is what drives oversizing and holding losers — the 5/13 / 5/19
behavior. Control the inputs; let the dollars follow *if* the edge is real.

## WHY WE DON'T FORECAST P&L (yet)
From the 16-day backtest: mean **+$360/day**, but **std $1,068 (~3× the mean)** and the **95% CI on
the daily edge is −$107 to +$827 — it straddles zero.** 2 down days erased 72% of the month's profit,
and the in-sample worst day (−$2,793) is *not* the worst possible (gross single-leg losses hit −$5k–$11k;
offsets cushioned the net). Translation: **16 days can't even confirm the edge is positive, let alone
predict a monthly/annual number.** A naive ×252 ("$90k/yr") is false precision that would push you to
oversize. Real expectancy needs a much larger, out-of-sample sample that has survived a true tail day.

---

## 1. RISK GOALS (hard, pass/fail — the real targets) — CONFIRM YOUR NUMBERS
| Metric | Target (placeholder — set yours) | Action if breached |
|--------|----------------------------------|--------------------|
| Per-trade max loss | amber notice ≥ **25% / $3,750** of the $15k account (informational today) | reconsider size before entering |
| Personal hard ceiling per trade | **decide a number you will not cross** (e.g. 40% / $6,000) | do not open beyond it, period |
| Per-day stop | stand down after **2 consecutive losers** or **−$1,500 (~10%) on the day** | stop trading that day |
| Drawdown circuit-breaker | account **−15% from peak** | halt, full review before resuming |
| Add-to-loser | **never** | if tempted, close instead |

## 2. PROCESS GOALS (daily, controllable)
- [ ] Capture the session in `trading_log_YYYY-MM-DD.md` (structured, every decision).
- [ ] Pre-register what's "under test" + max risk budget before the open.
- [ ] Don't override the regime gate: in a **trend-continuation** (negative-GEX / surge) regime, take the forced exit.
- [ ] Log actual fills (for the P1-5 mid-vs-real pricing check).

## 3. VALIDATION GOALS (these set the timeline; the gate to sizing up)
Tracked **out-of-sample** (Monday forward — NOT the 16 days we built on):
1. **Sample:** ≥ **~50 graded trades** before re-estimating expectancy seriously (≥100 to trust it).
2. **Edge confirmed:** out-of-sample mean P&L > 0 **with the 95% CI lower bound also > 0** (CI clears zero).
3. **Tail survived:** ≥ **1 genuine trend-through day** survived with caps intact (max loss ≤ ceiling, per-day stop honored).
4. **Engine precision up:** the false-alarm rate (EXIT flagged but trade won) falls vs the **25/36** baseline.
5. **Only after 1–4:** consider sizing up. Until then, size stays capped.

## 4. REVIEW CADENCE
- **Daily:** log + EOD grade (template already in each `trading_log`).
- **Weekly:** aggregate — win rate, mean/day, worst day, **did the caps hold?**, drawdown, trades-to-date.
- **Monthly:** re-estimate expectancy + its CI on the growing sample; decide whether the size gate (3.5) is met.

## 5. REALISTIC TIMELINE
- **Next ~1–2 months = VALIDATION phase, not a profit phase.** The honest goal is *"N trades captured,
  caps never breached, edge confirmed out-of-sample, one tail day survived"* — **not** "$X by December."
- A year-end P&L target is deliberately **not** set; with a CI that straddles zero, it would be a guess that
  rewards risk-taking. The dollars are the *output* of hitting the controllable goals above.

---

## DEFERRED — Expectancy Scorecard (build after ~50 graded trades exist)
A panel/endpoint off the Signal Tracker (P0-6) that reports, on the accumulated out-of-sample sample:
rolling **expectancy ($/trade) with its 95% CI**, win rate, profit factor, worst day, max drawdown,
and a green/red flag for **"CI cleared zero?"** (the size-up gate from §3.2). Not built now — it has no
data to compute until the sample accumulates, and we're holding new code until the Monday checkpoint is
validated live. Spec is here so it's ready when the data is.
