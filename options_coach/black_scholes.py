"""Black-Scholes-Merton pricing, Greeks and implied volatility. Standard library only.

Units used everywhere in this package:
  S, K       price in dollars
  T          years (days / 365)
  r, q       continuous rates as decimals (0.04 = 4%)
  sigma      volatility as a decimal (0.30 = 30%)
  theta      dollars per calendar day, per share
  vega       dollars per 1 volatility point, per share
  rho        dollars per 1% rate move, per share

These are European-style prices. US equity options are American, so a deep ITM put or a call
right before an ex-dividend date can be worth a bit more than this (early exercise value).
"""
import math
from dataclasses import dataclass

SQRT_2PI = math.sqrt(2 * math.pi)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _check_kind(kind: str) -> str:
    kind = kind.upper()[:1]
    if kind not in ("C", "P"):
        raise ValueError(f"option type must be C or P, got {kind!r}")
    return kind


def _d1_d2(S, K, T, r, sigma, q):
    vt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vt
    return d1, d1 - vt


def intrinsic(kind: str, S: float, K: float) -> float:
    return max(S - K, 0.0) if _check_kind(kind) == "C" else max(K - S, 0.0)


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    prob_itm: float


def greeks(kind: str, S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> Greeks:
    kind = _check_kind(kind)
    if S <= 0 or K <= 0:
        raise ValueError("S and K must be positive")
    if T <= 0 or sigma <= 0:
        itm = (S > K) if kind == "C" else (S < K)
        delta = (1.0 if itm else 0.0) * (1 if kind == "C" else -1)
        return Greeks(intrinsic(kind, S, K), delta, 0.0, 0.0, 0.0, 0.0, 1.0 if itm else 0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    dq, dr, sqt = math.exp(-q * T), math.exp(-r * T), math.sqrt(T)
    pdf1 = norm_pdf(d1)
    gamma = dq * pdf1 / (S * sigma * sqt)
    vega = S * dq * pdf1 * sqt / 100
    decay = -S * dq * pdf1 * sigma / (2 * sqt)
    if kind == "C":
        price = S * dq * norm_cdf(d1) - K * dr * norm_cdf(d2)
        delta = dq * norm_cdf(d1)
        theta = (decay - r * K * dr * norm_cdf(d2) + q * S * dq * norm_cdf(d1)) / 365
        rho = K * T * dr * norm_cdf(d2) / 100
        prob_itm = norm_cdf(d2)
    else:
        price = K * dr * norm_cdf(-d2) - S * dq * norm_cdf(-d1)
        delta = -dq * norm_cdf(-d1)
        theta = (decay + r * K * dr * norm_cdf(-d2) - q * S * dq * norm_cdf(-d1)) / 365
        rho = -K * T * dr * norm_cdf(-d2) / 100
        prob_itm = norm_cdf(-d2)
    return Greeks(price, delta, gamma, theta, vega, rho, prob_itm)


def price(kind: str, S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    return greeks(kind, S, K, T, r, sigma, q).price


def implied_vol(kind: str, option_price: float, S: float, K: float, T: float, r: float, q: float = 0.0,
                lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-7) -> float:
    """Volatility that makes the model price equal option_price. Bisection, so it always converges."""
    kind = _check_kind(kind)
    if T <= 0:
        raise ValueError("implied vol needs time to expiry > 0")
    floor = price(kind, S, K, T, r, lo, q)
    ceiling = price(kind, S, K, T, r, hi, q)
    if option_price < floor - 1e-9:
        raise ValueError(f"price {option_price:.4f} is below the no-arbitrage floor {floor:.4f} (check the quote)")
    if option_price > ceiling:
        raise ValueError(f"price {option_price:.4f} implies vol above {hi:.0%} (check the quote)")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if price(kind, S, K, T, r, mid, q) > option_price:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def expected_move(S: float, sigma: float, T: float) -> float:
    """One standard deviation move in dollars by expiry (about 68% of outcomes land inside +/- this)."""
    return S * sigma * math.sqrt(max(T, 0.0))


def prob_touch(kind: str, S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """Rule-of-thumb chance the strike gets touched before expiry: about 2x the chance of finishing ITM."""
    return min(1.0, 2 * greeks(kind, S, K, T, r, sigma, q).prob_itm)
