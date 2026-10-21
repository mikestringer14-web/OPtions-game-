"""Black-Scholes engine for the options partner bot.

Stdlib only (no scipy), so it runs anywhere Python does.
"""
from math import erf, exp, log, pi, sqrt


def norm_cdf(x):
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def norm_pdf(x):
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def bs(S, K, T, r, sigma, q=0.0, kind="call"):
    d1 = (log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    if kind == "call":
        price = S * exp(-q * T) * norm_cdf(d1) - K * exp(-r * T) * norm_cdf(d2)
        delta = exp(-q * T) * norm_cdf(d1)
        theta = (-S * norm_pdf(d1) * sigma * exp(-q * T) / (2 * sqrt(T))
                 - r * K * exp(-r * T) * norm_cdf(d2) + q * S * exp(-q * T) * norm_cdf(d1)) / 365
        p_itm = norm_cdf(d2)
    else:
        price = K * exp(-r * T) * norm_cdf(-d2) - S * exp(-q * T) * norm_cdf(-d1)
        delta = exp(-q * T) * (norm_cdf(d1) - 1)
        theta = (-S * norm_pdf(d1) * sigma * exp(-q * T) / (2 * sqrt(T))
                 + r * K * exp(-r * T) * norm_cdf(-d2) - q * S * exp(-q * T) * norm_cdf(-d1)) / 365
        p_itm = norm_cdf(-d2)
    gamma = exp(-q * T) * norm_pdf(d1) / (S * sigma * sqrt(T))
    vega = S * exp(-q * T) * norm_pdf(d1) * sqrt(T) / 100
    return dict(price=price, delta=delta, gamma=gamma, theta=theta, vega=vega, p_itm=p_itm)


def implied_vol(market_price, S, K, T, r, q=0.0, kind="call"):
    lo, hi = 0.01, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if bs(S, K, T, r, mid, q, kind)["price"] > market_price:
            hi = mid
        else:
            lo = mid
    return mid


def position(legs, S, r, q=0.0):
    """legs: list of dicts {K, T, sigma, kind, qty}; qty + for long, - for short (contracts)."""
    total = dict(price=0, delta=0, gamma=0, theta=0, vega=0)
    for L in legs:
        g = bs(S, L["K"], L["T"], r, L["sigma"], q, L["kind"])
        for k in total:
            total[k] += g[k] * L["qty"] * 100
    return total


def pnl_grid(legs, S_now, r, moves=(-0.10, -0.05, -0.02, 0, 0.02, 0.05, 0.10),
             days_forward=0, iv_shift=0.0, q=0.0):
    """P&L of the position at different stock moves, days forward, and IV shifts."""
    entry = position(legs, S_now, r, q)["price"]
    out = {}
    for m in moves:
        S = S_now * (1 + m)
        shifted = []
        for L in legs:
            T = max(L["T"] - days_forward / 365, 1e-6)
            shifted.append({**L, "T": T, "sigma": max(L["sigma"] + iv_shift, 0.01)})
        out[f"{m:+.0%}"] = round(position(shifted, S, r, q)["price"] - entry, 2)
    return out
