"""Plain data types shared by the screen, backtest and paper modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TORONTO = ZoneInfo("America/Toronto")
OPEN = time(9, 30)
CLOSE = time(16, 0)


@dataclass(frozen=True)
class Contract:
    symbol: str
    expiry: date
    strike: float
    right: str  # "C" or "P"

    @property
    def occ(self) -> str:
        """OCC-style ticker without padding, e.g. SPY261023C00580000 (Massive uses an 'O:' prefix)."""
        return f"{self.symbol}{self.expiry:%y%m%d}{self.right}{int(round(self.strike * 1000)):08d}"

    def dte(self, on: date) -> int:
        return (self.expiry - on).days

    def label(self) -> str:
        kind = "CALL" if self.right == "C" else "PUT"
        return f"{self.symbol} {self.expiry:%Y-%m-%d} {self.strike:g} {kind}"


@dataclass
class Bar:
    """One bar. For options: o/h/l/c are trade prices; bid/ask (if known) are quotes for the minute;
    trades = number of prints in the bar (IBKR barCount, Massive 'n')."""
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    trades: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None

    @property
    def et_time(self) -> time:
        return self.ts.astimezone(ET).time()


@dataclass
class OptionSnapshot:
    """A contract as seen at the prior close (or synthesized for backtests)."""
    contract: Contract
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float] = None
    volume: Optional[float] = None
    open_interest: Optional[float] = None
    prev_open_interest: Optional[float] = None
    delta: Optional[float] = None
    iv: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    synthetic: bool = False

    @property
    def mid(self) -> Optional[float]:
        if self.bid is not None and self.ask is not None and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last


@dataclass
class OptionStats:
    """Ticker-level options activity on the as-of day."""
    option_volume: Optional[float] = None
    avg_option_volume_20d: Optional[float] = None
    open_interest: Optional[float] = None
    iv: Optional[float] = None
    iv_prev: Optional[float] = None
    iv_history: list = field(default_factory=list)   # ~1y of daily IV values for IV rank


@dataclass
class Check:
    name: str
    value: Optional[float]
    threshold: str
    status: str          # PASS | FAIL | N/A
    note: str = ""


@dataclass
class FillQuality:
    contract: Contract
    checks: list
    source: str
    verified: bool        # True = real quotes/trades; False = PROXY from bars
    median_spread_pct: Optional[float] = None
    first_hour_volume: Optional[float] = None
    open_interest: Optional[float] = None
    prints_per_min: Optional[float] = None
    round_trip_cost_pct: Optional[float] = None
    substituted_from: Optional[str] = None

    @property
    def passed(self) -> bool:
        return all(c.status != "FAIL" for c in self.checks)

    @property
    def failed_checks(self) -> list:
        return [c.name for c in self.checks if c.status == "FAIL"]

    @property
    def label(self) -> str:
        return "VERIFIED" if self.verified else "PROXY"

    @property
    def score(self) -> float:
        counted = [c for c in self.checks if c.status != "N/A"]
        return sum(c.status == "PASS" for c in counted) / len(counted) if counted else 0.0


@dataclass
class Candidate:
    symbol: str
    direction: str                     # "bull" | "bear"
    scores: dict
    combined: float
    move_rate: Optional[float]
    catalyst: str
    earnings: bool
    iv_rank: Optional[float]
    iv_crush_risk: bool
    gate_a: bool
    gate_b: bool
    gate_c: bool
    snapshot: Optional[OptionSnapshot] = None
    fill: Optional[FillQuality] = None
    plan: Optional[dict] = None
    notes: list = field(default_factory=list)
    reject_reason: str = ""
