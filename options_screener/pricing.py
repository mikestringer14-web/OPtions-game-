"""Black-Scholes helpers. Used ONLY to synthesize contracts/prices where no real option data
exists (mock data, underlying-proxy backtests). Anything built with these is labeled PROXY."""
from __future__ import annotations

import math

RATE = 0.04


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1(s: float, k: float, t: float, vol: float, r: float = RATE) -> float:
    return (math.log(s / k) + (r + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))


def price(s: float, k: float, t: float, vol: float, right: str, r: float = RATE) -> float:
    if t <= 0 or vol <= 0:
        return max(0.0, s - k) if right == "C" else max(0.0, k - s)
    d1 = _d1(s, k, t, vol, r)
    d2 = d1 - vol * math.sqrt(t)
    if right == "C":
        return s * _ncdf(d1) - k * math.exp(-r * t) * _ncdf(d2)
    return k * math.exp(-r * t) * _ncdf(-d2) - s * _ncdf(-d1)


def delta(s: float, k: float, t: float, vol: float, right: str, r: float = RATE) -> float:
    if t <= 0 or vol <= 0:
        return (1.0 if s > k else 0.0) if right == "C" else (-1.0 if s < k else 0.0)
    d1 = _d1(s, k, t, vol, r)
    return _ncdf(d1) if right == "C" else _ncdf(d1) - 1.0


def year_fraction(days: float) -> float:
    return max(days, 0.0) / 365.0


def realized_vol(closes: list[float], n: int = 20) -> float:
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(max(1, len(closes) - n), len(closes))
            if closes[i - 1] > 0]
    if len(rets) < 2:
        return 0.3
    m = sum(rets) / len(rets)
    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
    return max(0.05, math.sqrt(var) * math.sqrt(252))
