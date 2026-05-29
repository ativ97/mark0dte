"""
Signal Outcome Tracker v2
=========================
Tracks every exit/hold signal with full market context, then measures what
happened AFTER the signal to determine if it was correct.

Key question answered: "When the system said X, was it right?"

For EXIT signals (CLOSE_SOON, TAKE_PROFIT, etc.):
  - Correct if exiting at signal time was cheaper than the final outcome.
  - Measured in dollars: exit_savings = final_cost - buyback_at_signal.
    Positive = signal saved money, negative = signal was premature.

For HOLD signals (HOLD, LET_EXPIRE, etc.):
  - Correct if the position remained profitable (expired OTM or closed profitably).
  - Wrong if position went ITM or the trade lost money.

Between signal and resolution, tracks worst/best moat and buyback to capture
the full risk picture — even if the final outcome was good, we know how close
it got to disaster.

Only state *transitions* are logged (HOLD→CLOSE_SOON), not every poll cycle.
Between transitions, each cycle updates the tracking stats (worst moat, etc.).
"""

import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger("signal_tracker")

# ---- CONFIGURATION ----
MIN_SIGNALS_FOR_DISPLAY = 10
SIGNAL_LOG_FILE = Path(__file__).parent / "signal_log.jsonl"
SPREAD_WIDTH = 5.0  # $5 SPX spread width — max loss per contract

# Actions that represent "system says close"
_EXIT_ACTIONS = {"CLOSE_NOW", "CLOSE_SOON", "URGENT_CLOSE", "CRITICAL_EJECT", "TAKE_PROFIT"}
# Actions that represent "system says hold"
_HOLD_ACTIONS = {"HOLD", "HOLD_WITH_TRIGGER", "HOLD_FOR_EXPIRY", "LET_EXPIRE"}

# ---- IN-MEMORY STATE ----
# One active signal per position — updated every telemetry cycle
_active_signals: dict[int, dict] = {}  # pos_id → current signal record


def _flush_signal(signal: dict):
    """Append a finalized signal record to the JSONL log file."""
    with open(SIGNAL_LOG_FILE, "a") as f:
        f.write(json.dumps(signal, default=str) + "\n")


def _load_finalized_signals() -> list[dict]:
    """Load all finalized signal records from the log file."""
    if not SIGNAL_LOG_FILE.exists():
        return []
    signals = []
    with open(SIGNAL_LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    signals.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return signals


def _grade_signal(signal: dict) -> dict:
    """
    Compute signal correctness based on what happened after.

    For EXIT signals:
      Compare buyback_at_signal vs final_cost (what holding cost in the end).
      exit_savings = final_cost - buyback_at_signal
      Positive = signal saved money.

    For HOLD signals:
      Correct if realized_pl >= 0.

    Returns dict with: signal_grade, exit_savings, grade_reason.
    """
    is_exit = signal.get("is_exit_signal", False)
    buyback_at_signal = signal.get("buyback_at_signal", 0)
    realized_pl = signal.get("realized_pl")
    close_reason = signal.get("close_reason", "")
    credit = signal.get("credit", 0)
    worst_moat = signal.get("worst_moat_after", 999)

    if is_exit:
        # What would it have cost to exit when the signal fired?
        exit_cost = buyback_at_signal

        # What did the position actually cost in the end?
        if close_reason == "expired_otm":
            final_cost = 0.0  # Expired worthless — free!
        elif close_reason == "expired_itm":
            final_cost = SPREAD_WIDTH  # Max loss
        elif realized_pl is not None:
            final_cost = credit - realized_pl  # Actual close price
        else:
            final_cost = 0.0  # Unknown — assume expired OTM

        exit_savings = round(final_cost - exit_cost, 2)

        if exit_savings > 0.05:
            grade = "CORRECT"
            reason = (
                f"Exiting at ~${exit_cost:.2f} saved ${exit_savings:.2f}/contract "
                f"vs actual cost of ${final_cost:.2f}."
            )
        elif exit_savings < -0.05:
            # Signal was premature — but was the risk real?
            if worst_moat <= 10:
                grade = "JUSTIFIED"
                reason = (
                    f"Exiting at ~${exit_cost:.2f} cost ${abs(exit_savings):.2f} extra "
                    f"vs holding, BUT moat hit {worst_moat:.0f} pts — risk was real."
                )
            else:
                grade = "PREMATURE"
                reason = (
                    f"Exiting at ~${exit_cost:.2f} cost ${abs(exit_savings):.2f} extra. "
                    f"Position recovered (worst moat {worst_moat:.0f} pts). Premature signal."
                )
        else:
            grade = "NEUTRAL"
            reason = "Exit vs hold was roughly equal (±$0.05)."

        return {"signal_grade": grade, "exit_savings": exit_savings, "grade_reason": reason}

    else:
        # HOLD signal
        if realized_pl is not None and realized_pl >= 0:
            grade = "CORRECT"
            reason = f"Hold was correct — trade profited ${realized_pl:.2f}/contract."
        elif realized_pl is not None and realized_pl < 0:
            grade = "WRONG"
            reason = f"Hold was wrong — trade lost ${abs(realized_pl):.2f}/contract."
        elif close_reason == "expired_otm":
            grade = "CORRECT"
            reason = f"Hold was correct — expired OTM, full ${credit:.2f} credit kept."
        elif close_reason == "expired_itm":
            grade = "WRONG"
            reason = "Hold was wrong — expired ITM, max loss."
        else:
            grade = "PENDING"
            reason = "Outcome unknown."

        hold_value = realized_pl if realized_pl is not None else 0
        return {"signal_grade": grade, "exit_savings": round(hold_value, 2), "grade_reason": reason}


# ---- PUBLIC API (called from main.py) ----

def track_signal(pos_id: int, pos_type: str, strike: float, credit: float,
                 action: str, regime_score: int, moat: float,
                 escalation: str | None = None, spx_price: float = 0,
                 buyback: float = 0, hours_remaining: float = 0):
    """
    Called every telemetry cycle for every position.

    On action TRANSITIONS: finalizes the previous signal (with partial tracking),
    creates a new signal with fresh context snapshot.

    On SAME action: updates tracking stats (worst/best moat, buyback, sample count).
    """
    active = _active_signals.get(pos_id)

    if active is None or active["action"] != action:
        # ---- TRANSITION: finalize previous, start new ----
        if active is not None:
            active["superseded_by"] = action
            active["resolved"] = True
            active["close_reason"] = "superseded"
            # For superseded signals, realized_pl isn't known yet — leave as None
            grading = _grade_signal(active)
            active.update(grading)
            _flush_signal(active)
            logger.info(
                f"Signal finalized (superseded): pos {pos_id} "
                f"action={active['action']} → {action}"
            )

        profit_pct = round((credit - buyback) / credit * 100, 1) if credit > 0 else 0

        _active_signals[pos_id] = {
            "signal_id": str(uuid4()),
            "pos_id": pos_id,
            "pos_type": pos_type,
            "strike": strike,
            "credit": credit,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "is_exit_signal": action in _EXIT_ACTIONS,
            "escalation": escalation,
            "regime_score": regime_score,
            # Snapshot at signal time
            "spx_at_signal": round(spx_price, 2),
            "moat_at_signal": round(moat, 1),
            "buyback_at_signal": round(buyback, 4),
            "profit_pct_at_signal": profit_pct,
            "hours_at_signal": round(hours_remaining, 2),
            # Tracking (updated each cycle)
            "worst_moat_after": round(moat, 1),
            "best_moat_after": round(moat, 1),
            "worst_buyback_after": round(buyback, 4),
            "best_buyback_after": round(buyback, 4),
            "tracking_samples": 0,
            # Resolution (set on close/expiry)
            "resolved": False,
            "close_reason": None,
            "realized_pl": None,
            "superseded_by": None,
            "signal_grade": None,
            "exit_savings": None,
            "grade_reason": None,
        }
        logger.info(
            f"Signal logged: pos {pos_id} ({pos_type}@{strike}) "
            f"action={action} moat={moat:.1f} buyback=${buyback:.2f} "
            f"profit={profit_pct:.0f}% regime={regime_score}"
        )
    else:
        # ---- SAME ACTION: update tracking ----
        active["worst_moat_after"] = round(min(active["worst_moat_after"], moat), 1)
        active["best_moat_after"] = round(max(active["best_moat_after"], moat), 1)
        active["worst_buyback_after"] = round(max(active["worst_buyback_after"], buyback), 4)
        active["best_buyback_after"] = round(min(active["best_buyback_after"], buyback), 4)
        active["tracking_samples"] += 1


def resolve_position(pos_id: int, won: bool, realized_pl: float | None,
                     close_reason: str = "manual"):
    """
    Called when a position is closed. Finalizes the active signal with outcome,
    computes correctness grade, and flushes to disk.
    """
    active = _active_signals.pop(pos_id, None)
    if active:
        active["resolved"] = True
        active["realized_pl"] = realized_pl
        active["close_reason"] = close_reason
        grading = _grade_signal(active)
        active.update(grading)
        _flush_signal(active)
        logger.info(
            f"Signal resolved: pos {pos_id} action={active['action']} "
            f"grade={active['signal_grade']} savings=${active['exit_savings']:.2f} "
            f"pl={realized_pl} reason={close_reason}"
        )


def resolve_expired_positions(positions: list[dict]) -> int:
    """P0-6: at expiry (market close), grade every still-open signal by its expiry outcome
    instead of leaving it unresolved forever. OTM (moat > 0) = full credit kept; ITM (moat <= 0)
    = max loss (width - credit). Idempotent: only resolves positions that still have an active
    signal. Returns the number resolved. Call this from the telemetry pipeline when the market
    has closed (hours_remaining <= 0), BEFORE/instead of track_signal('EXPIRED', ...)."""
    resolved = 0
    for p in positions:
        pid = p.get("id")
        if pid is None or pid not in _active_signals:
            continue
        moat = p.get("moat", 0) or 0
        credit = p.get("credit", 0) or 0
        if moat > 0:
            close_reason, realized_pl = "expired_otm", round(credit, 2)
        else:
            close_reason, realized_pl = "expired_itm", round(-(SPREAD_WIDTH - credit), 2)
        resolve_position(pid, won=(close_reason == "expired_otm"),
                         realized_pl=realized_pl, close_reason=close_reason)
        resolved += 1
    if resolved:
        logger.info(f"resolve_expired_positions: graded {resolved} signal(s) at expiry")
    return resolved


def clear_position_state(pos_id: int):
    """Remove in-memory tracking for a position (e.g. after delete)."""
    _active_signals.pop(pos_id, None)


def get_accuracy_stats() -> dict | None:
    """
    Compute signal quality metrics from finalized signals.
    Returns None if insufficient data.

    Key metrics:
      - exit_correct / exit_total / exit_pct: how often exit signals were right
      - hold_correct / hold_total / hold_pct: how often hold signals were right
      - total_exit_savings: net $ saved by following exit signals
      - total_hold_earnings: net $ earned by following hold signals
      - overall_correct / overall_total / overall_pct
      - per_action: breakdown by action type
    """
    signals = _load_finalized_signals()
    # Only count non-superseded signals for stats (superseded have incomplete outcomes)
    resolved = [s for s in signals if s.get("resolved") and s.get("close_reason") != "superseded"]
    pending_count = len([s for s in signals if not s.get("resolved")])
    active_count = len(_active_signals)

    if len(resolved) < MIN_SIGNALS_FOR_DISPLAY:
        return {
            "data_sufficient": False,
            "total_resolved": len(resolved),
            "total_pending": pending_count + active_count,
            "min_signals_required": MIN_SIGNALS_FOR_DISPLAY,
        }

    # ---- EXIT SIGNALS ----
    exit_signals = [s for s in resolved if s.get("is_exit_signal")]
    exit_correct = [s for s in exit_signals if s.get("signal_grade") in ("CORRECT", "JUSTIFIED")]
    exit_premature = [s for s in exit_signals if s.get("signal_grade") == "PREMATURE"]
    exit_savings_total = sum(s.get("exit_savings", 0) for s in exit_signals)

    # ---- HOLD SIGNALS ----
    hold_signals = [s for s in resolved if not s.get("is_exit_signal")]
    hold_correct = [s for s in hold_signals if s.get("signal_grade") == "CORRECT"]
    hold_wrong = [s for s in hold_signals if s.get("signal_grade") == "WRONG"]
    hold_earnings_total = sum(s.get("exit_savings", 0) for s in hold_signals)

    # ---- PER-ACTION BREAKDOWN ----
    per_action = {}
    for s in resolved:
        action = s.get("action", "UNKNOWN")
        if action not in per_action:
            per_action[action] = {"total": 0, "correct": 0, "savings": 0.0}
        per_action[action]["total"] += 1
        if s.get("signal_grade") in ("CORRECT", "JUSTIFIED"):
            per_action[action]["correct"] += 1
        per_action[action]["savings"] += s.get("exit_savings", 0)
    for k in per_action:
        per_action[k]["savings"] = round(per_action[k]["savings"], 2)
        t = per_action[k]["total"]
        per_action[k]["pct"] = round(per_action[k]["correct"] / t * 100, 1) if t > 0 else 0

    overall_correct = len(exit_correct) + len(hold_correct)
    overall_total = len(resolved)

    return {
        "data_sufficient": True,
        # Exit metrics
        "exit_total": len(exit_signals),
        "exit_correct": len(exit_correct),
        "exit_premature": len(exit_premature),
        "exit_pct": round(len(exit_correct) / len(exit_signals) * 100, 1) if exit_signals else None,
        "exit_savings_total": round(exit_savings_total, 2),
        # Hold metrics
        "hold_total": len(hold_signals),
        "hold_correct": len(hold_correct),
        "hold_wrong": len(hold_wrong),
        "hold_pct": round(len(hold_correct) / len(hold_signals) * 100, 1) if hold_signals else None,
        "hold_earnings_total": round(hold_earnings_total, 2),
        # Overall
        "overall_correct": overall_correct,
        "overall_total": overall_total,
        "overall_pct": round(overall_correct / overall_total * 100, 1) if overall_total > 0 else 0,
        "net_signal_value": round(exit_savings_total + hold_earnings_total, 2),
        # Per-action breakdown
        "per_action": per_action,
        # Counts
        "total_resolved": overall_total,
        "total_pending": pending_count + active_count,
        "min_signals_required": MIN_SIGNALS_FOR_DISPLAY,
    }


def get_signal_log(limit: int = 50) -> list[dict]:
    """Return the most recent finalized signals for inspection."""
    signals = _load_finalized_signals()
    return signals[-limit:]
