"""Synthetic contracts and option price paths built from the UNDERLYING. Used for mock data and
for backtests without a historical options provider. Everything built here is PROXY data."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .. import pricing
from ..models import Bar, Contract, OptionSnapshot


def fridays(start: date, end: date) -> list[date]:
    d = start + timedelta(days=(4 - start.weekday()) % 7)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def strike_step(spot: float, cfg: dict) -> float:
    bt = cfg.get("backtest", {})
    return bt.get("strike_step_high", 5.0) if spot > 200 else bt.get("strike_step_low", 1.0)


def synth_chain(symbol: str, spot: float, asof: date, target: date, vol: float, cfg: dict,
                spread_pct: float, n_strikes: int = 8) -> list[OptionSnapshot]:
    c = cfg["contract"]
    step = strike_step(spot, cfg)
    atm = round(spot / step) * step
    expiries = fridays(target + timedelta(days=max(0, c["dte_min"])), target + timedelta(days=c["dte_max"]))
    out = []
    for exp in expiries:
        t = pricing.year_fraction((exp - asof).days)
        for i in range(-n_strikes, n_strikes + 1):
            k = atm + i * step
            if k <= 0:
                continue
            for right in ("C", "P"):
                px = pricing.price(spot, k, t, vol, right)
                if px < 0.05:
                    continue
                half = max(0.005, px * spread_pct / 200)
                out.append(OptionSnapshot(contract=Contract(symbol, exp, k, right), bid=round(px - half, 2),
                                          ask=round(px + half, 2), last=round(px, 2),
                                          delta=round(pricing.delta(spot, k, t, vol, right), 3), iv=vol,
                                          synthetic=True))
    return out


def option_path(contract: Contract, underlying: list[Bar], vol: float, spread_pct: float,
                volume_per_min: float = 0.0, trades_per_min: float = 0.0) -> list[Bar]:
    """Minute option bars priced off the underlying minute bars (Black-Scholes, constant vol)."""
    out = []
    for b in underlying:
        days_left = (datetime.combine(contract.expiry, datetime.min.time(), tzinfo=b.ts.tzinfo) - b.ts).total_seconds() / 86400 + 0.67
        t = pricing.year_fraction(days_left)
        px = {f: pricing.price(getattr(b, f), contract.strike, t, vol, contract.right) for f in ("open", "high", "low", "close")}
        hi, lo = max(px.values()), min(px.values())
        half = max(0.005, px["close"] * spread_pct / 200)
        out.append(Bar(ts=b.ts, open=px["open"], high=hi, low=lo, close=px["close"], volume=volume_per_min,
                       trades=int(trades_per_min) if trades_per_min else None,
                       bid=max(0.0, px["close"] - half), ask=px["close"] + half))
    return out
