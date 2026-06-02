"""
Synthetic-scenario replay harness (Implementation Plan P1-6).

Drives the LIVE engine (`evaluate_positions`) bar-by-bar over a constructed SPX
price path with injected synthetic positions, so we can validate exit/sizing
DECISIONS without trade timestamps or paid option data.

Why this works: the engine's exit decision for a spread depends only on the SPX
path + moat + regime indicators (RSI/ER/range) + the strikes + time remaining --
NOT on when the position was opened. So we choose the entry time-of-day ourselves
and replay the path. See docs/VALIDATION_PLAN.md.

Run directly:  python3 synthetic_replay.py
Use in tests:  from synthetic_replay import SyntheticPosition, replay, make_directional_path, first_action, breach_bar

Known v1 limitation: engine._update_drift_tracker() stamps prices with wall-clock
time (datetime.now()), so the secondary `drift_alert` is not bar-time-accurate inside
a tight loop. It does NOT affect the action timeline (driven by moat/zone/time/reversal).
Bar-time injection is a P1-6 follow-up; we clear engine._drift_history between scenarios.
"""

from datetime import datetime as _real_datetime, timezone as _tz, timedelta as _td
from unittest.mock import MagicMock

import engine


# --------------------------------------------------------------------------- #
# Bar-time clock injection
# --------------------------------------------------------------------------- #
# The engine reads datetime.now() internally for cooldown, escalation, breach
# timers and drift. To replay faithfully we drive a controllable clock derived
# from each bar's hours_remaining, instead of real wall-clock (which would
# collapse every bar into the same instant and freeze the cooldown/escalation).
_MARKET_CLOSE_UTC = _real_datetime(2026, 5, 13, 20, 0, 0, tzinfo=_tz.utc)  # ~16:00 ET (EDT)


class _Clock:
    """Stand-in for engine.datetime: .now() returns simulated bar-time; everything
    else (fromisoformat, strptime, ...) delegates to the real datetime class."""

    def __init__(self):
        self._t = _MARKET_CLOSE_UTC

    def set_from_hours_remaining(self, hours):
        self._t = _MARKET_CLOSE_UTC - _td(hours=max(0.0, float(hours)))

    def now(self, tz=None):
        return self._t if tz is None else self._t.astimezone(tz)

    def __getattr__(self, name):
        return getattr(_real_datetime, name)


# --------------------------------------------------------------------------- #
# Synthetic position (mirrors the PositionDB attributes the engine reads)
# --------------------------------------------------------------------------- #
class SyntheticPosition:
    """Stand-in for a PositionDB row. `contracts` is carried for future sizing tests."""

    def __init__(self, id, type, strike, credit, breach_start_time=None, contracts=1):
        self.id = id
        self.type = type            # "Call Spread" | "Put Spread"
        self.strike = strike        # short strike
        self.credit = credit        # credit per contract
        self.breach_start_time = breach_start_time
        self.contracts = contracts


# --------------------------------------------------------------------------- #
# Bar / context construction
# --------------------------------------------------------------------------- #
def _context(spx, day_low, day_high, hours_remaining, rsi, er, bias,
             regime_score=0, effective_moat_min=35, gex_data=None, surge_data=None):
    rng = max(1e-9, day_high - day_low)
    range_position = max(0.0, min(100.0, (spx - day_low) / rng * 100.0))
    return dict(
        regime_score=regime_score,
        effective_moat_min=effective_moat_min,
        directional_bias=bias,
        range_position=range_position,
        day_high_spx=day_high,
        day_low_spx=day_low,
        hours_remaining=hours_remaining,
        rsi_14=rsi,
        er_value=er,
        gex_data=gex_data,
        surge_data=surge_data,
    )


def make_directional_path(short_strike, side="Call Spread", n=22,
                          start_dist=30.0, end_dist=-8.0,
                          start_hours=0.7, end_hours=0.03,
                          er=0.45, regime_score=0, effective_moat_min=35,
                          gex_regime=None):
    """
    A steady, efficient directional grind that carries SPX from `start_dist` points
    away from the short strike to `end_dist` points past it (negative = through it).

    Call Spread -> SPX rises toward/through the short call (the at-risk side).
    Put Spread  -> SPX falls toward/through the short put.

    RSI pushes into the overbought/oversold extreme, ER stays high (efficient trend,
    so the engine awards NO reversal credit for weak ER), range_position rides the
    extreme (new highs/lows). `start_hours`/`end_hours` place the move in the session.
    """
    bars = []
    prices = []
    for i in range(n):
        f = i / (n - 1)
        hours = start_hours + (end_hours - start_hours) * f
        if side == "Call Spread":
            spx = short_strike - start_dist + (start_dist - end_dist) * f
            bias = "STRONG BULLISH"
            rsi = 55.0 + 23.0 * f          # 55 -> ~78 (overbought)
        else:
            spx = short_strike + start_dist - (start_dist - end_dist) * f
            bias = "STRONG BEARISH"
            rsi = 45.0 - 23.0 * f          # 45 -> ~22 (oversold)
        prices.append(spx)
        day_low = min(prices)
        day_high = max(prices)
        bars.append({
            "label": f"t{i:02d} h={hours:0.2f}",
            "spx": round(spx, 2),
            "ctx": _context(spx, day_low, day_high, hours, rsi, er, bias,
                            regime_score=regime_score, effective_moat_min=effective_moat_min,
                            gex_data=({"gex_regime": gex_regime, "gamma_wall_spx": short_strike + 60.0}
                                      if gex_regime else None)),
        })
    return bars


# --------------------------------------------------------------------------- #
# Replay driver
# --------------------------------------------------------------------------- #
def replay(positions, bars, reset=True):
    """Step the engine through each bar; return a flat timeline of per-position decisions."""
    if reset:
        engine.clear_rec_state()
        try:
            engine._drift_history.clear()   # not reset by clear_rec_state()
        except AttributeError:
            pass
    db = MagicMock()
    timeline = []
    clock = _Clock()
    saved_dt = engine.datetime
    engine.datetime = clock          # inject bar-time for the duration of the replay
    try:
        for bar in bars:
            clock.set_from_hours_remaining(bar["ctx"]["hours_remaining"])
            results = engine.evaluate_positions(list(positions), bar["spx"], db, **bar["ctx"])
            for r in results:
                es = r["exit_strategy"]
                timeline.append({
                    "label": bar["label"],
                    "hours": round(bar["ctx"]["hours_remaining"], 2),
                    "spx": bar["spx"],
                    "pos_id": r["id"],
                    "moat": r["moat"],
                    "action": es["action"],
                    "escalation": es.get("escalation_level"),
                    "reversal_score": r["reversal_score"],
                    "reversal_downgrade": es.get("reversal_downgrade", False),
                    "p0_2_forced": es.get("p0_2_forced", False),
                    "mean_reverting": r.get("mean_reverting", False),
                })
    finally:
        engine.datetime = saved_dt   # always restore the real datetime
    return timeline


# --------------------------------------------------------------------------- #
# Assertion helpers
# --------------------------------------------------------------------------- #
_EXIT_ACTIONS = {"CLOSE_SOON", "CLOSE_NOW", "URGENT_CLOSE", "CRITICAL_EJECT"}
_HARD_EXIT = {"URGENT_CLOSE", "CRITICAL_EJECT"}


def first_action(timeline, pos_id, actions):
    """First timeline row for pos_id whose action is in `actions` (set/iterable), else None."""
    actions = set(actions)
    for row in timeline:
        if row["pos_id"] == pos_id and row["action"] in actions:
            return row
    return None


def breach_bar(timeline, pos_id):
    """First row where the position's strike is breached (moat <= 0), else None."""
    for row in timeline:
        if row["pos_id"] == pos_id and row["moat"] <= 0:
            return row
    return None


def exited_before_breach(timeline, pos_id):
    """True if a real exit signal (CLOSE_*/EJECT) fired strictly before strike breach."""
    first_exit = first_action(timeline, pos_id, _EXIT_ACTIONS)
    breach = breach_bar(timeline, pos_id)
    if first_exit is None:
        return False
    if breach is None:
        return True
    return first_exit["spx"] != breach["spx"] and timeline.index(first_exit) < timeline.index(breach)


def hold_while_escalation_critical(timeline, pos_id):
    """Rows where the USER-FACING action is a HOLD_* while the engine's internal
    escalation is already URGENT_CLOSE / CRITICAL_EJECT.

    A non-empty result is the 5/13 trap: the engine has internally decided the
    position must be ejected, but is still telling the trader to HOLD. P0-2 must
    make this list empty for a with-trend short.
    """
    bad = []
    for row in timeline:
        if (row["pos_id"] == pos_id
                and str(row["action"]).startswith("HOLD")
                and row["escalation"] in _HARD_EXIT):
            bad.append(row)
    return bad


# --------------------------------------------------------------------------- #
# Demonstration scenarios
# --------------------------------------------------------------------------- #
def _print_timeline(title, timeline, short_strike):
    print(f"\n=== {title} ===")
    print(f"{'bar':<12}{'hrs':>5}{'SPX':>9}{'moat':>7}  {'action':<18}{'esc':<18}{'rev':>4}{'F':>3}{'MR':>4}")
    for r in timeline:
        f_flag = "F" if r.get("p0_2_forced") else ""
        mr = "mr" if r.get("mean_reverting") else ""
        print(f"{r['label']:<12}{r['hours']:>5}{r['spx']:>9}{r['moat']:>7}  "
              f"{r['action']:<18}{str(r['escalation']):<18}{r['reversal_score']:>4}{f_flag:>3}{mr:>4}")


def scenario_0513_final_30min():
    """
    5/13 keystone: the short 7440 call spread (4 lots) on the afternoon rally.
    Place the trend-through in the final ~40 minutes (the live-trade danger window).
    Current engine is expected to HOLD_FOR_EXPIRY through the warning zone and only
    eject AT/after the strike is breached -- i.e. at ~max loss. P0-2 must fix this.
    """
    pos = SyntheticPosition(id=513, type="Call Spread", strike=7440.0, credit=0.50, contracts=4)
    bars = make_directional_path(7440.0, side="Call Spread",
                                 start_dist=30.0, end_dist=-8.0,
                                 start_hours=0.66, end_hours=0.02)
    tl = replay([pos], bars)
    _print_timeline("5/13 final-30min trend-through  (short 7440 Call Spread x4)", tl, 7440.0)

    first_exit = first_action(tl, 513, _EXIT_ACTIONS)
    breach = breach_bar(tl, 513)
    held_while_critical = hold_while_escalation_critical(tl, 513)
    forced = [r for r in tl if r["pos_id"] == 513 and r.get("p0_2_forced")]
    print("\n  VERDICT (with P0-2):")
    print(f"    first user-facing close : "
          f"{first_exit['action']+' @ SPX '+str(first_exit['spx'])+' (moat '+str(first_exit['moat'])+')' if first_exit else 'NONE'}")
    print(f"    strike breached at      : "
          f"{'SPX '+str(breach['spx'])+' (moat '+str(breach['moat'])+')' if breach else 'not breached'}")
    print(f"    P0-2 forced-exit bars   : {len(forced)}"
          + (f"  (first @ SPX {forced[0]['spx']}, esc {forced[0]['escalation']})" if forced else ""))
    print(f"    HOLD-while-URGENT/EJECT  : {len(held_while_critical)}  (must be 0)")
    ok = (len(held_while_critical) == 0 and len(forced) > 0)
    print(f"    >>> GR-0513 {'PASS' if ok else 'FAIL'}: trend-continuation forces a non-downgradable exit, no HOLD-while-critical.")
    return tl


def scenario_calm_guard():
    """Guard: a calm range day must NOT produce any close/eject (no false alarms)."""
    pos = SyntheticPosition(id=1, type="Call Spread", strike=7440.0, credit=0.50)
    # SPX drifts 70-40 pts below the short call all day; never threatens it.
    bars = make_directional_path(7440.0, side="Call Spread",
                                 start_dist=70.0, end_dist=40.0,
                                 start_hours=5.5, end_hours=2.5, er=0.15)
    tl = replay([pos], bars)
    any_exit = first_action(tl, 1, _EXIT_ACTIONS)
    print("\n=== GUARD: calm range day (short 7440 call, never near strike) ===")
    print(f"  any close/eject signal? : {any_exit['action'] if any_exit else 'NONE (correct)'}")
    return tl


def scenario_0529_meanrev():
    """
    5/29 counter-case: a short 7550 put spread pressed toward the strike in the final
    ~40 min, but in a POSITIVE-GEX (mean-reverting) regime with oversold RSI — today's
    actual conditions, where the position bounced for a +$1,255 day. P0-2 must NOT
    force-close here (the hold / reversal-downgrade is correct). Mirror of GR-0513 with
    the opposite regime.
    """
    pos = SyntheticPosition(id=529, type="Put Spread", strike=7550.0, credit=0.74, contracts=15)
    bars = make_directional_path(7550.0, side="Put Spread",
                                 start_dist=30.0, end_dist=12.0,   # dips toward strike, never breaches
                                 start_hours=0.66, end_hours=0.02,
                                 er=0.20, gex_regime="POSITIVE")
    tl = replay([pos], bars)
    _print_timeline("5/29 final-30min dip, POSITIVE-GEX mean-reverting  (short 7550 Put Spread x15)", tl, 7550.0)
    forced = [r for r in tl if r["pos_id"] == 529 and r.get("p0_2_forced")]
    n_pos = len([r for r in tl if r["pos_id"] == 529])
    mr_bars = sum(1 for r in tl if r["pos_id"] == 529 and r.get("mean_reverting"))
    ok = (len(forced) == 0 and mr_bars > 0)
    print("\n  VERDICT (with P0-2):")
    print(f"    mean-reverting bars      : {mr_bars}/{n_pos}  (positive GEX recognized)")
    print(f"    P0-2 forced-exit bars    : {len(forced)}  (must be 0 — do NOT force the positive-GEX bounce)")
    print(f"    >>> GR-0529 {'PASS' if ok else 'FAIL'}: mean-reverting regime is NOT force-closed.")
    return tl


def scenario_0518_put_trendthrough():
    """5/18 real tail (backtest worst put leg): short 7385 put spread broke DOWN through the
    strike to deep ITM (bought back ~$17.83). No positive-GEX support → P0-2 must force the exit."""
    pos = SyntheticPosition(id=518, type="Put Spread", strike=7385.0, credit=0.58, contracts=6)
    bars = make_directional_path(7385.0, side="Put Spread", start_dist=30.0, end_dist=-8.0,
                                 start_hours=0.66, end_hours=0.02, gex_regime=None)
    tl = replay([pos], bars)
    forced = [r for r in tl if r["pos_id"] == 518 and r.get("p0_2_forced")]
    hwc = hold_while_escalation_critical(tl, 518)
    ok = len(forced) > 0 and len(hwc) == 0
    print(f"\n=== GR-0518 put trend-through (short 7385 put) ===")
    print(f"    forced bars: {len(forced)}  HOLD-while-URGENT/EJECT: {len(hwc)}")
    print(f"    >>> GR-0518 {'PASS' if ok else 'FAIL'}: bearish trend-through forces the exit.")
    return tl


def scenario_0519_call_trendthrough():
    """5/19 real tail (backtest worst trade −$5,189): short 7380 call spread broke UP through the
    strike to deep ITM (bought back ~$11.08). No positive-GEX support → P0-2 must force the exit."""
    pos = SyntheticPosition(id=519, type="Call Spread", strike=7380.0, credit=0.73, contracts=15)
    bars = make_directional_path(7380.0, side="Call Spread", start_dist=30.0, end_dist=-8.0,
                                 start_hours=0.66, end_hours=0.02, gex_regime=None)
    tl = replay([pos], bars)
    forced = [r for r in tl if r["pos_id"] == 519 and r.get("p0_2_forced")]
    hwc = hold_while_escalation_critical(tl, 519)
    ok = len(forced) > 0 and len(hwc) == 0
    print(f"\n=== GR-0519 call trend-through (short 7380 call) ===")
    print(f"    forced bars: {len(forced)}  HOLD-while-URGENT/EJECT: {len(hwc)}")
    print(f"    >>> GR-0519 {'PASS' if ok else 'FAIL'}: bullish trend-through forces the exit.")
    return tl


if __name__ == "__main__":
    print("SYNTHETIC-SCENARIO REPLAY HARNESS  (driving the live engine.evaluate_positions)")
    scenario_0513_final_30min()
    scenario_0518_put_trendthrough()
    scenario_0519_call_trendthrough()
    scenario_0529_meanrev()
    scenario_calm_guard()
    print("\nDone. (F = P0-2 forced exit; mr = mean-reverting regime; * dg = reversal downgrade)")
