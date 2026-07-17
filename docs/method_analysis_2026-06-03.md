# What's Worked — and How to Improve Without Over/Underfitting
**Date:** 2026-06-03 · companion to `trading_log_2026-06-03.md` and the edge analysis (`edge_analysis.py`)

This is the strategic read the build serves. It separates two questions that keep getting tangled:
**(A) is there an edge, and what is it?** and **(B) how do we improve the tool around that edge without fooling ourselves?**

---

## 1. What has actually worked (evidence, not vibes)

**The data-driven method is the edge.** Splitting the Robinhood history at 5/20 (when GEX/RSI/EMA decision-making began):

| Era | Days | Net P&L | Win days | Worst day |
|-----|------|---------|----------|-----------|
| Discretionary (5/11–5/19) | 7 | **−$725** | 4/7 (57%) | −$1,320 (ITM settle) |
| Data-driven (5/20–6/2) | 9 | **+$12,093** | **9/9 (100%)** | +$515 |

The regime change in results lines up exactly with the method change. Both realized losses predate it. This is real signal, not noise — a 9-day, +$12k, zero-down-day stretch is not what a coin flip looks like.

**Engine components validated live (2026-06-03):**
- **H2 cry-wolf gate** — CLOSE/DRIFT recs fired only on genuinely at-risk legs, stayed quiet on winners price was moving away from. The single most useful fix; it makes the exit flags trustworthy.
- **H7 / P0-2 force-path** — fired correctly the first time a real negative-GEX trend-through appeared (the 5/13 configuration). Proven to *fire*; not yet proven to *save* (the user overrode it and a bounce bailed the book).
- **H1 single-source, H4 hysteresis, H5 RED-while-profit** — all behaved as designed.
- **Exit discipline** — the user closed green on both the trend-through and the chop; turned a −$5k intraday (5/19) into −$798 realized. Exits are a genuine skill here.

**The honest counterweight:** the edge is **high-win-rate, negative-skew premium selling** (81% win, win/loss size ratio ~1.4, realized skew −0.5 even in this sample). A high win rate is *exactly* what makes a streak feel like certainty — right until the tail. The data-driven era has logged **zero tail days**, so it cannot yet distinguish "the method removed the tail" from "the tail hasn't shown up." And lot size **tripled (10→30)** over the streak, so the eventual tail day is now 3× as costly. **Edge is real; durability depends on size.**

---

## 2. The over/underfitting problem, stated plainly

The engine is a model of "is this a safe place to sell premium?" Like any model:

- **Overfitting** = tuning it to the recent winning tape so it looks great in-sample and fails live. Symptoms here: nudging thresholds because the last 9 days won; stacking more multiplicative moat factors (already **8**: range × signal × time × exhaustion × event × GEX × move-consumed × IB-breakout — each tuned on thin data, and they compound); trusting `AVG_WIN_DAY_REFERENCE` or the magnet touch-% as if calibrated; reacting to single days.
- **Underfitting** = so smoothed/generic it misses real regime shifts. Symptoms: hysteresis deadbands set so wide they swallow a true trend-through; treating every negative-GEX day identically; ignoring the flip/ΔGEX signal entirely.

We have been **closer to the overfitting edge** (8 stacked factors, lots of heuristics) than the underfitting one. The discipline below is mostly about *resisting the urge to add and tune*.

---

## 3. How to improve without over/underfitting — the discipline

**1. Freeze the core during validation.** Do **not** retune the regime gate, escalation ladder, smart-moat factors, or P0-2 logic to make the winning days look better. Changing parameters to fit observed outcomes is the definition of overfitting and it invalidates the out-of-sample test. (This is exactly why no code logic was changed mid-session today — only bug fixes and additive read-outs.)

**2. Pre-register and measure out-of-sample.** The H1–H8 hypothesis logs already do this — decide PASS/FAIL *before* the day. Keep it. The next milestone is **~30–50 data-era trades at a FIXED 10-lot size**, logged with the setup recorded before the outcome, then compute **expectancy** (not win rate): `E = win% × avg_win − loss% × avg_loss`. Win rate is the seductive-but-useless metric for a negative-skew strategy; expectancy and the **size/frequency of the worst losses** are the whole question.

**3. Separate the edge from the size — they need different evidence.** The *edge* (regime read, entry quality) can be validated on ~30–50 trades. The *tail* (how bad a gap/ITM day is) is a rare event you cannot average away — you size for it a priori. Today's `tail_day_preview` exists precisely so the rare event is always visible before it happens. **Keep sizing a hard, separate discipline (≤ the amber line), not something the win streak is allowed to relax.**

**4. Prefer pruning to adding.** Before adding a 9th moat factor, ask which of the 8 is actually carrying weight out-of-sample. A simpler model with fewer tuned knobs generalizes better. The Signal Outcome Tracker (once it has ~50 graded signals) can tell us which signals have real predictive value and which are dead weight — *then* prune.

**5. Bias–variance, concretely.** More factors / tighter tuning = lower bias, higher variance (overfit, brittle live). Fewer factors / wider deadbands = higher bias, lower variance (underfit, sluggish). The right complexity is whatever the *data volume* justifies — and right now that volume is small (16 days total, 9 data-era). So: **earn each parameter.** Don't wire the flip or `trend_dominant` into the core regime gate until the ΔGEX/flip read has been watched live for a stretch and shown to lead, not lag.

**6. Capture the tail when it comes.** The most informative day ahead is the first **data-era losing day** — especially a gap or ITM-settlement day. That single observation tells us more about the strategy's true expectancy than ten more green days. Log it in full.

---

## 4. What the three shipped changes do for this

- **Tail-day preview** — makes the one variable that actually threatens the account (size → tail severity) impossible to miss, in $, % of account, and "good days erased." Directly attacks the documented #1 leak.
- **Contract-weighted P&L** — you can't manage what you mis-measure; the scoreboard is now correct.
- **ΔGEX velocity / distance-to-zero** — a *measured* regime-change read to replace the broken flip heuristic, and a candidate leading indicator to validate (not yet trust). The flip itself is now correct-or-silent (enforces spot>flip ⟺ net_gex>0).

None of these change the trading logic — they improve *measurement and visibility*, which is the safe way to improve a model when you don't yet have enough data to retune it.

---

## 5. The one-line version
**The edge is real and it's the data-driven method; the risk is real and it's size; the discipline is to keep measuring out-of-sample and resist tuning the engine to a 9-day winning streak.**
