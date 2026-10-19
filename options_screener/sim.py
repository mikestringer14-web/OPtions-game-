"""Simulate the morning plan on one session's 1-minute option + underlying bars.

Fill model (deliberately pessimistic):
  * The order rests at mid. It only "fills" if a bar inside the timeout window traded at or
    through the limit (low <= limit) with volume >= 10x our size; otherwise it is a NO FILL.
  * Even when filled we charge the ask (mid + half spread) on entry and receive the bid
    (mid - half spread) on exit, times the cost multiplier, plus commissions both ways.
  * Within a bar, the stop is checked before the target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

from .fill_quality import bar_spread_pct, commission_per_side
from .models import Bar, Contract
from .signals import opening_range


@dataclass
class Trade:
    day: date
    symbol: str
    contract: str
    right: str
    dte: int
    direction: str
    earnings: bool
    score: float
    fq_score: float
    status: str                       # filled | no_fill | no_trigger | skipped_spread | no_data
    exit_reason: str = ""
    entry_mid: Optional[float] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    placed_at: Optional[str] = None
    filled_at: Optional[str] = None
    exited_at: Optional[str] = None
    minutes_to_fill: Optional[float] = None
    minutes_held: Optional[float] = None
    hit_target_mid: bool = False
    hit_stretch_mid: bool = False     # +target2 (10%) reached before the stop / time stop (recorded, not traded)
    contracts: int = 1
    pnl: float = 0.0
    net_ret: float = 0.0
    tags: dict = field(default_factory=dict)

    @property
    def filled(self) -> bool:
        return self.status == "filled"


def _minute(t: time) -> int:
    return t.hour * 60 + t.minute


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _spread_abs(b: Bar, proxy_pct: float, quotes: bool) -> float:
    s, from_quotes = bar_spread_pct(b)
    mid = (b.bid + b.ask) / 2 if (quotes and b.bid is not None and b.ask is not None) else b.close
    if quotes and from_quotes and s is not None:
        return s / 100 * mid
    return proxy_pct / 100 * mid


def _mid(b: Bar, quotes: bool) -> float:
    if quotes and b.bid is not None and b.ask is not None and b.ask > 0:
        return (b.bid + b.ask) / 2
    return b.close


def _reaches_stretch(opt: dict, m0: int, tstop: int, entry_mid: float, p: dict) -> bool:
    """Bookkeeping only: would +target2 have printed before the stop or the time stop?"""
    stretch = entry_mid * (1 + p.get("target2_pct", 10.0) / 100)
    stop = entry_mid * (1 - p["stop_pct"] / 100)
    for m in range(m0, tstop):
        b = opt.get(m)
        if b is None:
            continue
        if b.low <= stop:
            return False
        if b.high >= stretch:
            return True
    return False


def simulate(*, day: date, contract: Contract, direction: str, option_bars: list[Bar], underlying_bars: list[Bar],
             cfg: dict, hist_median_spread_pct: Optional[float], quotes: bool, entry_delay_min: int = 0,
             cost_mult: float = 1.0, overrides: Optional[dict] = None, meta: Optional[dict] = None) -> Trade:
    p = {**cfg["plan"], **(overrides or {})}
    fq, costs = cfg["fill_quality"], cfg["costs"]
    meta = meta or {}
    n = meta.get("contracts") or cfg["contract"]["contracts"]
    tr = Trade(day=day, symbol=contract.symbol, contract=contract.label(), right=contract.right,
               dte=contract.dte(day), direction=direction, earnings=meta.get("earnings", False),
               score=meta.get("score", 0.0), fq_score=meta.get("fq_score", 0.0), status="no_data", tags=meta.get("tags", {}),
               contracts=n)
    if not option_bars or not underlying_bars:
        return tr
    orng = opening_range(underlying_bars, p["entry_after_minutes"])
    if not orng:
        return tr
    orh, orl = orng
    proxy = fq["proxy_spread_pct"]
    opt = {_minute(b.et_time): b for b in option_bars}
    und = {_minute(b.et_time): b for b in underlying_bars}
    start = _minute(time(9, 30)) + p["entry_after_minutes"]
    deadline, tstop = _minute(_hm(p["entry_deadline"])), _minute(_hm(p["time_stop"]))
    timeout_bars = max(1, round(p["fill_timeout_seconds"] / 60))

    trigger = None
    for m in range(start, deadline + 1):
        u = und.get(m)
        if u and ((direction == "bull" and u.close > orh) or (direction == "bear" and u.close < orl)):
            trigger = m
            break
    if trigger is None:
        tr.status = "no_trigger"
        return tr
    place = trigger + entry_delay_min
    ob = opt.get(place) or next((opt[k] for k in sorted(opt, reverse=True) if k <= place), None)
    if ob is None:
        tr.status = "no_data"
        return tr
    limit = _mid(ob, quotes)
    spread = _spread_abs(ob, proxy, quotes)
    tr.entry_mid, tr.placed_at = round(limit, 4), f"{place // 60:02d}:{place % 60:02d}"
    if limit <= 0 or spread / limit * 100 > fq["max_morning_spread_pct"]:
        tr.status = "skipped_spread"
        return tr

    fill_m = None
    for m in range(place + 1, place + 1 + timeout_bars):
        b = opt.get(m)
        if b and b.low <= limit and (b.volume or 0) >= fq["depth_multiple"] * n and (b.trades is None or b.trades > 0):
            fill_m = m
            break
    if fill_m is None:
        tr.status = "no_fill"
        return tr
    slip = costs.get("extra_slippage_pct", 0.0) / 100 * limit
    entry = limit + (spread / 2 + slip) * cost_mult
    tr.status, tr.entry_price = "filled", round(entry, 4)
    tr.filled_at, tr.minutes_to_fill = f"{fill_m // 60:02d}:{fill_m % 60:02d}", float(fill_m - place)

    target_mid = limit * (1 + p["target_pct"] / 100)
    stop_mid = limit * (1 - p["stop_pct"] / 100)
    widen_limit = (hist_median_spread_pct or proxy) * p["spread_widen_multiple"]
    exit_px, reason, exit_m = None, "", None
    last_b = opt[fill_m]
    for m in range(fill_m + 1, tstop + 1):
        b = opt.get(m)
        if b is None:
            continue
        last_b = b
        half = _spread_abs(b, proxy, quotes) / 2 * cost_mult
        mid_b = _mid(b, quotes)
        if m >= tstop:
            exit_px, reason, exit_m = b.open - half, "time_stop", m
            break
        if b.low <= stop_mid:
            exit_px, reason, exit_m = min(b.open, stop_mid) - half, "stop", m
            break
        if b.high >= target_mid and (b.volume or 0) >= fq["depth_multiple"] * n:
            tr.hit_target_mid = True
            exit_px, reason, exit_m = target_mid - half, "target", m
            tr.hit_stretch_mid = _reaches_stretch(opt, m, tstop, limit, p)
            break
        u = und.get(m)
        if u and ((direction == "bull" and u.close < orh) or (direction == "bear" and u.close > orl)):
            exit_px, reason, exit_m = b.close - half, "range_reclaimed", m
            break
        if mid_b > 0 and _spread_abs(b, proxy, quotes) / mid_b * 100 > widen_limit:
            exit_px, reason, exit_m = b.close - half, "spread_widened", m
            break
    if exit_px is None:
        half = _spread_abs(last_b, proxy, quotes) / 2 * cost_mult
        exit_px, reason, exit_m = last_b.close - half, "end_of_data", _minute(last_b.et_time)
    exit_px = max(0.0, exit_px - slip * cost_mult)
    commissions = 2 * commission_per_side(n, costs) * cost_mult
    tr.exit_price, tr.exit_reason = round(exit_px, 4), reason
    tr.exited_at, tr.minutes_held = f"{exit_m // 60:02d}:{exit_m % 60:02d}", float(exit_m - fill_m)
    tr.pnl = round((exit_px - entry) * 100 * n - commissions, 2)
    tr.net_ret = tr.pnl / (entry * 100 * n) if entry > 0 else 0.0
    return tr
