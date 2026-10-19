"""Trade metrics and bootstrap."""
from __future__ import annotations

import random
from collections import defaultdict
from statistics import mean
from typing import Callable, Iterable, Optional


def metrics(trades: list, days: Optional[int] = None) -> dict:
    attempted = [t for t in trades if t.status in ("filled", "no_fill")]
    filled = [t for t in trades if t.filled]
    wins = [t for t in filled if t.pnl > 0]
    losses = [t for t in filled if t.pnl <= 0]
    gw, gl = sum(t.pnl for t in wins), -sum(t.pnl for t in losses)
    eq, peak, dd = 0.0, 0.0, 0.0
    for t in sorted(filled, key=lambda x: (x.day, x.filled_at or "")):
        eq += t.pnl
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "signals": len(trades),
        "entries_attempted": len(attempted),
        "filled": len(filled),
        "fill_rate": len(filled) / len(attempted) if attempted else None,
        "hit_rate_target": sum(t.hit_target_mid for t in filled) / len(filled) if filled else None,
        "win_rate": len(wins) / len(filled) if filled else None,
        "avg_win": gw / len(wins) if wins else None,
        "avg_loss": -gl / len(losses) if losses else None,
        "expectancy_usd": mean(t.pnl for t in filled) if filled else None,
        "expectancy_ret": mean(t.net_ret for t in filled) if filled else None,
        "profit_factor": (gw / gl) if gl > 0 else (float("inf") if gw > 0 else None),
        "max_drawdown_usd": dd,
        "total_pnl": sum(t.pnl for t in filled),
        "avg_minutes_to_fill": mean(t.minutes_to_fill for t in filled) if filled else None,
        "avg_minutes_held": mean(t.minutes_held for t in filled) if filled else None,
        "trades_per_day": len(filled) / days if days else None,
    }


def split(trades: list, key: Callable) -> dict:
    groups = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)
    return {k: metrics(v) for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))}


def bootstrap(values: Iterable[float], n: int = 5000, seed: int = 11) -> Optional[dict]:
    vals = list(values)
    if len(vals) < 5:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    return {"p5": means[int(0.05 * n)], "p50": means[n // 2], "p95": means[int(0.95 * n)],
            "prob_mean_gt_0": sum(m > 0 for m in means) / n}
