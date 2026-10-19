"""(C) FILL-QUALITY gate, per specific strike + expiry, from the previous 1-5 trading days.

VERIFIED = spreads come from real bid/ask quotes. PROXY = only trade bars exist, so the spread
is estimated from each bar's high-low range. Checks with no data at all are N/A (not counted as
a pass in the score) and are listed so the report shows what could not be checked.
"""
from __future__ import annotations

from datetime import time
from statistics import median
from typing import Callable, Optional

from .models import Bar, Check, Contract, FillQuality, OptionSnapshot

MORNING = (time(9, 35), time(10, 30))
FIRST_HOUR = (time(9, 30), time(10, 30))
CLOSE_WINDOW = (time(15, 55), time(16, 0))


def _in(b: Bar, window) -> bool:
    t = b.et_time
    return window[0] <= t < window[1]


def bar_spread_pct(b: Bar) -> tuple[Optional[float], bool]:
    """(spread % of mid, from_quotes). Falls back to (high-low)/close when no quotes."""
    if b.bid is not None and b.ask is not None and b.ask > 0 and b.bid >= 0:
        mid = (b.bid + b.ask) / 2
        if mid > 0:
            return (b.ask - b.bid) / mid * 100, True
    if b.close and b.close > 0 and b.high >= b.low and (b.volume or 0) > 0:
        return (b.high - b.low) / b.close * 100, False
    return None, False


def commission_per_side(n: int, costs: dict) -> float:
    return max(costs["min_commission_per_order"], costs["commission_per_contract"] * n) + costs["other_fees_per_contract"] * n


def round_trip_cost_pct(spread_pct: float, mid: float, n: int, costs: dict, cost_mult: float = 1.0) -> float:
    """Buy at the ask + sell at the bid = one full spread, plus slippage and both commissions."""
    commissions = 2 * commission_per_side(n, costs)
    commission_pct = commissions / (mid * 100 * n) * 100 if mid > 0 else float("inf")
    return (spread_pct + 2 * costs.get("extra_slippage_pct", 0.0)) * cost_mult + commission_pct * cost_mult


def _check(name, value, ok, threshold, note="") -> Check:
    if value is None:
        return Check(name, None, threshold, "N/A", note or "no data")
    return Check(name, round(value, 3), threshold, "PASS" if ok else "FAIL", note)


def evaluate(contract: Contract, snap: Optional[OptionSnapshot], days: list[list[Bar]], *, has_quotes: bool,
             has_trade_counts: bool, cfg: dict, source: str) -> FillQuality:
    fq, costs = cfg["fill_quality"], cfg["costs"]
    n = cfg["contract"]["contracts"]
    target = cfg["plan"]["target_pct"]
    traded_days = [d for d in days if any((b.volume or 0) > 0 for b in d)]

    morning_spreads, close_spreads, from_quotes = [], [], []
    first_hour_vol, day_vol, active, gaps = [], [], [], []
    for bars in days:
        first_hour_vol.append(sum(b.volume or 0 for b in bars if _in(b, FIRST_HOUR)))
        day_vol.append(sum(b.volume or 0 for b in bars))
        morning = [b for b in bars if _in(b, MORNING)]
        active.append(sum(1 for b in morning if (b.volume or 0) > 0 or (b.trades or 0) > 0))
        for b in morning:
            s, q = bar_spread_pct(b)
            if s is not None:
                morning_spreads.append(s)
                from_quotes.append(q)
            if has_trade_counts:
                gaps.append(60.0 / b.trades if b.trades else 60.0)
        for b in bars:
            if _in(b, CLOSE_WINDOW):
                s, _ = bar_spread_pct(b)
                if s is not None:
                    close_spreads.append(s)

    verified = has_quotes and bool(from_quotes) and all(from_quotes)
    spread_note = "quotes" if verified else "PROXY: bar high-low range"
    no_bars = "no bars in lookback" if not traded_days else ""
    med_spread = median(morning_spreads) if morning_spreads else None
    med_close = median(close_spreads) if close_spreads else None
    fh = median(first_hour_vol) if days else None
    dv = median(day_vol) if days else None
    act = median(active) if days else None
    med_gap = median(gaps) if gaps else None

    checks = [
        _check("morning_spread_pct", med_spread, med_spread is not None and med_spread <= fq["max_morning_spread_pct"],
               f"<= {fq['max_morning_spread_pct']}", spread_note if med_spread is not None else no_bars),
        _check("close_spread_pct", med_close, med_close is not None and med_close <= fq["max_close_spread_pct"],
               f"<= {fq['max_close_spread_pct']}", spread_note if med_close is not None else no_bars),
        _check("first_hour_volume", fh, fh is not None and fh >= fq["min_first_hour_volume"],
               f">= {fq['min_first_hour_volume']}"),
        _check("day_volume", dv, dv is not None and dv >= fq["min_day_volume"], f">= {fq['min_day_volume']}"),
        _check("active_first_hour_minutes", act, act is not None and act >= fq["min_active_first_hour_minutes"],
               f">= {fq['min_active_first_hour_minutes']} of 55"),
    ]
    oi = snap.open_interest if snap else None
    checks.append(_check("open_interest", oi, oi is not None and oi >= fq["min_open_interest"],
                         f">= {fq['min_open_interest']}"))
    prev = snap.prev_open_interest if snap else None
    drop = (prev - oi) / prev * 100 if (oi is not None and prev) else None
    checks.append(_check("oi_drop_pct", drop, drop is not None and drop <= fq["max_oi_drop_pct"],
                         f"<= {fq['max_oi_drop_pct']}", "" if drop is not None else "no prior-day OI"))
    checks.append(_check("median_seconds_between_prints", med_gap,
                         med_gap is not None and med_gap <= fq["max_median_seconds_between_prints"],
                         f"<= {fq['max_median_seconds_between_prints']}",
                         "from per-minute print counts" if med_gap is not None else "no trade-count data"))
    need = fq["depth_multiple"] * n
    depth = None
    if snap and snap.bid_size is not None and snap.ask_size is not None:
        depth = min(snap.bid_size, snap.ask_size)
    checks.append(_check("displayed_depth", depth, depth is not None and depth >= need, f">= {need}"))
    mid = snap.mid if snap else None
    rt = round_trip_cost_pct(med_spread, mid, n, costs) if (med_spread is not None and mid) else None
    limit = fq["max_round_trip_cost_share_of_target"] * target
    checks.append(_check("round_trip_cost_pct", rt, rt is not None and rt <= limit,
                         f"<= {limit:.2f} ({fq['max_round_trip_cost_share_of_target']:.0%} of +{target}%)"))

    return FillQuality(contract=contract, checks=checks, source=source, verified=verified,
                       median_spread_pct=med_spread, first_hour_volume=fh, open_interest=oi,
                       prints_per_min=(60.0 / med_gap) if med_gap else None, round_trip_cost_pct=rt)


# ---------------------------------------------------------------- contract choice

def eligible(snaps: list[OptionSnapshot], right: str, on, cfg: dict) -> list[OptionSnapshot]:
    c = cfg["contract"]
    max_prem = cfg["universe"]["max_premium_per_contract"]
    min_dte = 0 if c["allow_0dte"] else max(1, c["dte_min"])
    out = []
    for s in snaps:
        k = s.contract
        if k.right != right or s.delta is None or s.ask is None:
            continue
        dte = k.dte(on)
        if not (min_dte <= dte <= c["dte_max"]):
            continue
        if not (c["delta_min"] <= abs(s.delta) <= c["delta_max"]):
            continue
        if s.ask * 100 > max_prem:
            continue
        out.append(s)
    return out


def choose_contract(snaps: list[OptionSnapshot], right: str, on, cfg: dict,
                    assess: Callable[[OptionSnapshot], FillQuality], max_alternatives: int = 6):
    """Ideal = delta nearest the middle of the band, then most volume. If it fails (C), try nearby
    strikes/expiries and take the passing one with the tightest spread and most volume."""
    pool = eligible(snaps, right, on, cfg)
    if not pool:
        return None, None
    mid_delta = (cfg["contract"]["delta_min"] + cfg["contract"]["delta_max"]) / 2
    pool.sort(key=lambda s: (abs(abs(s.delta) - mid_delta), -(s.volume or 0)))
    ideal = pool[0]
    fq = assess(ideal)
    if fq.passed:
        return ideal, fq
    alts = sorted(pool[1:], key=lambda s: (abs(s.contract.strike - ideal.contract.strike),
                                           abs((s.contract.expiry - ideal.contract.expiry).days)))[:max_alternatives]
    passing = []
    for s in alts:
        f = assess(s)
        if f.passed:
            passing.append((s, f))
    if passing:
        s, f = min(passing, key=lambda p: (p[1].median_spread_pct or 99, -(p[1].first_hour_volume or 0)))
        f.substituted_from = ideal.contract.label()
        return s, f
    return ideal, fq
