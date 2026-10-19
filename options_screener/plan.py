"""Per-candidate morning plan: entry trigger, target, invalidation, time stop, cost."""
from __future__ import annotations

from .fill_quality import commission_per_side
from .models import Candidate


def build(c: Candidate, cfg: dict) -> dict:
    p, snap, fq = cfg["plan"], c.snapshot, c.fill
    n = cfg["contract"]["contracts"]
    mid = snap.mid or 0.0
    side = "HIGH" if c.direction == "bull" else "LOW"
    orm = p["entry_after_minutes"]
    commission = commission_per_side(n, cfg["costs"])
    return {
        "entry_trigger": f"after 9:{30 + orm:02d} ET, underlying breaks the {orm}-min opening-range {side}",
        "entry_order": f"BUY limit at mid (est {mid:.2f}); cancel after {p['fill_timeout_seconds']}s; never market, never chase",
        "entry_requires": f"live spread <= {cfg['fill_quality']['max_morning_spread_pct']}% of mid",
        "entry_deadline": p["entry_deadline"],
        "target": f"+{p['target_pct']}% (mid {mid * (1 + p['target_pct'] / 100):.2f}); stretch +{p['target2_pct']}% "
                  f"({mid * (1 + p['target2_pct'] / 100):.2f}); exit with a limit at/near the bid",
        "stop": f"-{p['stop_pct']}% (mid {mid * (1 - p['stop_pct'] / 100):.2f})",
        "invalidation": f"underlying back inside the opening range ({side.lower()} reclaimed), or spread > "
                        f"{p['spread_widen_multiple']}x historical median ({(fq.median_spread_pct or 0) * p['spread_widen_multiple']:.1f}%)",
        "time_stop": f"{p['time_stop']} ET, never hold past it",
        "est_cost_per_contract": round((snap.ask or mid) * 100 + commission / n, 2),
        "est_round_trip_commission": round(2 * commission, 2),
    }
