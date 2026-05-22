"""
Forward Accuracy Tracker
========================
Logs every real-time engine recommendation and resolves outcomes when
positions close.  This builds a ground-truth dataset over time so system
accuracy can be measured from live data — not unreliable backtest estimates.

Tracked per signal:
  - position id, type, strike, credit
  - timestamp of signal
  - engine action (CLOSE_NOW, CLOSE_SOON, HOLD, etc.)
  - regime score, moat, escalation at that moment
  - resolved: bool (was the outcome recorded?)
  - outcome_won: bool (did the trade end profitably?)
  - close_reason: how the position was closed
  - realized_pl: actual P/L when closed

Only state *transitions* are logged (HOLD→CLOSE_SOON), not every poll cycle.
Accuracy is only displayed once MIN_SIGNALS_FOR_DISPLAY signals are resolved.
"""

import logging
import json
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("accuracy_tracker")

# ---- CONFIGURATION ----
MIN_SIGNALS_FOR_DISPLAY = 10  # Don't show accuracy until this many resolved
TRACKER_FILE = Path(__file__).parent / "accuracy_log.jsonl"

# In-memory state: last known action per position to detect transitions
_last_action: dict[int, str] = {}  # pos_id → last action string


def _append_signal(record: dict):
    """Append a signal record to the JSONL log file."""
    with open(TRACKER_FILE, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _load_signals() -> list[dict]:
    """Load all signal records from the log file."""
    if not TRACKER_FILE.exists():
        return []
    signals = []
    with open(TRACKER_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    signals.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return signals


def _save_signals(signals: list[dict]):
    """Rewrite the full log file (used when resolving outcomes)."""
    with open(TRACKER_FILE, "w") as f:
        for record in signals:
            f.write(json.dumps(record, default=str) + "\n")


# Actions that represent "system says close"
_EXIT_ACTIONS = {"CLOSE_NOW", "CLOSE_SOON", "URGENT_CLOSE", "CRITICAL_EJECT"}
# Actions that represent "system says hold"
_HOLD_ACTIONS = {"HOLD", "HOLD_WITH_TRIGGER", "HOLD_FOR_EXPIRY", "LET_EXPIRE"}


def log_recommendation(pos_id: int, pos_type: str, strike: float,
                        credit: float, action: str, regime_score: int,
                        moat: float, escalation: str | None = None):
    """
    Called after each evaluate_positions cycle.  Only logs when the action
    transitions (e.g. HOLD → CLOSE_SOON) to avoid flooding the log.
    """
    prev = _last_action.get(pos_id)
    if prev == action:
        return  # No transition — skip

    _last_action[pos_id] = action

    is_exit = action in _EXIT_ACTIONS
    record = {
        "pos_id": pos_id,
        "pos_type": pos_type,
        "strike": strike,
        "credit": credit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "is_exit_signal": is_exit,
        "regime_score": regime_score,
        "moat": round(moat, 1),
        "escalation": escalation,
        "resolved": False,
        "outcome_won": None,
        "realized_pl": None,
        "close_reason": None,
    }
    _append_signal(record)
    logger.info(
        f"Signal logged: pos {pos_id} ({pos_type}@{strike}) "
        f"action={action} moat={moat:.1f} regime={regime_score}"
    )


def resolve_position(pos_id: int, won: bool, realized_pl: float | None,
                      close_reason: str = "manual"):
    """
    Called when a position is closed.  Marks all unresolved signals for this
    position with the actual outcome.
    """
    signals = _load_signals()
    updated = 0
    for s in signals:
        if s["pos_id"] == pos_id and not s["resolved"]:
            s["resolved"] = True
            s["outcome_won"] = won
            s["realized_pl"] = realized_pl
            s["close_reason"] = close_reason
            updated += 1

    if updated > 0:
        _save_signals(signals)
        logger.info(
            f"Resolved {updated} signal(s) for pos {pos_id}: "
            f"won={won}, pl={realized_pl}, reason={close_reason}"
        )

    # Clean up in-memory state
    _last_action.pop(pos_id, None)


def clear_position_state(pos_id: int):
    """Remove in-memory tracking for a position (e.g. after close/delete)."""
    _last_action.pop(pos_id, None)


def get_accuracy_stats() -> dict | None:
    """
    Compute accuracy metrics from resolved signals.
    Returns None if insufficient data (< MIN_SIGNALS_FOR_DISPLAY resolved).

    Metrics:
      - exit_signals_total: how many times system said "close"
      - exit_on_losing_trades: of those, how many were on trades that lost
      - exit_accuracy_pct: exit_on_losing_trades / exit_signals_total
      - hold_signals_total: how many times system said "hold"
      - hold_on_winning_trades: of those, how many were on trades that won
      - hold_accuracy_pct: hold_on_winning_trades / hold_signals_total
      - total_resolved: total resolved signals
      - total_unresolved: signals still awaiting outcome
    """
    signals = _load_signals()
    resolved = [s for s in signals if s["resolved"]]
    unresolved = [s for s in signals if not s["resolved"]]

    if len(resolved) < MIN_SIGNALS_FOR_DISPLAY:
        return None  # Not enough data to show

    # Exit signals: system said close → was the trade actually losing?
    exit_signals = [s for s in resolved if s["is_exit_signal"]]
    exit_on_losers = [s for s in exit_signals if not s["outcome_won"]]

    # Hold signals: system said hold → was the trade actually winning?
    hold_signals = [s for s in resolved if not s["is_exit_signal"]]
    hold_on_winners = [s for s in hold_signals if s["outcome_won"]]

    exit_total = len(exit_signals)
    hold_total = len(hold_signals)

    return {
        "exit_signals_total": exit_total,
        "exit_on_losing_trades": len(exit_on_losers),
        "exit_accuracy_pct": round(
            len(exit_on_losers) / exit_total * 100, 1
        ) if exit_total > 0 else None,
        "hold_signals_total": hold_total,
        "hold_on_winning_trades": len(hold_on_winners),
        "hold_accuracy_pct": round(
            len(hold_on_winners) / hold_total * 100, 1
        ) if hold_total > 0 else None,
        "total_resolved": len(resolved),
        "total_unresolved": len(unresolved),
        "min_signals_required": MIN_SIGNALS_FOR_DISPLAY,
        "data_sufficient": True,
    }


def get_signal_log(limit: int = 50) -> list[dict]:
    """Return the most recent signals for debugging/inspection."""
    signals = _load_signals()
    return signals[-limit:]
