"""Multi-leg positions: P/L, breakevens, max profit/loss, probability of profit and what-if grids.

A leg is written like  +1C150@3.20  (signed quantity, C/P/S, strike, @ price paid or received).
  +1C150@3.20     buy 1 call, strike 150, paid 3.20
  -2P140@1.10     sell 2 puts, strike 140, received 1.10
  -1C160          sell 1 call; no price given, so the model prices it at --iv
  +1C150@3.20~45  same as the first, but this leg's IV is 45% (overrides the solved IV)
  +100S@148.50    100 shares bought at 148.50
"""
import math
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import black_scholes as bs

CONTRACT = 100
LEG_RE = re.compile(r"^([+-]?\d+)([CPS])(\d+(?:\.\d+)?)?(?:@(\d+(?:\.\d+)?))?(?:~(\d+(?:\.\d+)?))?$", re.I)


@dataclass
class Leg:
    qty: int
    kind: str
    strike: Optional[float] = None
    premium: Optional[float] = None
    iv: Optional[float] = None

    @property
    def mult(self) -> int:
        return 1 if self.kind == "S" else CONTRACT

    def label(self) -> str:
        side = "LONG" if self.qty > 0 else "SHORT"
        if self.kind == "S":
            return f"{side} {abs(self.qty)} shares"
        return f"{side} {abs(self.qty)}x {self.strike:g} {'CALL' if self.kind == 'C' else 'PUT'}"


def parse_leg(text: str) -> Leg:
    m = LEG_RE.match(text.strip().replace(" ", ""))
    if not m:
        raise ValueError(f"can't read leg {text!r}; use a format like +1C150@3.20 or -2P140")
    qty, kind, strike, prem, iv = m.groups()
    kind = kind.upper()
    if int(qty) == 0:
        raise ValueError(f"leg {text!r} has quantity 0")
    if kind != "S" and strike is None:
        raise ValueError(f"option leg {text!r} needs a strike")
    if kind == "S" and prem is None:
        raise ValueError(f"stock leg {text!r} needs an entry price, e.g. +100S@148.50")
    return Leg(int(qty), kind, float(strike) if strike and kind != "S" else None,
               float(prem) if prem else None, float(iv) / 100 if iv else None)


class Position:
    def __init__(self, legs: List[Leg], S: float, dte: float, r: float = 0.04, q: float = 0.0,
                 iv: Optional[float] = None):
        if not legs:
            raise ValueError("need at least one leg")
        if S <= 0 or dte < 0:
            raise ValueError("price must be > 0 and days to expiry >= 0")
        self.legs, self.S, self.dte, self.r, self.q = legs, S, dte, r, q
        self.T = dte / 365
        self.notes: List[str] = []
        self._resolve_vols(iv)

    def _resolve_vols(self, iv: Optional[float]) -> None:
        """Each option leg gets a vol: its own ~IV, else solved from its price, else the position --iv."""
        for leg in self.legs:
            if leg.kind == "S" or leg.iv is not None:
                continue
            if leg.premium is not None and self.T > 0:
                try:
                    leg.iv = bs.implied_vol(leg.kind, leg.premium, self.S, leg.strike, self.T, self.r, self.q)
                except ValueError as e:
                    self.notes.append(f"{leg.label()}: {e}")
        solved = [leg.iv for leg in self.legs if leg.kind != "S" and leg.iv is not None]
        self.iv = iv if iv is not None else (sum(solved) / len(solved) if solved else None)
        if self.iv is None:
            raise ValueError("no volatility: pass --iv or give option prices so IV can be solved")
        for leg in self.legs:
            if leg.kind != "S":
                leg.iv = leg.iv if leg.iv is not None else self.iv
                if leg.premium is None:
                    leg.premium = bs.price(leg.kind, self.S, leg.strike, self.T, self.r, leg.iv, self.q)
                    self.notes.append(f"{leg.label()}: no price given, used model price {leg.premium:.2f}")

    # ---- cost and values -------------------------------------------------------------------
    @property
    def cost(self) -> float:
        """Net dollars paid to open. Positive = debit, negative = credit received."""
        return sum(leg.qty * leg.mult * leg.premium for leg in self.legs)

    def value(self, spot: float, days_forward: float = 0.0, iv_shift: float = 0.0) -> float:
        T = max(self.T - days_forward / 365, 0.0)
        total = 0.0
        for leg in self.legs:
            if leg.kind == "S":
                total += leg.qty * spot
            else:
                sigma = max(leg.iv + iv_shift, 0.01)
                total += leg.qty * leg.mult * bs.price(leg.kind, spot, leg.strike, T, self.r, sigma, self.q)
        return total

    def pnl(self, spot: float, days_forward: float = 0.0, iv_shift: float = 0.0) -> float:
        return self.value(spot, days_forward, iv_shift) - self.cost

    def pnl_at_expiry(self, spot: float) -> float:
        total = 0.0
        for leg in self.legs:
            v = spot if leg.kind == "S" else bs.intrinsic(leg.kind, spot, leg.strike)
            total += leg.qty * leg.mult * v
        return total - self.cost

    # ---- Greeks ----------------------------------------------------------------------------
    def greeks(self) -> dict:
        out = dict(delta=0.0, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)
        for leg in self.legs:
            if leg.kind == "S":
                out["delta"] += leg.qty
                continue
            g = bs.greeks(leg.kind, self.S, leg.strike, self.T, self.r, leg.iv, self.q)
            n = leg.qty * leg.mult
            for k in out:
                out[k] += n * getattr(g, k)
        return out

    # ---- expiry profile --------------------------------------------------------------------
    def _kinks(self) -> List[float]:
        strikes = sorted({leg.strike for leg in self.legs if leg.kind != "S"})
        top = max(strikes + [self.S]) * 10
        return [0.0] + strikes + [top]

    def _upside_slope(self) -> int:
        """Dollars of P/L per $1 move above the highest strike (calls and stock only)."""
        return sum(leg.qty * leg.mult for leg in self.legs if leg.kind in ("C", "S"))

    def breakevens(self) -> List[float]:
        pts = self._kinks()
        out = []
        for a, b in zip(pts, pts[1:]):
            pa, pb = self.pnl_at_expiry(a), self.pnl_at_expiry(b)
            if pa == 0 and a > 0:
                out.append(a)
            elif pa * pb < 0:  # P/L is a straight line between kinks, so this is exact
                out.append(a + (b - a) * (-pa) / (pb - pa))
        return sorted({round(x, 2) for x in out})

    def max_profit_loss(self) -> Tuple[Optional[float], Optional[float]]:
        """(max profit, max loss). None means unlimited."""
        vals = [self.pnl_at_expiry(p) for p in self._kinks()[:-1]]
        slope = self._upside_slope()
        hi, lo = max(vals), min(vals)
        return (None if slope > 0 else hi), (None if slope < 0 else lo)

    # ---- probabilities ---------------------------------------------------------------------
    def expiry_distribution(self, steps: int = 4000, width: float = 8.0):
        """Lognormal (risk-neutral) prices at expiry with their probabilities."""
        if self.T <= 0:
            return [(self.S, 1.0)]
        vt = self.iv * math.sqrt(self.T)
        mu = math.log(self.S) + (self.r - self.q - 0.5 * self.iv ** 2) * self.T
        dz = 2 * width / steps
        out = []
        for i in range(steps):
            z0 = -width + i * dz
            p = bs.norm_cdf(z0 + dz) - bs.norm_cdf(z0)
            out.append((math.exp(mu + vt * (z0 + dz / 2)), p))
        return out

    def prob_of_profit(self) -> float:
        return sum(p for s, p in self.expiry_distribution() if self.pnl_at_expiry(s) > 0)

    def expected_pnl_at_expiry(self) -> float:
        return sum(p * self.pnl_at_expiry(s) for s, p in self.expiry_distribution())

    def expected_move(self) -> float:
        return bs.expected_move(self.S, self.iv, self.T)

    # ---- what-if grid ----------------------------------------------------------------------
    def scenario_grid(self, days_forward: float, moves=(-10, -5, -2, 0, 2, 5, 10), iv_shifts=(-0.10, 0.0, 0.10)):
        rows = []
        for shift in iv_shifts:
            rows.append((shift, [self.pnl(self.S * (1 + m / 100), days_forward, shift) for m in moves]))
        return list(moves), rows
