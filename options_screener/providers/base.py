"""Provider interfaces + the as-of guard that makes lookahead impossible.

A DataView answers questions about a date. The screen only ever talks to an AsOfView, which
raises LookaheadError if anything after the as-of close is requested, and drops any bar stamped
after it. The backtest wraps every historical view in AsOfView(asof=prior session).
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional, Protocol

from ..models import ET, Bar, Contract, OptionSnapshot, OptionStats


class LookaheadError(RuntimeError):
    pass


class ProviderUnavailable(RuntimeError):
    """A provider is not configured or could not be reached. Callers degrade gracefully."""


class DataView(Protocol):
    name: str
    has_quotes: bool          # option bars include bid/ask
    has_trade_counts: bool    # option bars include number of prints

    def daily_bars(self, symbol: str, end: date, n: int) -> list[Bar]: ...
    def intraday_bars(self, symbol: str, day: date) -> list[Bar]: ...
    def option_stats(self, symbol: str, day: date) -> Optional[OptionStats]: ...
    def chain(self, symbol: str, day: date, target: date) -> list[OptionSnapshot]: ...
    def option_bars(self, contract: Contract, day: date) -> list[Bar]: ...


class CatalystProvider(Protocol):
    name: str

    def earnings_dates(self, symbol: str, start: date, end: date) -> Optional[list[date]]: ...


class NewsProvider(Protocol):
    name: str

    def daily_counts(self, symbol: str, end: date, n: int) -> Optional[list[int]]: ...


class HistoricalOptionsProvider(Protocol):
    """Option bars for ANY contract including expired ones (IBKR cannot do this)."""
    name: str
    has_quotes: bool
    has_trade_counts: bool

    def option_bars(self, contract: Contract, day: date) -> list[Bar]: ...


class NullCatalysts:
    name = "none"

    def earnings_dates(self, symbol, start, end):
        return None


class NullNews:
    name = "none"

    def daily_counts(self, symbol, end, n):
        return None


def _cutoff(asof: date) -> datetime:
    return datetime.combine(asof, time(23, 59, 59), tzinfo=ET)


class AsOfView:
    """Wraps a DataView so nothing after the close of `asof` can be read."""

    def __init__(self, inner: DataView, asof: date):
        self.inner, self.asof = inner, asof
        self.name = inner.name
        self.has_quotes = inner.has_quotes
        self.has_trade_counts = inner.has_trade_counts

    def _check(self, day: date, what: str) -> None:
        if day > self.asof:
            raise LookaheadError(f"{what} for {day} requested but the as-of date is {self.asof}")

    def _filter(self, bars: list[Bar]) -> list[Bar]:
        cut = _cutoff(self.asof)
        return [b for b in bars if b.ts <= cut]

    def daily_bars(self, symbol, end, n):
        self._check(end, "daily bars")
        return self._filter(self.inner.daily_bars(symbol, end, n))

    def intraday_bars(self, symbol, day):
        self._check(day, "intraday bars")
        return self._filter(self.inner.intraday_bars(symbol, day))

    def option_stats(self, symbol, day):
        self._check(day, "option stats")
        return self.inner.option_stats(symbol, day)

    def chain(self, symbol, day, target):
        self._check(day, "option chain")
        return self.inner.chain(symbol, day, target)

    def option_bars(self, contract, day):
        self._check(day, "option bars")
        return self._filter(self.inner.option_bars(contract, day))
