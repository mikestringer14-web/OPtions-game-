"""C$100, ONE-position, defined-risk sizing. Pure functions, no I/O.

  usd_budget               = capital_cad * cad_usd_rate * (1 - fx_cost_pct/100)
  max_premium_per_contract = (usd_budget - fee_per_contract_usd) / 100           (USD per share)
  contracts                = floor(usd_budget / (ask*100 + fee)), must be >= 1

Affordability always uses the ASK (what you pay), never the mid or last trade. Long calls and
puts only: max loss = premium + fees, in CAD including the FX buffer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

UNAFFORDABLE = "unaffordable at C$100"


@dataclass
class Sizing:
    contracts: int
    ask: float
    entry_cost_usd: float          # premium at the ask + fees, all contracts
    entry_cost_cad: float          # incl. the FX buffer
    pct_of_capital: float
    max_loss_cad: float            # full premium + fees: the option can go to zero
    stop_loss_cad: float           # CAD lost if sold at -stop_pct (incl. exit fee + FX)
    target_value_cad: dict         # {5: P/L CAD at +5%, 10: P/L CAD at +10%} after exit fee + FX
    breakeven: float               # underlying price at expiry
    reason: str = ""

    @property
    def affordable(self) -> bool:
        return self.contracts >= 1


def account(cfg: dict) -> dict:
    return cfg["account"]


def usd_budget(cfg: dict, cad_usd: Optional[float] = None) -> float:
    a = account(cfg)
    rate = cad_usd if cad_usd is not None else a["cad_usd_rate"]
    risk_cad = a["capital_cad"] * min(100.0, a["max_risk_per_trade_pct"]) / 100.0
    return risk_cad * rate * (1 - a["fx_cost_pct"] / 100.0)


def max_premium_per_contract(cfg: dict, cad_usd: Optional[float] = None) -> float:
    return (usd_budget(cfg, cad_usd) - account(cfg)["fee_per_contract_usd"]) / account(cfg)["contract_multiplier"]


def usd_to_cad_cost(usd: float, cfg: dict, cad_usd: float) -> float:
    """CAD you spend to obtain `usd` (conversion buffer charged on the way in)."""
    return usd / (cad_usd * (1 - account(cfg)["fx_cost_pct"] / 100.0))


def usd_to_cad_proceeds(usd: float, cfg: dict, cad_usd: float) -> float:
    """CAD you receive when converting `usd` back (buffer charged on the way out)."""
    return usd * (1 - account(cfg)["fx_cost_pct"] / 100.0) / cad_usd


def size(ask: Optional[float], strike: float, right: str, cfg: dict, cad_usd: Optional[float] = None,
         multiplier: int = 100, stop_pct: Optional[float] = None) -> Sizing:
    a = account(cfg)
    rate = cad_usd if cad_usd is not None else a["cad_usd_rate"]
    fee, mult = a["fee_per_contract_usd"], a["contract_multiplier"]
    stop = stop_pct if stop_pct is not None else cfg["plan"]["stop_pct"]
    empty = Sizing(0, ask or 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, {}, 0.0)
    if multiplier != mult:
        empty.reason = f"non-standard multiplier {multiplier} (need {mult})"
        return empty
    if ask is None or ask <= 0:
        empty.reason = "no ask price"
        return empty
    per_contract = ask * mult + fee
    n = math.floor(usd_budget(cfg, rate) / per_contract)
    if n < 1:
        empty.reason = UNAFFORDABLE
        return empty
    cost_usd = n * per_contract
    cost_cad = usd_to_cad_cost(cost_usd, cfg, rate)

    def pl_cad(move_pct: float) -> float:
        proceeds_usd = n * (ask * mult * (1 + move_pct / 100.0) - fee)
        return usd_to_cad_proceeds(proceeds_usd, cfg, rate) - cost_cad

    be = strike + ask + 2 * fee / mult if right == "C" else strike - ask - 2 * fee / mult
    return Sizing(contracts=n, ask=ask, entry_cost_usd=round(cost_usd, 2), entry_cost_cad=round(cost_cad, 2),
                  pct_of_capital=round(cost_cad / a["capital_cad"] * 100, 1), max_loss_cad=round(cost_cad, 2),
                  stop_loss_cad=round(-pl_cad(-stop), 2),
                  target_value_cad={5: round(pl_cad(5.0), 2), 10: round(pl_cad(10.0), 2)}, breakeven=round(be, 3))


def pl_cad_at(exit_price: float, sz: Sizing, cfg: dict, cad_usd: Optional[float] = None) -> float:
    """CAD P/L if all contracts are sold at `exit_price` (exit fee + FX buffer included)."""
    a = account(cfg)
    rate = cad_usd if cad_usd is not None else a["cad_usd_rate"]
    proceeds = sz.contracts * (max(0.0, exit_price) * a["contract_multiplier"] - a["fee_per_contract_usd"])
    return round(usd_to_cad_proceeds(proceeds, cfg, rate) - sz.entry_cost_cad, 2)


def one_contract_cad(ask: float, cfg: dict, cad_usd: Optional[float] = None) -> float:
    """CAD needed for ONE contract at the ask (incl. fee + FX buffer)."""
    a = account(cfg)
    rate = cad_usd if cad_usd is not None else a["cad_usd_rate"]
    return round(usd_to_cad_cost(ask * a["contract_multiplier"] + a["fee_per_contract_usd"], cfg, rate), 2)
