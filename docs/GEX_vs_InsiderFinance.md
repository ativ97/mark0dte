# 0DTE Quant Engine vs. InsiderFinance GEX — Comparison & Gap Analysis

_Analysis date: 2026-06-02. Sources: project source (`backend/data_fetcher.py`, `engine.py`, `CLAUDE.md`), a sample `/api/telemetry` response (2026-06-02 12:56 UTC), the InsiderFinance HAR capture (12:34–12:53 UTC), and the live `insiderfinance.io/gamma-exposure/SPX` page._

## TL;DR

These are not really competitors. **InsiderFinance is a broad, read-only options *analytics & visualization* platform** (GEX is one page among flow, congress/insider trades, earnings, news, profit calculator) covering any ticker. **Your project is a narrow, opinionated 0DTE-SPX *decision & risk-management* engine** where GEX is just 1 of 8 smart-moat factors feeding position evaluation, exit escalation, and signal grading.

InsiderFinance wins on **GEX breadth and visualization** (all-expiration aggregation, zero-gamma/flip level, max pain, gamma-by-expiry, gamma price profile, intraday ΔGEX, squeeze screener, native SPX). Your project wins on **the decision layer** — it tells you what to *do* with a live position, and it grades its own accuracy. The single most useful thing to borrow from them is the **zero-gamma flip level**.

---

## 1. What each tool actually is

| | **Your 0DTE Quant Engine** | **InsiderFinance GEX page** |
|---|---|---|
| Core purpose | Manage live 0DTE SPX credit-spread positions: regime, moat sizing, exit signals | Visualize options positioning for any ticker |
| Output | Recommendations, escalation, exit grades, P&L, signal scorecard | Charts, tables, levels, screeners (read-only) |
| Scope | SPX, 0DTE only, one strategy | Any ticker, all expirations, strategy-agnostic |
| GEX role | 1 of 8 multiplicative smart-moat factors | The whole product on that page |
| Access / cost | Your own backend (ThetaData + Yahoo + Alpaca) | Public/free GEX page; ~$55/mo for flow/full suite |
| Refresh | 30s telemetry poll, 120s GEX cache | ~90s poll, payload ~2 min stale |

---

## 2. GEX methodology — the numbers don't line up, and here's why

Your sample response and InsiderFinance, captured minutes apart on the same day, disagree on the **sign** of net GEX:

- **Your engine:** `net_gex = -103.6M` → **NEGATIVE** (trending/volatile, dealer short gamma)
- **InsiderFinance:** `Net GEX = +$4.3B` (live) / `+$46.9B` (HAR snapshot) → **POSITIVE** (vol-suppressing)

That is not a bug on either side — they are measuring different things:

**(a) Expiration scope is the big one.** Your engine fetches `expiration = today` only (0DTE). InsiderFinance defaults to **All Expirations** (54 of them, strikes 2200–20000, 28k contracts). On their own page, 0DTE is only **~0.2%** of total gamma; weekly ~1.8%, monthly ~11.5%. So their headline GEX is ~99.8% driven by dated/LEAP positioning that is irrelevant to a 0DTE trader. Their far-dated calls dominate → large positive; your 0DTE-only slice has put gamma dominating near spot → negative. **For your use case, the 0DTE-only number is the *correct* one** — but you should know it will routinely disagree with public "SPX GEX is positive" dashboards.

**(b) Units/normalization differ.** Your GEX = `gamma × OI × 100 × spot` (≈10^8 scale). The standard "dollar-gamma" used by InsiderFinance is effectively `gamma × OI × 100 × spot² × 0.01` (dollar gamma per 1% move), which is why theirs is in the **billions**. The two net numbers are not comparable in magnitude either, even on the same expiration.

**(c) Gamma source.** They get per-contract `gamma` directly from their data vendor. You compute Black-Scholes gamma yourself from IV+delta (`_bs_gamma`, `r=0.05` hardcoded, `t_years` from wall-clock hours-to-close). That's reasonable but adds a small modeling error they don't carry.

**(d) Wall definitions differ.** Your `call_wall`/`put_wall` are **gamma-weighted** (max call GEX / most-negative GEX strike); InsiderFinance's call/put walls are **open-interest-based**, and their "Peak GEX strike" is the gamma magnet (your closest analog is `gamma_wall_spx`). So "call wall" literally means different strikes on each tool.

**(e) Underlying.** You use **SPY × ratio** as an SPX proxy (your own pitfalls #13/#22 flag ratio drift ≈7.5 pts at this level — material when the gamma-trap threshold is 10 pts). InsiderFinance uses **native SPX options**, no conversion.

---

## 3. GEX features InsiderFinance has that you don't

Ranked by value to a 0DTE credit-spread trader:

1. **Zero-gamma / flip level** (e.g. $7569). The price where net gamma crosses zero — the boundary between your POSITIVE and NEGATIVE regimes. You currently classify regime by the *sign of net GEX* with a hysteresis deadband; a real flip level is the more principled version of the same idea and a tradeable line. **Highest-value add.**
2. **Per-expiration filter + gamma-by-expiry** (0DTE / weekly / monthly / all). Lets you see how much of a level is 0DTE-anchored (i.e. evaporates at the close) vs. structural.
3. **Intraday ΔGEX** (session + recent change). Detects dealer *repositioning* during the day — a genuine 0DTE edge. You already have the telemetry ring buffer to compute this.
4. **Gamma price profile** — net gamma projected across a range of prices (a curve, not just walls). Would make your "magnet" and moat logic visual and defensible.
5. **Max pain** and **Put/Call ratio + Call/Put OI totals** — cheap to compute from the chain you already pull.
6. **Gamma squeeze screener** with a 0–100 probability score (gamma regime, call-wall proximity, flow alignment, volume, DEX bias).
7. **Native SPX**, multi-asset, and a much richer chart/heatmap UI.

---

## 4. What your engine does that InsiderFinance can't

InsiderFinance shows you data; it never tells you what to do with a position you're holding. Your engine's entire reason to exist is the decision layer:

- **Position lifecycle management** — per-position moat, exit strategy, reversal scoring, graduated escalation (CAUTION → … → CRITICAL_EJECT), profit-aware caps, and the P0-2 regime-conditional EJECT tuned from real losses.
- **Multi-signal regime engine** — CHOP/ER/RSI/EMA → STATE A/B/C, not GEX alone.
- **Expected-move moat sizing** — VIX/VIX9D → recommended moat, move-consumed logic. (Nothing on IF sizes a spread for you.)
- **Smart moat = 8 multiplicative factors** — GEX is one input, contextualized by range, signal quality, time decay, events, etc.
- **Signal Outcome Tracker** — dollar-valued self-grading (CORRECT / JUSTIFIED / PREMATURE / WRONG). You measure whether your own calls made money; IF has no feedback loop.
- **Side-aware mean-reversion gating** — GEX only counts as protection if the wall sits between spot and your short strike (pitfall #22). A nuance IF's generic page can't express.
- **Magnet forces, RSI-50 price, portfolio heat, live SPXW spread pricing, trade proposals, intraday P&L** — all strategy-specific.

In short: **breadth + visualization (IF) vs. depth + automation (you).**

---

## 5. Recommendations

**High value, low effort (you already fetch the data):**

- Add a **zero-gamma flip level** and surface it as a key level; consider basing the POSITIVE/NEGATIVE regime on spot-vs-flip rather than raw net sign.
- Add **max pain** and **P/C ratio** to `fetch_gex_data` output.
- Either compute an **all-expiration (or 0DTE+weekly) GEX aggregate** alongside the 0DTE number, **or explicitly label yours "0DTE GEX"** so it isn't confused with public dashboards — and note in the UI *why* it can read negative when "SPX GEX" reads positive.

**Medium effort, real edge:**

- **Intraday ΔGEX** from your existing telemetry ring buffer (diff `net_gex` and wall positions across the session) — arguably more useful for 0DTE than the static snapshot.
- A **gamma price profile** curve to back the magnet/moat logic.

**Structural:**

- Move GEX off the **SPY proxy** to the **SPXW chain** you already price spreads against — eliminates the ratio-drift error your own notes flag, and makes walls land on real SPX strikes.
- Document the **dollar-gamma normalization** (×spot²×0.01) so your `net_gex` is comparable to public GEX, or keep your scale but label the unit.

**Don't copy:** their all-expiration default headline, the broad multi-asset/flow/congress surface area — none of it serves a single-strategy 0DTE SPX engine, and chasing it would dilute the decision layer that is your actual advantage.

---

## 6. Data-quality notes

- Latency is comparable: IF payload ~2 min stale, polled ~90s; your GEX cache is 120s.
- IF's gamma is vendor-supplied; yours is BS-modeled from IV — a small extra assumption, watch the hardcoded `r=0.05` and the hours-to-close `t_years`.
- IF's all-expiration walls swung hard between the two same-day snapshots ($7600/$7570 → $7650/$7400), a reminder that aggregate walls are noisy; your 0DTE walls are tighter and more session-relevant.
