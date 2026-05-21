# 0DTE Quant Engine — User Manual

**A practical guide to reading the dashboard, understanding every indicator, and making trading decisions.**

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [The 30-Second Glance — What to Check First](#2-the-30-second-glance)
3. [Dashboard Layout (Top to Bottom)](#3-dashboard-layout)
4. [Panel-by-Panel Deep Dive](#4-panel-by-panel-deep-dive)
   - [4.1 Header Bar](#41-header-bar)
   - [4.2 Watch Levels (Ceiling & Floor)](#42-watch-levels)
   - [4.3 Action Required Alerts](#43-action-required-alerts)
   - [4.4 Algorithmic Directives](#44-algorithmic-directives)
   - [4.5 VIX & Expected Move](#45-vix--expected-move)
   - [4.6 GEX (Gamma Exposure)](#46-gex-gamma-exposure)
   - [4.7 Day P/L Dashboard](#47-day-pl-dashboard)
   - [4.8 Position Summary (Iron Condor View)](#48-position-summary)
   - [4.9 Position Cards](#49-position-cards)
   - [4.10 Trade Ideas (Auto-Proposals)](#410-trade-ideas)
   - [4.11 Market Watch & Opportunities](#411-market-watch)
5. [The Indicators — What Each One Means](#5-the-indicators)
6. [Decision Flowchart — When to Act](#6-decision-flowchart)
7. [The Zone System (SAFE → GAMMA TRAP)](#7-the-zone-system)
8. [Exit Strategy Actions Explained](#8-exit-strategy-actions)
9. [Escalation Levels](#9-escalation-levels)
10. [Time of Day — How It Changes Everything](#10-time-of-day)
11. [Common Scenarios & What To Do](#11-common-scenarios)
12. [Glossary](#12-glossary)

---

## 1. What This System Does

This is a **decision-support dashboard** for selling 0DTE (zero days to expiration) SPX credit spreads. It does NOT auto-trade. You open positions on your broker (e.g., Robinhood), enter them here, and the system monitors them in real-time, telling you:

- **When your positions are safe** (let theta decay work)
- **When to pay attention** (market moving toward your strike)
- **When to close** (with specific prices and timeframes)
- **What new trades to consider** (auto-proposed candidates)

The system refreshes every **30 seconds** automatically.

---

## 2. The 30-Second Glance

When you open the dashboard, check these **in this order** (takes 30 seconds):

| Priority | What to Check | Where | What You're Looking For |
|----------|--------------|-------|------------------------|
| **1st** | 🔴 Red "ACTION REQUIRED" banner | Top of page | Any flashing red = act NOW |
| **2nd** | Position colors | Position cards | All green = relax. Any red/amber = read the message |
| **3rd** | Market State | Algorithmic Directives | State A = good. State C = dangerous |
| **4th** | Time remaining | Top-right of directives | < 1 hour = theta is your friend |
| **5th** | Day P/L | Above positions | Running total of your day |

**If everything is green and State A/B with > 2 hours left → you can check back in 10-15 minutes.**

---

## 3. Dashboard Layout

The dashboard has two main columns on wide screens:

```
┌─────────────────────────────────────────────────────┐
│  HEADER: SPX price, SPY price, range bar            │
├──────────────────────┬──────────────────────────────┤
│  LEFT COLUMN         │  RIGHT COLUMN                │
│  ─────────────       │  ─────────────               │
│  Watch Levels        │  Smart Ledger (Positions)    │
│  Alert Strip         │   ├─ Day P/L                 │
│  Algo Directives     │   ├─ Position Summary        │
│  VIX Expected Move   │   ├─ Position Cards          │
│  GEX Panel           │   └─ Add Position Form       │
├──────────────────────┴──────────────────────────────┤
│  FULL-WIDTH SECTIONS                                │
│  Trade Ideas (auto-proposals)                       │
│  Market Watch & Opportunities                       │
│  Detailed Recommendations                           │
└─────────────────────────────────────────────────────┘
```

---

## 4. Panel-by-Panel Deep Dive

### 4.1 Header Bar

The top bar shows:

- **SPX Price**: The current estimated S&P 500 index level (derived from SPY × 10). This is what your option strikes are measured against.
- **SPY Price**: Live Alpaca feed price for SPY ETF.
- **Range Bar**: A colored bar showing where SPX currently sits within today's high-low range. 50% = middle of the day's range.
  - **Why it matters**: If you sold a put spread and the range bar is pinned to the left (near day low), SPX is at its lowest point today — your put side is under pressure.

### 4.2 Watch Levels (Ceiling & Floor)

Two boxes showing the **nearest danger levels** for your positions:

- **▲ CEILING**: The closest call spread strike that SPX could threaten if it moves up.
- **▼ FLOOR**: The closest put spread strike that SPX could threaten if it moves down.

**Color coding:**
- **Red background** = a position is in the Gamma Trap zone (≤ 10 pts from strike). Act immediately.
- **Amber background** = a position is in the Warning zone (≤ 25 pts). Pay close attention.
- **Dark/neutral** = all positions are safely distant.

**The number shown is the SPX price level** where your nearest strike sits. The distance in points is shown below it.

> **Example**: Floor shows "5850" with "50 pts below" → your nearest put spread is at 5850, and SPX is currently at 5900. You have 50 points of buffer. That's healthy.

### 4.3 Action Required Alerts

A **red flashing banner** that appears ONLY when immediate action is needed. If you see this, read it first.

Each alert shows:
- **Category**: CLOSE, EJECT, ADJUST, etc.
- **Message**: What to do and why.

**If this banner is not visible → no immediate action is required.**

### 4.4 Algorithmic Directives

This is the **brain of the system**. It tells you the current market environment:

#### Market State (A / B / C)

| State | What It Means | Your Approach |
|-------|---------------|---------------|
| **State A** (Score 0-1) | Clean trend. Market moving in one direction smoothly. | Best environment for credit spreads. Sell on the opposite side of the trend. Tight moats OK. |
| **State B** (Score 2) | Moderate chop. Mixed signals. | Be careful. Wider moats needed. Use neutral iron condors. |
| **State C** (Score 3-4) | High entropy / whipsaw. Market chopping violently in both directions. | Most dangerous. Widest moats. Only sell if moat is huge. Consider sitting out. |

The score is computed from 4 technical indicators:
- **EMA Compression**: Moving averages squeezing together (chop signal)
- **RSI Dead Zone**: RSI stuck in the middle (no momentum)
- **Choppiness Index**: Direct measure of price path efficiency
- **Efficiency Ratio**: How much of price movement is directional vs noise

**Binary score** (0-4): How many indicators are flagging chop.
**Continuous score** (0.0-4.0): More precise, weighted version.

#### Smart Moat

The **recommended minimum distance** (in SPX points) between SPX and your strikes.

- Shows the current recommended moat value (e.g., "42 pts")
- Shows the base value from VIX math and what adjustments were applied
- **Adjustment factors displayed**: Range (day's trading range), Signal (trend quality), Time (hours left), Events (FOMC/CPI etc.), GEX (gamma exposure)

> **Rule of thumb**: If your position's moat is ABOVE the smart moat → you're safe. If BELOW → pay attention to the CAUTION/WARNING message.

#### Directional Bias

Which direction SPX is trending:
- **BULLISH / LEAN BULLISH**: SPX trending up → put spreads are safer, call spreads are riskier
- **BEARISH / LEAN BEARISH**: SPX trending down → call spreads are safer, put spreads are riskier
- **NEUTRAL**: No clear direction

#### Regime Transition

Predicts whether the market state is about to change:
- **IMPROVING**: Chop is resolving → better conditions ahead
- **FIRMING**: Trend strengthening
- **STABLE**: No change expected
- **SOFTENING**: Trend weakening → conditions deteriorating
- **DETERIORATING**: Chop increasing rapidly → widen moats or close positions

#### Trading Window

The current time of day's classification:
- **Trend Establishment** (10:00-11:30): Best time to enter new positions
- **Lunch Lull** (11:30-1:00): Low volatility, safe to hold
- **Power Hour** (3:00-3:45): Dangerous for new entries, but theta accelerates
- **Final Minutes** (3:45-4:00): Don't do anything. Let theta work.

### 4.5 VIX & Expected Move

Shows the **math-based expected range** for SPX today:

- **Expected Move**: How many points SPX is expected to move, based on VIX and time remaining.
- **1-sigma (68%)**: SPX has a 68% chance of staying within this range.
- **2-sigma (95%)**: 95% chance of staying within this range.
- **Recommended Moat**: The system's suggested minimum moat based on this math.

#### Realized Distribution ("Reality Check")

Below the expected move, you may see a section showing **what actually happened** in the last 120 trading days:

- Shows what percentage of days SPX moved more than ±0.5%, ±1.0%, ±1.5%, ±2.0%
- **Why it matters**: If VIX says "expected move = 30 pts" but 45% of recent days moved > 0.5% (≈30 pts at SPX 5900), the actual risk may be higher than VIX implies.

### 4.6 GEX (Gamma Exposure)

Shows where market makers have concentrated options positions:

- **Net GEX Regime** (POSITIVE / NEUTRAL / NEGATIVE):
  - **POSITIVE**: Dealers are long gamma → market tends to mean-revert. Ranges hold. Good for credit spreads.
  - **NEGATIVE**: Dealers are short gamma → market trends harder, breakouts stick. Dangerous. Wider moats needed.

- **Gamma Wall**: The price level with the highest dealer gamma. SPX is magnetically attracted to this level.
- **Put Wall**: Highest put-side gamma. Acts as a support/floor.
- **Call Wall**: Highest call-side gamma. Acts as a resistance/ceiling.

> **How to use**: If you sold a put spread at 5850 and the Put Wall is at 5860, dealers will likely defend 5860 → your 5850 has extra protection. If the Put Wall is at 5840 (below your strike), you have less protection.

### 4.7 Day P/L Dashboard

Shows your **running profit/loss for the entire day**:

- **Closed P/L**: Realized profit/loss from positions you've already closed today. (Count) = number of closed positions.
- **Open P/L**: Estimated unrealized P/L from positions still open. Based on estimated buyback cost.
- **Total P/L**: Combined closed + open.

**Green** = profitable. **Red** = losing.

> When you close a position using the ✓ button, you'll be prompted for the close price. Enter it to track accurate P/L. Leave blank to skip.

### 4.8 Position Summary (Iron Condor View)

If you have both put and call spreads open, this shows the aggregate view:

- **Structure**: IRON_CONDOR, PUT_HEAVY, CALL_HEAVY, etc.
- **Safe Corridor**: The SPX range where ALL your positions are safe.
- **Total Credit**: Sum of all credits collected.
- **Risk Tilt**: Whether your exposure is balanced or skewed to one side.
- **Est. P/L**: Combined estimated P/L across all open positions.

### 4.9 Position Cards

Each open position gets a card showing:

#### The Moat Bar
A horizontal colored bar showing how much buffer you have:
- **Green (long bar)**: Safe. Large moat. Let theta work.
- **Amber (medium bar)**: Caution/Warning zone. Read the message carefully.
- **Red (short/no bar)**: Gamma trap or strike breached. Act immediately.

The number next to it (e.g., "+65.0 pts") is the exact distance in SPX points.

#### Status Message
A text message explaining the current situation. Examples:
- "SAFE: Theta Decay Active" → Do nothing
- "CAUTION: Moat 8 pts below recommended minimum (42 pts)" → Monitor more frequently
- "WARNING: Trend pushing toward strike" → Prepare to close
- "CRITICAL EJECT" → Close immediately

#### Exit Strategy Box
Color-coded instruction box:
- **Green**: HOLD / LET_EXPIRE — do nothing, let theta work
- **Blue**: HOLD_WITH_TRIGGER — hold but watch for a specific trigger
- **Amber**: CLOSE_SOON / CLOSE_RECOMMENDED — prepare to close, here's the target price
- **Red**: CLOSE_NOW / URGENT_CLOSE / CRITICAL_EJECT — close immediately

The box shows:
- **Action**: What to do (HOLD, CLOSE_SOON, CLOSE_NOW, etc.)
- **Est. @$X.XX**: Estimated price to close at
- **Xmin window**: How long to monitor before acting
- **Signal age/stability**: How long the system has been recommending this action (STABLE = confirmed)
- **Escalation level badge**: For danger zones, shows how urgent (see §9)

#### Badges on Position Cards

- **Breakeven touches** (yellow, pulsing): Position was losing money, then recovered to breakeven. Each touch is an exit opportunity. More touches = stronger close signal.
- **↗ DRIFT +Xpts**: SPX has been slowly but steadily drifting toward this strike over the last 90 minutes. A subtle warning that the position is getting less safe over time, even if the moat still looks OK.
- **Premium trend** (tiny bar below exit strategy): Shows whether the estimated buyback cost is RISING (bad — position getting more expensive to close), FALLING (good — decaying), STABLE, or VOLATILE.

#### Position Action Buttons
- **Number badge** (e.g., "3"): Number of recommendations for this position. Click to expand.
- **✓ (green)**: Close and archive the position. Prompts for close price for P/L tracking.
- **✕ (red)**: Delete position (for mistakes only — NOT archived).

### 4.10 Trade Ideas (Auto-Proposals)

When conditions allow, the system auto-proposes new position candidates:

Each card shows:
- **Type & Strike**: e.g., "Put Spread @ 5850"
- **Score/100**: Higher = better entry. Based on moat quality, day range safety, regime alignment, time, GEX.
- **Verdict**: STRONG_ENTRY (great) or ACCEPTABLE (decent)
- **Est. credit**: Rough estimate of premium you'd collect
- **Moat**: Distance from current SPX
- **Reasons for/against**: Key factors

> **These are suggestions, not orders.** Always verify the actual premium on your broker before entering. The estimated credits are rough models.

**Proposals only appear when:**
- More than 1 hour until market close
- Candidates score ACCEPTABLE or better

### 4.11 Market Watch & Opportunities

Collapsible section with lower-priority market observations:
- WATCH: Things to keep an eye on
- OPPORTUNITY: Potential favorable conditions
- ADJUST: Suggestions to rebalance

These are informational — no immediate action required.

---

## 5. The Indicators — What Each One Means

### Price & Range Indicators

| Indicator | Where Shown | What It Means | When to Care |
|-----------|-------------|---------------|--------------|
| **SPX Price** | Header | Current S&P 500 level | Always — this is what your strikes are measured against |
| **Range Position** | Header bar | Where SPX sits in today's high-low range (0-100%) | When it's extreme (< 20% or > 80%) — means SPX is pressing a day extreme |
| **Day High/Low** | Header | Today's SPX extremes | When they're close to your strikes |

### Regime Indicators

| Indicator | Where Shown | What It Means | When to Care |
|-----------|-------------|---------------|--------------|
| **Regime State** (A/B/C) | Algo Directives | Market environment quality | Always — determines your strategy |
| **Binary Score** (0-4) | Below state | How many chop signals are firing | State C (3-4) = max caution |
| **Continuous Score** (0.0-4.0) | Below state | Granular chop measurement | > 2.5 = high entropy |
| **Directional Bias** | Algo Directives | Which way SPX is trending | When deciding which side to sell |
| **Regime Transition** | Algo Directives | Is the regime about to change? | DETERIORATING = brace yourself |
| **Trading Window** | Algo Directives | Time-of-day classification | When entering new trades |

### Volatility Indicators

| Indicator | Where Shown | What It Means | When to Care |
|-----------|-------------|---------------|--------------|
| **VIX** | Expected Move panel | Market's implied volatility (fear gauge) | Higher VIX = wider moats needed |
| **Expected Move** (1σ, 2σ) | Expected Move panel | How far SPX might move today | Compare to your moat |
| **Realized Distribution** | Below expected move | What actually happened historically | Sanity-check the VIX math |

### GEX Indicators

| Indicator | Where Shown | What It Means | When to Care |
|-----------|-------------|---------------|--------------|
| **Net GEX Regime** | GEX panel | Dealer positioning environment | NEGATIVE = dangerous |
| **Gamma Wall** | GEX panel | Price magnet level | When SPX is near it |
| **Put/Call Wall** | GEX panel | Support/resistance from dealers | When your strikes are near them |

### Position-Specific Indicators

| Indicator | Where Shown | What It Means | When to Care |
|-----------|-------------|---------------|--------------|
| **Moat** (pts) | Position card | Distance from SPX to your strike | Always — this is your safety margin |
| **Moat bar** | Position card | Visual moat gauge (green/amber/red) | Glance-check — color tells the story |
| **Exit Strategy** | Position card | What to do with this position | When it's not green/HOLD |
| **Breakeven touches** | Yellow badge | Position recovered from loss to breakeven | Each touch = exit opportunity |
| **Drift alert** | Orange badge | SPX slowly moving toward strike | Subtle warning — moat is eroding |
| **Premium trend** | Below exit strategy | Is buyback cost rising or falling? | RISING = position getting worse |
| **Escalation level** | Badge in exit strategy | How urgent is the close signal | WARNING+ = pay attention |

---

## 6. Decision Flowchart — When to Act

```
START: Open dashboard
  │
  ├─ Is there a red "ACTION REQUIRED" banner?
  │   ├─ YES → Read it. Follow the instruction. Close the position.
  │   └─ NO ↓
  │
  ├─ Are any position cards red?
  │   ├─ YES → Read the exit strategy. Likely CLOSE_NOW or CLOSE_SOON.
  │   └─ NO ↓
  │
  ├─ Are any position cards amber?
  │   ├─ YES → Read the message. Is it WARNING or CAUTION?
  │   │   ├─ WARNING → Set alerts on your broker. Prepare to close.
  │   │   │   Check the exit strategy for specific prices/triggers.
  │   │   └─ CAUTION → Monitor more frequently. Check back in 5 min.
  │   └─ NO ↓
  │
  ├─ All positions green?
  │   ├─ YES → Relax. Check regime transition (is it DETERIORATING?)
  │   │   ├─ DETERIORATING → Check back in 5 min
  │   │   └─ STABLE/IMPROVING → Check back in 10-15 min
  │   └─ NO → Something unexpected. Read all messages.
  │
  ├─ Want to enter a new trade?
  │   ├─ Check "Trade Ideas" panel for auto-proposals
  │   ├─ Check Trading Window (is entry quality > 50?)
  │   ├─ Check Regime State (A is best, C is worst)
  │   ├─ Check Directional Bias (sell opposite side)
  │   └─ Use "Pre-Trade Analysis" on your broker's strike
  │
  └─ END: Come back in 5-15 minutes
```

---

## 7. The Zone System (SAFE → GAMMA TRAP)

Every position is classified into a zone based on its moat:

```
SAFE                    CAUTION              WARNING           GAMMA TRAP
(> smart moat)          (< smart moat)       (≤ 25 pts)        (≤ 10 pts)
┌─────────────────────┬─────────────────┬─────────────────┬──────────────┐
│ ■■■■■■■■■■■■■■■■■■  │ ■■■■■■■■■■■■    │ ■■■■■■■■        │ ■■■■         │
│ GREEN                │ AMBER           │ AMBER           │ RED          │
│ Let theta work       │ Monitor closely │ Prepare to close│ CLOSE NOW    │
│ Check back in 15 min │ Check in 5 min  │ Watch every     │ Act within   │
│                      │                 │ refresh (30s)   │ minutes      │
└─────────────────────┴─────────────────┴─────────────────┴──────────────┘
```

### Zone Hysteresis (Anti-Flip-Flop)

The system uses **sticky zones** to prevent rapid oscillation. If your position is in WARNING, it must improve by **15% above the threshold** to return to CAUTION (not just cross back by 0.1 pts). This means:

- Once a position enters WARNING (moat drops to 25), it stays WARNING until moat rises above ~29 pts
- Once in CAUTION, it stays CAUTION until moat rises above ~115% of the smart moat value
- This prevents the maddening "WARNING → SAFE → WARNING → SAFE" flip-flop when price oscillates near a boundary

---

## 8. Exit Strategy Actions Explained

| Action | Color | Urgency | What To Do |
|--------|-------|---------|------------|
| **HOLD** | Green | None | Do nothing. Theta is working. Position is safe. |
| **LET_EXPIRE** | Green | None | < 2.5 hours left, position is safe. Let it expire worthless. Close at $0.05 if available. |
| **HOLD_FOR_EXPIRY** | Green | None | Final 30 min. Ignore premium spikes. Only exit if strike is breached. |
| **HOLD_WITH_TRIGGER** | Blue | Low | Hold, but close if SPX hits a specific trigger price for X minutes. |
| **CLOSE_SOON** | Amber | Medium | Start working a close order at the shown target price. You have a few minutes. |
| **CLOSE_RECOMMENDED** | Amber | Medium-High | Escalated from CLOSE_SOON. Multiple signals agree you should close. |
| **CLOSE_NOW** | Red | High | Close at the target price or market. Don't wait. |
| **URGENT_CLOSE** | Red (pulse) | Very High | Escalated — position has been in danger for multiple cycles. Close at any reasonable price. |
| **CRITICAL_EJECT** | Red (pulse) | Maximum | Kill switch. Close at market immediately regardless of price. Max loss is better than surprise assignment. |
| **EXPIRED** | Gray | None | Market closed. Position expired. Check if ITM or OTM. |

---

## 9. Escalation Levels

When a position enters the Warning or Gamma Trap zone, it doesn't immediately jump to "EJECT." Instead, it goes through **graduated escalation levels**, spending a minimum of 3 minutes at each level:

```
SAFE → CAUTION → WARNING → CLOSE_RECOMMENDED → URGENT_CLOSE → CRITICAL_EJECT
                   │              │                    │                │
                   │          3+ min later         3+ min later     3+ min later
                   │              │                    │                │
              Position enters  System confirms    Still in danger   Maximum urgency
              danger zone      danger is real     — close now       — market order
```

**Why this matters:**
- A brief spike into the warning zone for 1-2 minutes → stays at WARNING level
- Sustained presence in danger → escalates to CLOSE_RECOMMENDED (you should act)
- Continued worsening → URGENT_CLOSE (act now)
- Strike breach or prolonged gamma trap → CRITICAL_EJECT (emergency exit)

**De-escalation**: If price recovers, levels drop back down — but with a buffer. A position at CLOSE_RECOMMENDED or higher that recovers drops to WARNING first (not straight to SAFE), giving you a chance to exit on the recovery.

The escalation level appears as a **colored badge** in the exit strategy box:
- Amber badge = CLOSE_RECOMMENDED
- Dark red badge = URGENT_CLOSE  
- Bright red badge = CRITICAL_EJECT

---

## 10. Time of Day — How It Changes Everything

The same position can have completely different recommendations depending on the time:

### Morning (9:30-11:30)
- Standard premium stops apply (200% or 250%)
- Regime classification is most reliable
- Best time to enter new positions (10:00-11:30)

### Midday (11:30-2:30)
- Lower volatility (Lunch Lull)
- Positions tend to be safest here
- Premium stops still apply

### Afternoon (2:30-3:00)
- Volatility starts rising (Pre-Power Hour)
- Do NOT enter new positions
- Monitor existing positions more closely

### Power Hour (3:00-3:45)
- Premium stops become counterproductive — a $1 premium can spike to $3 then decay to $0.10 in 30 min
- System switches to **asset-boundary stops only** (ignore premium, watch SPX level)
- Require sustained breaches (5-10 min) before exiting

### Final Minutes (3:45-4:00)
- **Theta is nuclear.** Premiums collapse exponentially.
- A position in the Warning zone at 3:50 PM will likely expire worthless by 4:00 PM if SPX doesn't actually breach the strike
- System recommends HOLD_FOR_EXPIRY unless strike is breached
- **Never panic-sell a 0DTE position in the last 10 minutes** unless SPX has blown through your strike

---

## 11. Common Scenarios & What To Do

### Scenario 1: "Everything is green, State A, 4 hours left"
**Action**: Perfect conditions. Let theta work. Check back in 15 minutes. Consider entering new positions via Trade Ideas.

### Scenario 2: "Position turned amber with CAUTION message"
**Action**: SPX moved closer to your strike but hasn't reached the Warning zone. Monitor every 5 minutes. Check if directional bias is moving against you. No action needed yet.

### Scenario 3: "WARNING zone — exit strategy says CLOSE_SOON"
**Action**: Read the target price and trigger level. Place a limit close order at the suggested price. If SPX hits the trigger level shown, close at market within the time window shown.

### Scenario 4: "Gamma Trap — CLOSE_NOW with 5 min timer"
**Action**: The system has started a verification timer. If SPX stays in the gamma trap for 5 minutes, it will escalate to CRITICAL_EJECT. Place a close order now. Don't wait for the timer — if you can close at a reasonable price, do it.

### Scenario 5: "Drift alert showing +12 pts"
**Action**: SPX has been creeping toward your strike for 90 minutes. The moat might still look OK, but the trend is against you. Tighten your mental stop. If the drift continues on the next refresh, consider closing for a smaller profit.

### Scenario 6: "Premium trend shows RISING"
**Action**: The estimated cost to close this position is increasing over time (meaning the position is getting worse). Combined with a shrinking moat, this is a strong signal to close sooner rather than later.

### Scenario 7: "Breakeven touch count = 3"
**Action**: This position was underwater, recovered to breakeven three times, and keeps going back underwater. Take the hint — close it on the next recovery to breakeven. The market keeps telling you this position is marginal.

### Scenario 8: "State C, 2 hours left, all positions safe"
**Action**: High chop but your moats are big enough. Don't enter new positions. Hold existing ones. The wide moats are protecting you. Check every 5-10 minutes to ensure moats are holding.

### Scenario 9: "GEX regime is NEGATIVE"
**Action**: Dealers are short gamma, meaning market moves will accelerate. Breakouts are real, not fake. Take Warning zone alerts more seriously than usual. Widen your mental moat requirements.

### Scenario 10: "It's 3:45 PM and one position is in Warning"
**Action**: Do NOT panic-sell. Read the exit strategy — it likely says HOLD_FOR_EXPIRY. Theta is destroying premium. A position 15 pts from the strike at 3:50 PM will very likely expire worthless. Only close if SPX actually crosses your strike price.

---

## 12. Glossary

| Term | Definition |
|------|-----------|
| **0DTE** | Zero Days To Expiration — options that expire today |
| **Credit Spread** | Selling a near-strike option and buying a farther-strike option for protection. You collect premium (credit) upfront. |
| **Put Spread** | Short put spread — profits if SPX stays ABOVE the short strike |
| **Call Spread** | Short call spread — profits if SPX stays BELOW the short strike |
| **Iron Condor** | Put spread + call spread together — profits if SPX stays in a range |
| **Moat** | Distance in SPX points between current price and your short strike |
| **Smart Moat** | Dynamically calculated recommended minimum moat |
| **Theta** | Time decay — options lose value as expiration approaches. This is how you profit. |
| **Gamma** | Rate of change of delta. Near expiry, gamma is extreme — small price moves cause huge option price changes. |
| **GEX** | Gamma Exposure — aggregate dealer gamma positioning across all strikes |
| **VIX** | CBOE Volatility Index — market's expected volatility over next 30 days |
| **VIX9D** | 9-day VIX — more relevant for 0DTE since it captures near-term vol |
| **Premium** | The price of the option / spread. You collect this when selling. |
| **Buyback** | Closing a short spread by buying it back. Costs premium. |
| **Regime** | The current market state (A/B/C) based on chop/trend signals |
| **Whipsaw** | Rapid price reversal that triggers false alarms |
| **Breach** | When SPX crosses a critical level (warning zone, gamma trap, or strike) |
| **Hysteresis** | Using different thresholds for entering vs exiting a zone to prevent flip-flopping |
| **Escalation** | Graduated increase in close urgency the longer a position stays in danger |
| **VWAP** | Volume Weighted Average Price — institutional benchmark. SPX tends to revert to VWAP. |
| **EMA** | Exponential Moving Average — trend indicator. EMA 9 (fast) and EMA 21 (slow). |
| **RSI** | Relative Strength Index — momentum oscillator. Dead zone = 45-55 (no momentum). |
| **CHOP** | Choppiness Index — measures how "choppy" vs "trendy" price action is. > 61.8 = choppy. |
| **ER** | Efficiency Ratio — how much of price movement is directional. < 0.20 = mostly noise. |
