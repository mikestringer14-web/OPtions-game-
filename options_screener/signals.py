"""(A) catalyst and (B) move-potential signals, each scored 0..1."""
from __future__ import annotations

from datetime import date, time
from typing import Optional

from . import pricing
from .models import Bar, OptionStats


def clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- (A) catalyst

def catalyst_score(symbol: str, asof: date, target: date, earnings: Optional[list[date]],
                   news_counts: Optional[list[int]], cfg: dict) -> tuple[float, str, bool]:
    """Returns (score, label, is_earnings)."""
    best, label, is_earn = 0.0, "none", False
    if earnings:
        for d in earnings:
            if d == asof:
                best, label, is_earn = 1.0, f"earnings {d} (after close if reported then; time not in source)", True
            elif d == target:
                best, label, is_earn = 1.0, f"earnings {d} (before open if reported then; time not in source)", True
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
    if not stats or not stats.option_volume or not stats.avg_option_volume_20d:
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
    change = (stats.iv - stats.iv_prev) if stats.iv_prev else None
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


def opening_range(bars: list[Bar], minutes: int) -> Optional[tuple[float, float]]:
    end = time(9, 30 + minutes) if minutes < 30 else time(10, 0)
    rng = [b for b in bars if time(9, 30) <= b.et_time < end]
    if not rng:
        return None
    return max(b.high for b in rng), min(b.low for b in rng)


def morning_option_move_proxy(bars: list[Bar], iv: float, cfg: dict) -> Optional[float]:
    """Best option % move within 60 min after an opening-range break (UNDERLYING PROXY:
    option move ~= delta x underlying move / option price, ATM, proxy DTE)."""
    plan = cfg["plan"]
    orng = opening_range(bars, plan["entry_after_minutes"])
    if not orng:
        return None
    orh, orl = orng
    after = [b for b in bars if b.et_time >= time(9, 30 + plan["entry_after_minutes"])]
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


def move_potential_rate(sessions: list[list[Bar]], iv: float, cfg: dict) -> Optional[float]:
    moves = [m for m in (morning_option_move_proxy(s, iv, cfg) for s in sessions) if m is not None]
    if len(moves) < 5:
        return None
    return sum(1 for m in moves if m >= cfg["signals"]["move_target_pct"]) / len(moves)


def weighted(scores: dict, cfg: dict, keys: list[str]) -> Optional[float]:
    w = cfg["signals"]
    num = den = 0.0
    for k in keys:
        if scores.get(k) is not None:
            num += w[f"weight_{k}"] * scores[k]
            den += w[f"weight_{k}"]
    return num / den if den else None
