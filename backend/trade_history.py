"""
Trade History Parser — Robinhood CSV Import
Parses Robinhood brokerage CSV exports to identify credit spread trades,
pair STO/BTO legs, track closures (OEXP/BTC/STC/OASGN/OCC),
and compute actual P/L per spread.

Supported instruments: SPXW (SPX weekly 0DTE), SPY options.
"""

import csv
import io
import re
import logging
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger("0DTE-QuantEngine")

OPTION_OPEN_CODES = {"STO", "BTO"}
OPTION_CLOSE_CODES = {"STC", "BTC"}
OPTION_EVENT_CODES = {"OEXP", "OASGN", "OCC"}
ALL_OPTION_CODES = OPTION_OPEN_CODES | OPTION_CLOSE_CODES | OPTION_EVENT_CODES


def parse_amount(amount_str: str) -> float:
    """Parse Robinhood amount: '$811.10' → 811.10, '($378.90)' → -378.90."""
    if not amount_str or not amount_str.strip():
        return 0.0
    s = amount_str.strip().replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    s = s.replace("$", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_price(price_str: str) -> float:
    if not price_str or not price_str.strip():
        return 0.0
    s = price_str.strip().replace(",", "").replace("$", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_quantity(qty_str: str) -> int:
    """Parse quantity: '10' → 10, '10S' → 10 (S suffix = short side in OEXP)."""
    if not qty_str or not qty_str.strip():
        return 0
    s = qty_str.strip().rstrip("Ss")
    try:
        return int(float(s))
    except ValueError:
        return 0


def parse_option_details(desc: str) -> dict | None:
    """
    Extract structured fields from Robinhood option descriptions:
      'SPXW 5/13/2026 Put $7,445.00'
      'Option Expiration for SPXW 5/7/2026 Call $7,410.00'
      'SPY 5/11/2026 Call $741.00'
      'Option Maturity: Cash Component'
    """
    if "Cash Component" in desc or "Maturity" in desc:
        return {"type": "CASH_SETTLEMENT"}

    pattern = r'(?:Option Expiration for\s+)?(\w+)\s+(\d+/\d+/\d+)\s+(Put|Call)\s+\$([0-9,]+\.?\d*)'
    match = re.search(pattern, desc)
    if match:
        return {
            "instrument": match.group(1),
            "expiry": match.group(2),
            "option_type": match.group(3),
            "strike": float(match.group(4).replace(",", "")),
        }
    return None


def parse_csv(csv_content: str) -> list[dict]:
    """
    Parse Robinhood CSV and return structured option transactions.
    Filters out non-option rows (stock buys, dividends, ACH, etc.).
    """
    transactions = []
    reader = csv.DictReader(io.StringIO(csv_content))

    for row in reader:
        trans_code = (row.get("Trans Code") or "").strip()
        if trans_code not in ALL_OPTION_CODES:
            continue

        instrument = (row.get("Instrument") or "").strip()
        if instrument not in ("SPXW", "SPY"):
            continue

        desc = (row.get("Description") or "").strip()
        details = parse_option_details(desc)
        if details is None:
            continue

        activity_date = (row.get("Activity Date") or "").strip()
        amount = parse_amount(row.get("Amount") or "")
        price = parse_price(row.get("Price") or "")
        qty = parse_quantity(row.get("Quantity") or "")

        txn = {
            "date": activity_date,
            "instrument": instrument,
            "trans_code": trans_code,
            "amount": amount,
            "price": price,
            "quantity": qty,
            "description": desc,
            "is_cash_settlement": details.get("type") == "CASH_SETTLEMENT",
            "option_type": details.get("option_type"),
            "strike": details.get("strike"),
            "expiry": details.get("expiry"),
        }
        transactions.append(txn)

    logger.info(f"Parsed {len(transactions)} option transactions from CSV")
    return transactions


def identify_spreads(transactions: list[dict]) -> list[dict]:
    """
    Groups transactions into credit spreads.
    For each (activity_date, expiry, option_type), finds STO/BTO opening pairs
    and matches with closures (OEXP, BTC/STC, OASGN/OCC).
    """
    groups = defaultdict(list)
    cash_settlements = []

    for txn in transactions:
        if txn.get("is_cash_settlement"):
            cash_settlements.append(txn)
            continue
        key = (txn["date"], txn["expiry"], txn["option_type"])
        groups[key].append(txn)

    spreads = []

    for (date, expiry, opt_type), txns in groups.items():
        opens_sto = [t for t in txns if t["trans_code"] == "STO"]
        opens_bto = [t for t in txns if t["trans_code"] == "BTO"]
        closes_btc = [t for t in txns if t["trans_code"] == "BTC"]
        closes_stc = [t for t in txns if t["trans_code"] == "STC"]
        expirations = [t for t in txns if t["trans_code"] == "OEXP"]
        assignments = [t for t in txns if t["trans_code"] == "OASGN"]

        if not opens_sto or not opens_bto:
            continue

        # Aggregate quantity per strike
        sto_qty_map = defaultdict(int)
        for t in opens_sto:
            sto_qty_map[t["strike"]] += t["quantity"]
        bto_qty_map = defaultdict(int)
        for t in opens_bto:
            bto_qty_map[t["strike"]] += t["quantity"]

        # Greedy match: pair each STO strike with closest BTO strike
        # that has matching quantity and reasonable width
        instrument = opens_sto[0]["instrument"] if opens_sto else "SPXW"
        max_width = 15.0 if instrument == "SPXW" else 5.0

        matched_bto = set()
        strike_pairs = []
        for sto_s in sorted(sto_qty_map.keys()):
            sto_q = sto_qty_map[sto_s]
            best_bto = None
            best_dist = float('inf')
            for bto_s in sorted(bto_qty_map.keys()):
                if bto_s in matched_bto:
                    continue
                if bto_qty_map[bto_s] != sto_q:
                    continue
                width = abs(sto_s - bto_s)
                if width > max_width or width == 0:
                    continue
                valid = (opt_type == "Put" and sto_s > bto_s) or (opt_type == "Call" and sto_s < bto_s)
                if valid and width < best_dist:
                    best_dist = width
                    best_bto = bto_s
            if best_bto is not None:
                strike_pairs.append((sto_s, best_bto))
                matched_bto.add(best_bto)

        for short_s, long_s in strike_pairs:
            pair_sto = [t for t in opens_sto if t["strike"] == short_s]
            pair_bto = [t for t in opens_bto if t["strike"] == long_s]
            pair_btc = [t for t in closes_btc if t["strike"] == short_s]
            pair_stc = [t for t in closes_stc if t["strike"] == long_s]
            pair_exp_short = [t for t in expirations if t["strike"] == short_s]
            pair_exp_long = [t for t in expirations if t["strike"] == long_s]
            pair_asgn = [t for t in assignments if t["strike"] == short_s]

            open_credit = sum(t["amount"] for t in pair_sto) + sum(t["amount"] for t in pair_bto)
            close_cost = sum(t["amount"] for t in pair_btc) + sum(t["amount"] for t in pair_stc)

            assignment_cash = 0.0
            if pair_asgn:
                date_cash = [c for c in cash_settlements if c["date"] == date]
                assignment_cash = sum(c["amount"] for c in date_cash)

            total_qty = max(
                sum(t["quantity"] for t in pair_sto),
                sum(t["quantity"] for t in pair_bto),
            )

            if pair_asgn:
                outcome = "ASSIGNED"
            elif pair_btc or pair_stc:
                outcome = "CLOSED"
            elif pair_exp_short or pair_exp_long:
                outcome = "EXPIRED"
            else:
                outcome = "UNKNOWN"

            net_pl = round(open_credit + close_cost + assignment_cash, 2)

            if opt_type == "Put":
                spread_label = f"Put {int(short_s)}/{int(long_s)}"
                width = short_s - long_s
            else:
                spread_label = f"Call {int(short_s)}/{int(long_s)}"
                width = long_s - short_s

            instrument = pair_sto[0]["instrument"] if pair_sto else "SPXW"

            # Convert to a date string suitable for Alpaca (YYYY-MM-DD)
            try:
                parsed_date = datetime.strptime(date, "%m/%d/%Y")
                iso_date = parsed_date.strftime("%Y-%m-%d")
            except Exception:
                iso_date = date

            spreads.append({
                "date": date,
                "iso_date": iso_date,
                "expiry": expiry,
                "instrument": instrument,
                "type": f"{opt_type} Spread",
                "label": spread_label,
                "short_strike": short_s,
                "long_strike": long_s,
                "width": width,
                "contracts": total_qty,
                "open_credit": round(open_credit, 2),
                "close_cost": round(close_cost, 2),
                "assignment_cash": round(assignment_cash, 2),
                "net_pl": net_pl,
                "outcome": outcome,
                "won": net_pl > 0,
            })

    spreads.sort(key=lambda s: datetime.strptime(s["date"], "%m/%d/%Y"), reverse=True)
    logger.info(f"Identified {len(spreads)} credit spreads from CSV")
    return spreads


def compute_trade_stats(spreads: list[dict]) -> dict:
    """Aggregate performance statistics from parsed spreads."""
    if not spreads:
        return {"error": "No spreads found", "total_trades": 0}

    total = len(spreads)
    wins = sum(1 for s in spreads if s["won"])
    losses = total - wins
    win_rate = round(wins / total * 100, 1)
    total_pl = round(sum(s["net_pl"] for s in spreads), 2)
    avg_pl = round(total_pl / total, 2)

    puts = [s for s in spreads if s["type"] == "Put Spread"]
    calls = [s for s in spreads if s["type"] == "Call Spread"]
    put_wins = sum(1 for s in puts if s["won"])
    call_wins = sum(1 for s in calls if s["won"])
    put_pl = round(sum(s["net_pl"] for s in puts), 2)
    call_pl = round(sum(s["net_pl"] for s in calls), 2)

    outcome_dist = defaultdict(int)
    for s in spreads:
        outcome_dist[s["outcome"]] += 1

    best = max(spreads, key=lambda s: s["net_pl"])
    worst = min(spreads, key=lambda s: s["net_pl"])

    daily_pl = defaultdict(float)
    for s in spreads:
        daily_pl[s["date"]] += s["net_pl"]
    daily_pl_list = [
        {"date": d, "pl": round(pl, 2)}
        for d, pl in sorted(daily_pl.items(), key=lambda x: datetime.strptime(x[0], "%m/%d/%Y"), reverse=True)
    ]

    gross_wins = sum(s["net_pl"] for s in spreads if s["net_pl"] > 0)
    gross_losses = abs(sum(s["net_pl"] for s in spreads if s["net_pl"] < 0))
    # Guard: a no-loss state would make this float('inf') → invalid JSON. Cap at a finite sentinel.
    profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (999.99 if gross_wins > 0 else 0.0)

    avg_credit = round(sum(abs(s["open_credit"]) for s in spreads) / total, 2)
    avg_width = round(sum(s["width"] for s in spreads) / total, 1)

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pl": total_pl,
        "avg_pl": avg_pl,
        "profit_factor": profit_factor,
        "put_trades": len(puts),
        "put_wins": put_wins,
        "put_win_rate": round(put_wins / len(puts) * 100, 1) if puts else 0,
        "put_pl": put_pl,
        "call_trades": len(calls),
        "call_wins": call_wins,
        "call_win_rate": round(call_wins / len(calls) * 100, 1) if calls else 0,
        "call_pl": call_pl,
        "outcome_distribution": dict(outcome_dist),
        "best_trade": {"date": best["date"], "label": best["label"], "pl": best["net_pl"]},
        "worst_trade": {"date": worst["date"], "label": worst["label"], "pl": worst["net_pl"]},
        "avg_credit": avg_credit,
        "avg_width": avg_width,
        "daily_pl": daily_pl_list,
    }


def analyze_trade_history(csv_content: str) -> dict:
    """Full pipeline: parse CSV → identify spreads → compute stats."""
    transactions = parse_csv(csv_content)
    if not transactions:
        return {"error": "No option transactions found in CSV", "stats": None, "spreads": []}

    spreads = identify_spreads(transactions)
    stats = compute_trade_stats(spreads)

    return {
        "stats": stats,
        "spreads": spreads,
        "transaction_count": len(transactions),
    }
