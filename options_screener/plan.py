"""Per-candidate morning plan: entry trigger, order rules, target, invalidation, time stop, cost.
Research only: this is text for a human, nothing here can send an order."""
from __future__ import annotations

from datetime import date

from .models import Candidate
from .signals import after_open


def build(c: Candidate, cfg: dict) -> dict:
    p, snap, fq = cfg["plan"], c.snapshot, c.fill
    mid = snap.mid or 0.0
    ask = snap.ask or mid
    side = "HIGH" if c.direction == "bull" else "LOW"
    orm = p["entry_after_minutes"]
    start = after_open(date(2000, 1, 3), orm).strftime("%H:%M").lstrip("0")
    fee = cfg["account"]["fee_per_contract_usd"]
    sz = c.sizing
    n = sz.contracts if sz and sz.affordable else 0
    max_debit = ask                      # the size was computed at the ask, so the ask is the ceiling
    spread_cap = (fq.median_spread_pct or 0) * p["spread_widen_multiple"] if fq else 0
    return {
        "entry_trigger": f"after {start} ET, underlying breaks the {orm}-min opening-range {side}",
        "entry_order": f"BUY {n} x limit between mid {mid:.2f} and ask {ask:.2f}, never above max debit {max_debit:.2f}; "
                       f"cancel after {p['fill_timeout_seconds']}s; at most 2 revisions; never market, never chase",
        "entry_requires": f"live spread <= {cfg['fill_quality']['max_morning_spread_pct']}% of mid",
        "entry_deadline": p["entry_deadline"],
        "target": f"+{p['target_pct']:g}% (mid {mid * (1 + p['target_pct'] / 100):.2f}); stretch +{p['target2_pct']:g}% "
                  f"({mid * (1 + p['target2_pct'] / 100):.2f}); exit with a limit at/near the bid",
        "stop": f"-{p['stop_pct']:g}% (mid {mid * (1 - p['stop_pct'] / 100):.2f})",
        "invalidation": f"underlying back inside the opening range ({side.lower()} reclaimed), or spread > "
                        f"{p['spread_widen_multiple']}x historical median ({spread_cap:.1f}%)",
        "time_stop": f"{p['time_stop']} ET, never hold past it",
        "max_debit": round(max_debit, 2),
        "est_cost_per_contract": round(ask * 100 + fee, 2),
        "est_round_trip_fees": round(2 * fee * max(n, 1), 2),
    }
