"""(A) catalyst and (B) move-potential signals, each scored 0..1."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from . import pricing
from .models import ET, Bar, OptionStats

log = logging.getLogger("options_screener.signals")
ONE_MIN = timedelta(minutes=1)


def clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- (A) catalyst

def _earning(e) -> tuple[date, Optional[str]]:
    """Providers return a date, or (date, timing) where timing is 'bmo'/'amc' only if the SOURCE says so."""
    if isinstance(e, tuple):
        d, timing = e[0], (e[1] or "").lower() or None
        return d, timing if timing in ("bmo", "amc") else None
    return e, None


def catalyst_score(symbol: str, asof: date, target: date, earnings: Optional[list],
                   news_counts: Optional[list[int]], cfg: dict) -> tuple[float, str, bool]:
    """Returns (score, label, is_earnings). BMO/AMC appears only when the source provides it;
    otherwise the label says 'time unverified' (and the screen adds an IV-crush warning)."""
    best, label, is_earn = 0.0, "none", False
    if earnings:
        for e in earnings:
            d, timing = _earning(e)
            if d in (asof, target):
                when = timing.upper() if timing else "time unverified"
                best, label, is_earn = 1.0, f"earnings {d} ({when})", True
    for ev in cfg.get("events", []) or []:
        if str(ev.get("date")) == target.isoformat() and best < 0.6:
            best, label = 0.6, f"scheduled: {ev.get('name', 'event')}"
    if news_counts and len(news_counts) >= 5:
        hist, today = news_counts[:-1], news_counts[-1]
        avg = sum(hist) / len(hist) if hist else 0
        ratio = today / avg if avg > 0 else (float("inf") if today else 0)
        if ratio >= cfg["signals"]["news_spike_ratio"]:
            s = 0.5 + 0.5 * clip((ratio - cfg["signals"]["news_spike_ratio"]) / 3)
            if s > best:
                best, label = s, f"news spike x{ratio:.1f}"
    return best, label, is_earn


# ---------------------------------------------------------------- (B) signals

def unusual_volume_score(stats: Optional[OptionStats]) -> Optional[float]:
    if not stats or stats.option_volume is None or not stats.avg_option_volume_20d:
        return None
    ratio = stats.option_volume / stats.avg_option_volume_20d
    s = clip((ratio - 1.0) / 2.0)
    if stats.open_interest:
        s = (s + clip((stats.option_volume / stats.open_interest) / 0.5)) / 2
    return s


def iv_metrics(stats: Optional[OptionStats]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(score, iv_rank 0..1, day-over-day IV change)."""
    if not stats or stats.iv is None:
        return None, None, None
    rank = None
    hist = [v for v in stats.iv_history if v is not None]
    if len(hist) >= 20 and max(hist) > min(hist):
        rank = clip((stats.iv - min(hist)) / (max(hist) - min(hist)))
    change = (stats.iv - stats.iv_prev) if stats.iv_prev is not None else None
    parts = []
    if rank is not None:
        parts.append(1.0 - rank)                 # cheaper options score higher
    if change is not None:
        parts.append(clip(change / 0.10))        # rising IV = anticipation
    return (sum(parts) / len(parts) if parts else None), rank, change


def momentum(daily: list[Bar], last_session: list[Bar]) -> tuple[Optional[float], float]:
    """(score 0..1, signed direction value -1..1)."""
    if len(daily) < 21:
        return None, 0.0
    window = daily[-20:]
    hi, lo, close = max(b.high for b in window), min(b.low for b in window), daily[-1].close
    pos = (close - lo) / (hi - lo) if hi > lo else 0.5
    last_hour = [b for b in last_session if b.et_time >= time(15, 0)]
    lh_ret = (last_hour[-1].close / last_hour[0].open - 1) if len(last_hour) >= 2 and last_hour[0].open else 0.0
    gaps = [abs(daily[i].open / daily[i - 1].close - 1) for i in range(max(1, len(daily) - 60), len(daily))
            if daily[i - 1].close]
    gap_tendency = clip((sum(gaps) / len(gaps)) / 0.01) if gaps else 0.0
    direction = 0.6 * clip(lh_ret / 0.005, -1, 1) + 0.4 * (pos - 0.5) * 2
    score = (abs(pos - 0.5) * 2 + clip(abs(lh_ret) / 0.005) + gap_tendency) / 3
    return score, direction


def at_et(day: date, hhmm: str | time) -> datetime:
    t = hhmm if isinstance(hhmm, time) else time(*map(int, hhmm.split(":")))
    return datetime.combine(day, t, tzinfo=ET)


def after_open(day: date, minutes: int) -> datetime:
    """9:30 ET + minutes, as a datetime (works for any number of minutes)."""
    return datetime.combine(day, time(9, 30), tzinfo=ET) + timedelta(minutes=minutes)


def bar_gaps(bars: list[Bar], step: timedelta = ONE_MIN) -> list[tuple[datetime, int]]:
    """(timestamp, missing minutes) wherever consecutive bars are further apart than `step`."""
    out = []
    for a, b in zip(bars, bars[1:], strict=False):
        d = b.ts - a.ts
        if d > step:
            out.append((b.ts, int(d / step) - 1))
    return out


def opening_range(bars: list[Bar], minutes: int) -> Optional[tuple[float, float]]:
    if not bars:
        return None
    day = bars[0].ts.astimezone(ET).date()
    start, end = after_open(day, 0), after_open(day, minutes)
    rng = [b for b in bars if start <= b.ts < end]
    if not rng:
        return None
    return max(b.high for b in rng), min(b.low for b in rng)


@dataclass
class MoveResult:
    side: Optional[str]
    exit_reason: str                 # target | stop | time_stop | end_of_data | no_trigger
    ret_pct: float                   # option return at exit (MODEL ESTIMATE)
    hit_target: bool                 # +target reached before the stop / time stop
    hit_stretch: bool                # +stretch reached before the stop / time stop
    entry_ts: Optional[datetime] = None
    exit_ts: Optional[datetime] = None
    gaps: list = field(default_factory=list)


def morning_option_move_proxy(bars: list[Bar], iv: float, cfg: dict) -> Optional[MoveResult]:
    """UNDERLYING PROXY for one morning, walked bar by bar like the real plan:
    enter at the close of the first bar (after the opening range, before the entry deadline)
    that breaks the range; price an ATM option with Black-Scholes (proxy DTE, constant IV,
    time decay per minute); exit at the FIRST of -stop, +target, or the time stop. Within a bar
    the stop (adverse extreme) is checked before the target (favourable extreme)."""
    if not bars:
        return None
    plan, sig = cfg["plan"], cfg["signals"]
    orng = opening_range(bars, plan["entry_after_minutes"])
    if not orng:
        return None
    orh, orl = orng
    day = bars[0].ts.astimezone(ET).date()
    start, deadline, tstop = after_open(day, plan["entry_after_minutes"]), at_et(day, plan["entry_deadline"]), at_et(day, plan["time_stop"])
    gaps = bar_gaps([b for b in bars if b.ts <= tstop])
    if gaps:
        log.warning("%s: %d gap(s) in 1-minute bars before the time stop", day, len(gaps))
    entry = next((b for b in bars if start <= b.ts <= deadline and (b.close > orh or b.close < orl)), None)
    if entry is None:
        return MoveResult(None, "no_trigger", 0.0, False, False, gaps=gaps)
    side = "bull" if entry.close > orh else "bear"
    right = "C" if side == "bull" else "P"
    s0, k, dte_min = entry.close, entry.close, sig["proxy_dte_days"] * 24 * 60
    opt0 = pricing.price(s0, k, pricing.year_fraction(sig["proxy_dte_days"]), iv, right)
    if opt0 <= 0:
        return MoveResult(side, "end_of_data", 0.0, False, False, entry.ts, entry.ts, gaps)
    target, stretch, stop = plan["target_pct"], plan.get("target2_pct", 10.0), plan["stop_pct"]
    res = MoveResult(side, "end_of_data", 0.0, False, False, entry.ts, None, gaps)
    done = False
    for b in bars:
        if b.ts <= entry.ts:
            continue
        t = pricing.year_fraction((dte_min - (b.ts - entry.ts).total_seconds() / 60) / (24 * 60))
        adverse, favourable = (b.low, b.high) if side == "bull" else (b.high, b.low)
        r_adv = pricing.price(adverse, k, t, iv, right) / opt0 * 100 - 100
        r_fav = pricing.price(favourable, k, t, iv, right) / opt0 * 100 - 100
        if b.ts >= tstop:
            if not done:
                res.exit_reason, res.exit_ts = "time_stop", b.ts
                res.ret_pct = pricing.price(b.open, k, t, iv, right) / opt0 * 100 - 100
            break
        if r_adv <= -stop:
            if not done:
                res.exit_reason, res.ret_pct, res.exit_ts = "stop", -stop, b.ts
            break                      # stretch bookkeeping ends at the stop too
        if r_fav >= target and not done:
            res.hit_target, res.exit_reason, res.ret_pct, res.exit_ts, done = True, "target", target, b.ts, True
        if r_fav >= stretch:
            res.hit_stretch = True
            break
        if not done:
            res.ret_pct = pricing.price(b.close, k, t, iv, right) / opt0 * 100 - 100
    return res


def morning_option_move_proxy_legacy(bars: list[Bar], iv: float, cfg: dict) -> Optional[float]:
    """LEGACY (kept for comparison only): best option % move within 60 bars after the break.
    Over-optimistic: ignores the stop, the time stop and time decay."""
    plan = cfg["plan"]
    orng = opening_range(bars, plan["entry_after_minutes"])
    if not orng:
        return None
    orh, orl = orng
    day = bars[0].ts.astimezone(ET).date()
    after = [b for b in bars if b.ts >= after_open(day, plan["entry_after_minutes"])]
    for i, b in enumerate(after):
        side = "bull" if b.close > orh else "bear" if b.close < orl else None
        if not side:
            continue
        s0 = b.close
        t = pricing.year_fraction(cfg["signals"]["proxy_dte_days"])
        right = "C" if side == "bull" else "P"
        opt = pricing.price(s0, s0, t, iv, right)
        dlt = abs(pricing.delta(s0, s0, t, iv, right))
        window = after[i + 1:i + 61]
        if not window or opt <= 0:
            return 0.0
        fav = (max(x.high for x in window) - s0) if side == "bull" else (s0 - min(x.low for x in window))
        return max(0.0, dlt * fav / opt * 100)
    return 0.0


def move_potential(sessions: list[list[Bar]], iv: float, cfg: dict) -> dict:
    """Rates over past mornings: new walk-forward proxy (used by gate B) and the legacy one."""
    res = [r for r in (morning_option_move_proxy(s, iv, cfg) for s in sessions) if r is not None]
    legacy = [m for m in (morning_option_move_proxy_legacy(s, iv, cfg) for s in sessions) if m is not None]
    out = {"n": len(res), "rate": None, "stretch_rate": None, "legacy_rate": None,
           "gaps": sum(len(r.gaps) for r in res)}
    if len(res) >= 5:
        out["rate"] = sum(r.hit_target for r in res) / len(res)
        out["stretch_rate"] = sum(r.hit_stretch for r in res) / len(res)
    if len(legacy) >= 5:
        out["legacy_rate"] = sum(1 for m in legacy if m >= cfg["signals"]["move_target_pct"]) / len(legacy)
    return out


def move_potential_rate(sessions: list[list[Bar]], iv: float, cfg: dict) -> Optional[float]:
    return move_potential(sessions, iv, cfg)["rate"]


def weighted(scores: dict, cfg: dict, keys: list[str]) -> Optional[float]:
    w = cfg["signals"]
    num = den = 0.0
    for k in keys:
        if scores.get(k) is not None:
            num += w[f"weight_{k}"] * scores[k]
            den += w[f"weight_{k}"]
    return num / den if den else None
