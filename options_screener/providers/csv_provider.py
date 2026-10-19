"""CSV files you drop in options_screener/data/ (see data/README.md for the formats)."""
from __future__ import annotations

import csv
from datetime import date, datetime, time
from pathlib import Path

from ..config import DATA
from ..models import ET, Bar, Contract


def _f(v):
    return float(v) if v not in (None, "", "nan") else None


def _ts(v: str) -> datetime:
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=ET)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [{k.strip().lower(): v for k, v in r.items()} for r in csv.DictReader(f)]


class CSVUnderlying:
    """data/underlying/<SYM>_1d.csv (date,open,high,low,close,volume) and
    data/underlying/<SYM>_1m.csv (ts,open,high,low,close,volume)."""
    name = "CSV underlying"

    def __init__(self, root: Path = DATA):
        self.root = root / "underlying"
        self._d, self._m = {}, {}

    def _daily(self, symbol):
        if symbol in self._d:
            return self._d[symbol]
        out = []
        for r in _read(self.root / f"{symbol}_1d.csv"):
            d = date.fromisoformat(r["date"][:10])
            out.append(Bar(ts=datetime.combine(d, time(16, 0), tzinfo=ET), open=_f(r["open"]), high=_f(r["high"]),
                           low=_f(r["low"]), close=_f(r["close"]), volume=_f(r.get("volume")) or 0))
        self._d[symbol] = sorted(out, key=lambda b: b.ts)
        return self._d[symbol]

    def _minutes(self, symbol):
        if symbol in self._m:
            return self._m[symbol]
        by_day: dict = {}
        for r in _read(self.root / f"{symbol}_1m.csv"):
            ts = _ts(r["ts"])
            by_day.setdefault(ts.astimezone(ET).date(), []).append(
                Bar(ts=ts, open=_f(r["open"]), high=_f(r["high"]), low=_f(r["low"]), close=_f(r["close"]),
                    volume=_f(r.get("volume")) or 0))
        self._m[symbol] = {d: sorted(v, key=lambda b: b.ts) for d, v in by_day.items()}
        return self._m[symbol]

    def daily_bars(self, symbol, end, n):
        return [b for b in self._daily(symbol) if b.ts.date() <= end][-n:]

    def intraday_bars(self, symbol, day):
        return [b for b in self._minutes(symbol).get(day, []) if time(9, 30) <= b.et_time < time(16, 0)]


class CSVOptions:
    """data/options/<OCC>.csv: ts,open,high,low,close,volume[,trades,bid,ask,bid_size,ask_size]."""
    name = "CSV options"

    def __init__(self, root: Path = DATA):
        self.root = root / "options"
        sample = next(iter(sorted(self.root.glob("*.csv"))), None) if self.root.exists() else None
        cols = set(_read(sample)[0].keys()) if sample and _read(sample) else set()
        self.has_quotes = {"bid", "ask"} <= cols
        self.has_trade_counts = "trades" in cols
        self._cache = {}

    def _load(self, occ):
        if occ in self._cache:
            return self._cache[occ]
        out = {}
        for r in _read(self.root / f"{occ}.csv"):
            ts = _ts(r["ts"])
            out.setdefault(ts.astimezone(ET).date(), []).append(Bar(
                ts=ts, open=_f(r["open"]), high=_f(r["high"]), low=_f(r["low"]), close=_f(r["close"]),
                volume=_f(r.get("volume")) or 0, trades=int(float(r["trades"])) if r.get("trades") else None,
                bid=_f(r.get("bid")), ask=_f(r.get("ask")), bid_size=_f(r.get("bid_size")), ask_size=_f(r.get("ask_size"))))
        self._cache[occ] = out
        return out

    def option_bars(self, contract: Contract, day: date):
        return sorted(self._load(contract.occ).get(day, []), key=lambda b: b.ts)


class CSVEarnings:
    """data/earnings.csv: symbol,date  (historical report dates for backtests)."""
    name = "CSV earnings"

    def __init__(self, path: Path = DATA / "earnings.csv"):
        self.rows: dict = {}
        for r in _read(path):
            self.rows.setdefault(r["symbol"].upper(), []).append(date.fromisoformat(r["date"][:10]))

    def earnings_dates(self, symbol, start, end):
        return sorted(d for d in self.rows.get(symbol.upper(), []) if start <= d <= end)
