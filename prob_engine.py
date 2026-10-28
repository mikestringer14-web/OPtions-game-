"""Probability engine for defined-risk option trades.

Everything here is a model estimate. Market-implied numbers use option IV and are risk-neutral (they describe
what the market is pricing, not a forecast). Realized numbers swap in 20 day historical vol. Neither model
predicts direction: both use the risk-free drift, so the only thing that changes between them is volatility.

Conventions
- Volatility is a decimal (0.25 = 25%). Days are calendar days, T = days / 365.
- Leg.qty: + long, - short, in contracts. A stock leg's qty is in lots of 100 shares (1 = 100 shares).
- Prices are per share. P&L, EV, max profit and max loss are in dollars for the whole position.
- vega and rho are per 1 percentage point, theta is per calendar day.

Nothing in this module places orders or talks to a broker.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

import numpy as np

SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)
DAYS_PER_YEAR = 365.0
TRADING_DAYS = 252.0


# --------------------------------------------------------------------------- normal distribution

def _erfc_array(x: np.ndarray) -> np.ndarray:
    # Numerical Recipes erfcc, fractional error < 1.2e-7 everywhere. Used only for vectorised (Monte Carlo) work.
    z = np.abs(x)
    t = 1.0 / (1.0 + 0.5 * z)
    poly = (-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (
        0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))))
    r = t * np.exp(poly)
    return np.where(x >= 0, r, 2.0 - r)


def norm_cdf(x):
    if np.ndim(x) == 0:
        return 0.5 * math.erfc(-float(x) / SQRT2)
    return 0.5 * _erfc_array(-np.asarray(x, dtype=float) / SQRT2)


def norm_pdf(x):
    if np.ndim(x) == 0:
        return math.exp(-0.5 * float(x) ** 2) / SQRT2PI
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / SQRT2PI


# --------------------------------------------------------------------------- Black-Scholes

def _d1d2(S, K, T, r, sigma, q):
    sig_t = sigma * np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / sig_t
    return d1, d1 - sig_t


def bs_price(S, K, T, r, sigma, kind: str, q: float = 0.0):
    """Black-Scholes-Merton price with continuous dividend yield q. Works on scalars or numpy arrays.
    T is in years. At or past expiry (T <= 0) or with zero vol it returns intrinsic value."""
    kind = kind.lower()
    if kind not in ("call", "put"):
        raise ValueError("kind must be 'call' or 'put'")
    scalar = all(np.ndim(v) == 0 for v in (S, K, T, sigma))
    S_, K_, T_, sig_ = (np.asarray(v, dtype=float) for v in (S, K, T, sigma))
    intrinsic = np.maximum(S_ - K_, 0.0) if kind == "call" else np.maximum(K_ - S_, 0.0)
    live = (T_ > 1e-12) & (sig_ > 1e-12) & (S_ > 0)
    Ts = np.where(live, T_, 1.0)
    ss = np.where(live, sig_, 0.2)
    Ss = np.where(S_ > 0, S_, 1e-12)
    d1, d2 = _d1d2(Ss, K_, Ts, r, ss, q)
    df_q, df_r = np.exp(-q * Ts), np.exp(-r * Ts)
    if kind == "call":
        px = Ss * df_q * norm_cdf(d1) - K_ * df_r * norm_cdf(d2)
    else:
        px = K_ * df_r * norm_cdf(-d2) - Ss * df_q * norm_cdf(-d1)
    out = np.where(live, px, intrinsic)
    return float(out) if scalar else out


@dataclass
class Greeks:
    delta: float
    gamma: float
    vega: float   # per 1 vol point
    theta: float  # per calendar day
    rho: float    # per 1 rate point

    def scaled(self, k: float) -> "Greeks":
        return Greeks(self.delta * k, self.gamma * k, self.vega * k, self.theta * k, self.rho * k)

    def __add__(self, o: "Greeks") -> "Greeks":
        return Greeks(self.delta + o.delta, self.gamma + o.gamma, self.vega + o.vega, self.theta + o.theta, self.rho + o.rho)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str, q: float = 0.0) -> Greeks:
    kind = kind.lower()
    if T <= 1e-12 or sigma <= 1e-12:
        itm = (S > K) if kind == "call" else (S < K)
        d = (1.0 if kind == "call" else -1.0) if itm else 0.0
        return Greeks(d, 0.0, 0.0, 0.0, 0.0)
    d1, d2 = _d1d2(S, K, T, r, sigma, q)
    d1, d2 = float(d1), float(d2)
    df_q, df_r = math.exp(-q * T), math.exp(-r * T)
    pdf = norm_pdf(d1)
    gamma = df_q * pdf / (S * sigma * math.sqrt(T))
    vega = S * df_q * pdf * math.sqrt(T) / 100.0
    common = -S * df_q * pdf * sigma / (2 * math.sqrt(T))
    if kind == "call":
        delta = df_q * norm_cdf(d1)
        theta = common - r * K * df_r * norm_cdf(d2) + q * S * df_q * norm_cdf(d1)
        rho = K * T * df_r * norm_cdf(d2) / 100.0
    else:
        delta = -df_q * norm_cdf(-d1)
        theta = common + r * K * df_r * norm_cdf(-d2) - q * S * df_q * norm_cdf(-d1)
        rho = -K * T * df_r * norm_cdf(-d2) / 100.0
    return Greeks(delta, gamma, vega, theta / DAYS_PER_YEAR, rho)


def implied_vol(price: float, S: float, K: float, T: float, r: float, kind: str, q: float = 0.0,
                lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-8) -> Optional[float]:
    """Solve for sigma. Returns None when the price is outside no-arbitrage bounds (below intrinsic, etc.)."""
    if price is None or T <= 0 or price <= 0:
        return None
    if bs_price(S, K, T, r, lo, kind, q) - price > tol or bs_price(S, K, T, r, hi, kind, q) < price:
        return None
    sigma = 0.3
    for _ in range(50):  # Newton first, bisection fallback
        diff = bs_price(S, K, T, r, sigma, kind, q) - price
        if abs(diff) < tol:
            return sigma
        v = bs_greeks(S, K, T, r, sigma, kind, q).vega * 100.0
        if v < 1e-10:
            break
        nxt = sigma - diff / v
        if not lo < nxt < hi:
            break
        sigma = nxt
    a, b = lo, hi
    for _ in range(200):
        m = 0.5 * (a + b)
        if bs_price(S, K, T, r, m, kind, q) > price:
            b = m
        else:
            a = m
        if b - a < tol:
            break
    return 0.5 * (a + b)


# --------------------------------------------------------------------------- single-level probabilities

def expected_move(S: float, iv: float, dte: float) -> float:
    """One standard deviation move in dollars: S x IV x sqrt(DTE / 365)."""
    return S * iv * math.sqrt(max(dte, 0.0) / DAYS_PER_YEAR)


def straddle_move(call_mid: float, put_mid: float) -> dict:
    """Cross check from the ATM straddle. The straddle price is roughly 0.8 of a one-sigma move."""
    s = call_mid + put_mid
    return {"straddle": s, "one_sigma_equiv": s / 0.7979}


def prob_above(level: float, S: float, vol: float, dte: float, r: float = 0.0, q: float = 0.0) -> float:
    """P(price at expiry > level) under a lognormal model with drift r - q."""
    T = dte / DAYS_PER_YEAR
    if T <= 0 or vol <= 0:
        return 1.0 if S > level else 0.0
    d2 = (math.log(S / level) + (r - q - 0.5 * vol * vol) * T) / (vol * math.sqrt(T))
    return norm_cdf(d2)


def prob_below(level: float, S: float, vol: float, dte: float, r: float = 0.0, q: float = 0.0) -> float:
    return 1.0 - prob_above(level, S, vol, dte, r, q)


def prob_touch(level: float, S: float, vol: float, dte: float, r: float = 0.0, q: float = 0.0) -> float:
    """APPROXIMATE probability of trading at `level` before expiry: 2 x P(finishing beyond it), capped at 1."""
    p = prob_above(level, S, vol, dte, r, q) if level >= S else prob_below(level, S, vol, dte, r, q)
    return min(1.0, 2.0 * p)


# --------------------------------------------------------------------------- volatility statistics

def hist_vol(closes: Sequence[float], window: int = 20) -> Optional[float]:
    """Annualised close-to-close historical volatility over the last `window` returns."""
    c = np.asarray(closes, dtype=float)
    c = c[np.isfinite(c) & (c > 0)]
    if len(c) < window + 1:
        return None
    rets = np.diff(np.log(c[-(window + 1):]))
    return float(np.std(rets, ddof=1) * math.sqrt(TRADING_DAYS))


def iv_rank(current: float, history: Sequence[float]) -> Optional[float]:
    """0-100: where today's IV sits between the min and max of the history window."""
    h = np.asarray([x for x in history if x is not None and np.isfinite(x)], dtype=float)
    if current is None or len(h) < 2 or h.max() == h.min():
        return None
    return float(np.clip((current - h.min()) / (h.max() - h.min()) * 100.0, 0, 100))


def iv_percentile(current: float, history: Sequence[float]) -> Optional[float]:
    """0-100: share of days in the history window with IV below today's."""
    h = np.asarray([x for x in history if x is not None and np.isfinite(x)], dtype=float)
    if current is None or len(h) < 2:
        return None
    return float((h < current).mean() * 100.0)


# --------------------------------------------------------------------------- liquidity

GRADE_ORDER = "ABCF"


def liquidity_grade(bid: Optional[float], ask: Optional[float], oi: Optional[float], volume: Optional[float]) -> dict:
    """A/B/C/F from bid/ask as % of mid, open interest and today's volume. The worst criterion wins.
    A: spread <= 5%, OI >= 1000, vol >= 500.  B: <= 10%, OI >= 250, vol >= 50.  C: <= 20%, OI >= 50, vol >= 1.
    Anything worse, no bid, or missing quotes is F (auto reject)."""
    if bid is None or ask is None or not bid > 0 or not ask >= bid:
        return {"grade": "F", "spread_pct": None, "why": "no two-sided market"}
    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid * 100
    oi, volume = oi or 0, volume or 0

    def g(val, a, b, c, higher_better=True):
        ok = (lambda t: val >= t) if higher_better else (lambda t: val <= t)
        return "A" if ok(a) else "B" if ok(b) else "C" if ok(c) else "F"

    parts = {"spread": g(spread_pct, 5, 10, 20, False), "oi": g(oi, 1000, 250, 50), "volume": g(volume, 500, 50, 1)}
    worst = max(parts.values(), key=GRADE_ORDER.index)
    why = ", ".join(f"{k} {v}" for k, v in parts.items() if v == worst)
    return {"grade": worst, "spread_pct": spread_pct, "why": why}


def worst_grade(grades: Iterable[str]) -> str:
    gs = list(grades)
    return max(gs, key=GRADE_ORDER.index) if gs else "F"


# --------------------------------------------------------------------------- positions

@dataclass
class Leg:
    kind: str                     # 'call', 'put' or 'stock'
    qty: float                    # + long / - short (contracts; stock in lots of 100 shares)
    strike: float = 0.0
    dte: float = 0.0              # calendar days to this leg's expiry
    price: Optional[float] = None  # your fill (per share). If None, estimated from bid/ask
    iv: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    oi: Optional[float] = None
    volume: Optional[float] = None

    @property
    def is_option(self) -> bool:
        return self.kind in ("call", "put")

    @property
    def mid(self) -> Optional[float]:
        if self.bid is not None and self.ask is not None and self.ask >= self.bid >= 0:
            return (self.bid + self.ask) / 2
        return self.price

    @property
    def half_spread(self) -> float:
        if self.bid is not None and self.ask is not None and self.ask >= self.bid:
            return (self.ask - self.bid) / 2
        return 0.0

    def fill(self) -> float:
        """Your fill if given, otherwise halfway between mid and the worse side of the spread."""
        if self.price is not None:
            return self.price
        if self.mid is None:
            raise ValueError(f"{self.kind} {self.strike} leg has no price and no bid/ask")
        return self.mid + (self.half_spread / 2 if self.qty > 0 else -self.half_spread / 2)


@dataclass
class Position:
    legs: List[Leg]
    multiplier: int = 100
    commission_per_contract: float = 0.0   # per contract, per side
    fx_fee_pct: float = 0.0                # e.g. 0.015 for a CAD account trading USD options
    name: str = ""
    dividend_yield: float = 0.0

    @property
    def option_legs(self) -> List[Leg]:
        return [lg for lg in self.legs if lg.is_option]

    @property
    def horizon(self) -> float:
        """Evaluation date in days: the first option expiry."""
        return min(lg.dte for lg in self.option_legs) if self.option_legs else 30.0

    @property
    def is_time_spread(self) -> bool:
        return len({round(lg.dte, 3) for lg in self.option_legs}) > 1

    def entry(self) -> float:
        """Net cost per share-unit at entry. Positive = debit paid, negative = credit received."""
        return sum(lg.qty * lg.fill() for lg in self.legs)

    def entry_slippage(self) -> float:
        """Dollars lost vs mid at entry (already inside entry())."""
        return sum(abs(lg.qty) * abs(lg.fill() - lg.mid) for lg in self.legs if lg.mid is not None) * self.multiplier

    def costs(self) -> dict:
        """Round trip fees and exit slippage, in dollars. Commissions are charged open and close on every
        option leg (conservative: OTM legs that expire free would save the closing commission). FX is charged
        on the premium going in and an equal amount coming out. Exit slippage applies to legs still open at the
        horizon, which have to be sold or bought back."""
        contracts = sum(abs(lg.qty) for lg in self.option_legs)
        commissions = contracts * self.commission_per_contract * 2
        fx = self.fx_fee_pct * abs(self.entry()) * self.multiplier * 2
        h = self.horizon
        exit_slip = sum(abs(lg.qty) * lg.half_spread / 2 for lg in self.option_legs if lg.dte > h + 1e-9) * self.multiplier
        return {"commissions": commissions, "fx": fx, "exit_slippage": exit_slip, "total": commissions + fx + exit_slip}

    def ref_iv(self) -> Optional[float]:
        """IV for the underlying's distribution: average IV of the legs that expire at the horizon."""
        h = self.horizon
        ivs = [lg.iv for lg in self.option_legs if abs(lg.dte - h) < 1e-9 and lg.iv]
        ivs = ivs or [lg.iv for lg in self.option_legs if lg.iv]
        return float(np.mean(ivs)) if ivs else None

    def value(self, S_T, t_days: float, r: float, iv_shock: float = 0.0):
        """Mark-to-model value per share-unit of all legs, `t_days` from now. Legs past expiry are worth intrinsic.
        Legs still alive are priced with Black-Scholes at their own IV x (1 + iv_shock)."""
        S_T = np.asarray(S_T, dtype=float)
        total = np.zeros_like(S_T)
        for lg in self.legs:
            if lg.kind == "stock":
                total = total + lg.qty * S_T
                continue
            T = max(lg.dte - t_days, 0.0) / DAYS_PER_YEAR
            sig = (lg.iv or 0.0) * (1.0 + iv_shock)
            if T > 0 and sig <= 0:
                raise ValueError(f"{lg.kind} {lg.strike} leg is alive at the horizon but has no IV")
            total = total + lg.qty * bs_price(S_T, lg.strike, T, r, sig, lg.kind, self.dividend_yield)
        return total

    def gross_pnl(self, S_T, t_days: float, r: float, iv_shock: float = 0.0):
        return (self.value(S_T, t_days, r, iv_shock) - self.entry()) * self.multiplier

    def net_greeks(self, S: float, r: float) -> Greeks:
        g = Greeks(0, 0, 0, 0, 0)
        for lg in self.legs:
            if lg.kind == "stock":
                g = g + Greeks(lg.qty, 0, 0, 0, 0)
            else:
                lg_g = bs_greeks(S, lg.strike, lg.dte / DAYS_PER_YEAR, r, lg.iv or 0.0, lg.kind, self.dividend_yield)
                g = g + lg_g.scaled(lg.qty)
        return g.scaled(self.multiplier)


# --------------------------------------------------------------------------- expiry analysis

def _terminal_grid(S, vol, T, r, q, n=4001, zmax=8.0):
    z = np.linspace(-zmax, zmax, n)
    w = norm_pdf(z)
    w = w / w.sum()
    S_T = S * np.exp((r - q - 0.5 * vol * vol) * T + vol * math.sqrt(T) * z)
    return S_T, w


def _payoff_shape(pos: Position, S: float, r: float) -> dict:
    """Breakevens, max profit and max loss at the horizon from a deterministic price grid (no probabilities)."""
    h = pos.horizon
    grid = np.concatenate([np.linspace(S * 0.01, S * 3.0, 6000), [S * 5.0, S * 10.0]])
    pnl = pos.gross_pnl(grid, h, r) - pos.costs()["total"]
    core, core_pnl = grid[:6000], pnl[:6000]
    up_slope = (pnl[-1] - pnl[-2]) / (grid[-1] - grid[-2])
    max_profit = float("inf") if up_slope > 1e-3 else float(pnl.max())
    at_zero = pos.gross_pnl(np.array([1e-9]), h, r)[0] - pos.costs()["total"]
    max_loss = float("-inf") if up_slope < -1e-3 else float(min(pnl.min(), at_zero))
    bes = []
    sign = np.sign(core_pnl)
    for i in np.nonzero(sign[:-1] * sign[1:] < 0)[0]:
        x0, x1, y0, y1 = core[i], core[i + 1], core_pnl[i], core_pnl[i + 1]
        bes.append(float(x0 - y0 * (x1 - x0) / (y1 - y0)))
    return {"max_profit": max_profit, "max_loss": max_loss, "breakevens": bes}


def expected_value(pos: Position, S: float, vol: float, r: float = 0.0) -> float:
    """Sum of probability x payoff over a lognormal scenario grid at the horizon, minus fees and slippage.
    Entry slippage is already in the fill price; exit slippage, commissions and FX are subtracted here."""
    T = pos.horizon / DAYS_PER_YEAR
    S_T, w = _terminal_grid(S, vol, T, r, pos.dividend_yield)
    net = pos.gross_pnl(S_T, pos.horizon, r) - pos.costs()["total"]
    return float((w * net).sum())


def analyze_expiry(pos: Position, S: float, vol: float, r: float = 0.0) -> dict:
    T = pos.horizon / DAYS_PER_YEAR
    S_T, w = _terminal_grid(S, vol, T, r, pos.dividend_yield)
    net = pos.gross_pnl(S_T, pos.horizon, r) - pos.costs()["total"]
    out = {"vol": vol, "pop": float(w[net > 0].sum()), "ev": float((w * net).sum())}
    out.update(_payoff_shape(pos, S, r))
    return out


# --------------------------------------------------------------------------- Monte Carlo

def monte_carlo(pos: Position, S: float, vol: float, r: float = 0.0, n_paths: int = 20000, iv_shock: float = 0.0,
                target_frac: float = 0.5, max_profit: Optional[float] = None, path_check: bool = True,
                seed: Optional[int] = 7, max_steps: int = 60) -> dict:
    """GBM paths (drift r - q, constant vol). Each step reprices every leg, so it handles calendars and diagonals.
    The IV shock multiplies every leg's IV (-0.2 = IVs fall 20% relative, e.g. 40% -> 32%).
    Returns POP and EV at the horizon (net of costs) and, if path_check, the chance the position's mark reaches
    `target_frac` of max profit at some daily close before the horizon."""
    rng = np.random.default_rng(seed)
    h = pos.horizon
    q = pos.dividend_yield
    costs = pos.costs()["total"]
    n_steps = max(1, min(int(math.ceil(h)), max_steps)) if path_check else 1
    dt_days = h / n_steps
    dt = dt_days / DAYS_PER_YEAR
    log_s = np.full(n_paths, math.log(S))
    hit = np.zeros(n_paths, dtype=bool)
    if max_profit is None:
        max_profit = _payoff_shape(pos, S, r)["max_profit"]
    target = target_frac * max_profit if np.isfinite(max_profit) and max_profit > 0 else None
    for k in range(1, n_steps + 1):
        z = rng.standard_normal(n_paths)
        log_s += (r - q - 0.5 * vol * vol) * dt + vol * math.sqrt(dt) * z
        if path_check and target is not None and k < n_steps:
            pnl_k = pos.gross_pnl(np.exp(log_s), k * dt_days, r, iv_shock) - costs
            hit |= pnl_k >= target
    S_T = np.exp(log_s)
    net = pos.gross_pnl(S_T, h, r, iv_shock) - costs
    if target is not None:
        hit |= net >= target
    return {
        "pop": float((net > 0).mean()),
        "ev": float(net.mean()),
        "p_hit_target": float(hit.mean()) if (path_check and target is not None) else None,
        "pnl_p5": float(np.percentile(net, 5)),
        "pnl_p50": float(np.percentile(net, 50)),
        "pnl_p95": float(np.percentile(net, 95)),
        "iv_shock": iv_shock,
        "paths": n_paths,
    }


# --------------------------------------------------------------------------- Greek attribution

def greek_pnl(pos: Position, S: float, r: float, dS: float, dvol_pts: float = 0.0, dt_days: float = 0.0,
              dr_pts: float = 0.0) -> dict:
    """dV ~ Delta dS + 1/2 Gamma dS^2 + Vega dsigma + Theta dt + Rho dr, in dollars for the whole position."""
    g = pos.net_greeks(S, r)
    terms = {"delta": g.delta * dS, "gamma": 0.5 * g.gamma * dS * dS, "vega": g.vega * dvol_pts,
             "theta": g.theta * dt_days, "rho": g.rho * dr_pts}
    terms["total"] = sum(terms.values())
    return terms


def dominant_greek(pos: Position, S: float, vol: float, r: float = 0.0, event_in_window: bool = False) -> dict:
    """Which term drives P&L right now, for a typical day: a one-sigma daily move, a 1 vol point IV change
    (5 points if an event sits inside the window), one day of decay and a 0.1 rate point move."""
    dS = S * vol * math.sqrt(1 / DAYS_PER_YEAR)
    terms = greek_pnl(pos, S, r, dS, 5.0 if event_in_window else 1.0, 1.0, 0.1)
    mags = {k: abs(v) for k, v in terms.items() if k != "total"}
    top = max(mags, key=mags.get)
    h = pos.horizon
    longest = max((lg.dte for lg in pos.option_legs), default=0)
    if event_in_window:
        regime = "event: vega and gamma. IV usually collapses after the event and can erase a correct directional call"
    elif h < 10:
        regime = "under 10 DTE: theta and gamma risk"
    elif longest >= 180:
        regime = "long-dated: rho, dividends and carry matter"
    else:
        regime = "directional: delta and gamma" if top in ("delta", "gamma") else f"{top}-driven"
    return {"dominant": top, "regime": regime, "terms": terms, "greeks": pos.net_greeks(S, r)}


# --------------------------------------------------------------------------- full two-model analysis

def analyze(pos: Position, S: float, iv: Optional[float], hv20: Optional[float], r: float = 0.0,
            n_paths: int = 20000, seed: Optional[int] = 7) -> dict:
    """Run every probability twice: market-implied (IV) and realized (HV20). The gap is the edge signal."""
    iv = iv or pos.ref_iv()
    out = {"horizon_days": pos.horizon, "entry": pos.entry() * pos.multiplier, "costs": pos.costs(),
           "entry_slippage": pos.entry_slippage(), "is_time_spread": pos.is_time_spread}
    for label, vol in (("implied", iv), ("realized", hv20)):
        if not vol:
            out[label] = None
            continue
        res = analyze_expiry(pos, S, vol, r)
        mc = monte_carlo(pos, S, vol, r, n_paths, 0.0, max_profit=res["max_profit"], seed=seed)
        res["p_hit_50"] = mc["p_hit_target"]
        res["mc_pop"], res["mc_ev"] = mc["pop"], mc["ev"]
        if pos.is_time_spread:
            res["iv_shock"] = {f"{int(s * 100):+d}%": monte_carlo(pos, S, vol, r, n_paths, s, path_check=False, seed=seed)
                               for s in (-0.2, 0.2)}
        out[label] = res
    base = out.get("implied") or out.get("realized") or {}
    for k in ("max_profit", "max_loss", "breakevens"):
        out[k] = base.get(k)
    out["edge"] = edge_read(out.get("implied"), out.get("realized"), iv, hv20)
    if pos.is_time_spread:
        back = max(pos.option_legs, key=lambda lg: lg.dte)
        out["time_spread_note"] = (f"Assumes back IV holds at {back.iv * 100:.0f}% to front expiry; "
                                   "flatters calendars in backwardation. Weigh the -20% row.")
    return out


def ev_tolerance(max_loss: Optional[float]) -> float:
    """'Near zero' EV band: the larger of $5 or 2% of max loss."""
    if max_loss is None or not np.isfinite(max_loss):
        return 5.0
    return max(5.0, 0.02 * abs(max_loss))


def edge_read(implied: Optional[dict], realized: Optional[dict], iv: Optional[float], hv: Optional[float]) -> str:
    if not implied or not realized:
        return "Only one vol model available, so there is no edge read. Treat the numbers as the market's pricing."
    tol = ev_tolerance(implied.get("max_loss"))
    ei, er = implied["ev"], realized["ev"]
    gap = f"IV {iv * 100:.1f}% vs HV20 {hv * 100:.1f}%"
    if er > tol and ei < -tol:
        return f"Market and recent history disagree ({gap}). Positive EV only if the stock keeps moving like it has for 20 days."
    if ei > tol and er < -tol:
        return (f"Market and recent history disagree ({gap}). Positive EV only if the stock moves the way options "
                "are pricing, not how it has been moving.")
    if ei > tol and er > tol:
        return f"Both models show positive EV ({gap})."
    if ei < -tol and er < -tol:
        return f"Both models show negative EV ({gap})."
    return f"EV is near zero in at least one model ({gap}). No clear edge."


def verdict(analysis: dict, liquidity: str, unplanned_event: bool = False, max_loss_limit: Optional[float] = None) -> dict:
    """ENTER CANDIDATE / MARGINAL / THROW IT OUT, using the rules in GROK_INSTRUCTIONS.md section D."""
    imp, rea = analysis.get("implied"), analysis.get("realized")
    max_loss = analysis.get("max_loss")
    tol = ev_tolerance(max_loss)
    reasons = []
    if liquidity == "F":
        reasons.append("liquidity grade F")
    if unplanned_event:
        reasons.append("unplanned event inside the trade window")
    if max_loss is not None and max_loss_limit and (not np.isfinite(max_loss) or abs(max_loss) > max_loss_limit):
        reasons.append(f"max loss ${abs(max_loss):,.0f} is over your ${max_loss_limit:,.0f} limit")
    if imp and rea and imp["ev"] < -tol and rea["ev"] < -tol:
        reasons.append("negative EV under both vol models")
    if reasons:
        return {"verdict": "THROW IT OUT", "reasons": reasons}
    if rea and rea["ev"] > tol and liquidity in ("A", "B"):
        return {"verdict": "ENTER CANDIDATE", "reasons": ["EV after costs positive under realized vol", f"liquidity {liquidity}"]}
    why = []
    if rea is None:
        why.append("no realized vol to test against")
    elif abs(rea["ev"]) <= tol:
        why.append("EV near zero under realized vol")
    if imp and rea and ((imp["ev"] > tol and rea["ev"] < -tol) or (imp["ev"] < -tol and rea["ev"] > tol)):
        why.append("the two vol models disagree")
    if liquidity == "C":
        why.append("liquidity grade C")
    return {"verdict": "MARGINAL", "reasons": why or ["no clear edge"]}


# --------------------------------------------------------------------------- formatting and CLI

def money(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    if not np.isfinite(x):
        return "unlimited"
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def pct(x: Optional[float], digits: int = 0) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def summary_lines(a: dict) -> List[str]:
    imp, rea = a.get("implied") or {}, a.get("realized") or {}
    lines = [
        f"POP impl {pct(imp.get('pop'))} / real {pct(rea.get('pop'))}"
        f" | EV impl {money(imp.get('ev'))} / real {money(rea.get('ev'))}",
        f"Max +{money(a['max_profit'])} / {money(a['max_loss'])} | BE {', '.join(f'{b:.2f}' for b in a['breakevens']) or 'none'}",
    ]
    if imp.get("p_hit_50") is not None or rea.get("p_hit_50") is not None:
        lines.append(f"P(50% of max) impl {pct(imp.get('p_hit_50'))} / real {pct(rea.get('p_hit_50'))}")
    if imp.get("iv_shock"):
        sh = imp["iv_shock"]
        lines.append("IV shock EV: " + " | ".join(f"{k} {money(v['ev'])} (POP {pct(v['pop'])})" for k, v in sh.items()))
    lines.append(a["edge"])
    if a.get("time_spread_note"):
        lines.append(a["time_spread_note"])
    return lines


def position_from_dict(d: dict) -> Position:
    legs = [Leg(**{k: v for k, v in lg.items() if k in Leg.__dataclass_fields__}) for lg in d["legs"]]
    keys = ("multiplier", "commission_per_contract", "fx_fee_pct", "name", "dividend_yield")
    return Position(legs=legs, **{k: d[k] for k in keys if k in d})


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Analyze a multi-leg option position from a JSON file. Model estimates only.")
    ap.add_argument("position_json", help='{"spot":..., "iv":..., "hv20":..., "r":..., "legs":[{"kind":"call","qty":1,...}]}')
    ap.add_argument("--max-loss-limit", type=float, default=None)
    args = ap.parse_args(argv)
    with open(args.position_json) as fh:
        d = json.load(fh)
    pos = position_from_dict(d)
    a = analyze(pos, d["spot"], d.get("iv"), d.get("hv20"), d.get("r", 0.04))
    liq = worst_grade(liquidity_grade(lg.bid, lg.ask, lg.oi, lg.volume)["grade"] for lg in pos.option_legs)
    v = verdict(a, liq, d.get("unplanned_event", False), args.max_loss_limit)
    dom = dominant_greek(pos, d["spot"], d.get("iv") or pos.ref_iv() or 0.3, d.get("r", 0.04), d.get("event_in_window", False))
    print(f"{v['verdict']} ({'; '.join(v['reasons'])})")
    for line in summary_lines(a):
        print(line)
    print(f"Liquidity {liq} | Dominant Greek: {dom['dominant']} ({dom['regime']})")
    print(f"Costs: {money(a['costs']['total'])} round trip + {money(a['entry_slippage'])} entry slippage vs mid")
    print("Probabilities are model estimates, not promises.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
