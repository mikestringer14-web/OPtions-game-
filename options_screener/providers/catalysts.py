"""Earnings calendar sources.

Alpha Vantage EARNINGS_CALENDAR (documented at alphavantage.co/documentation, "Earnings Calendar"):
  GET https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey=KEY
  Returns CSV: symbol,name,reportDate,fiscalDateEnding,estimate,currency. Upcoming dates only and
  NO time of day, so "after close / before open" cannot be confirmed; the report says so.
  Free API key: alphavantage.co/support/#api-key. Cached once per day.
Backtests need historical report dates: put them in data/earnings.csv (symbol,date).
"""
from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

import requests

from ..config import DATA, env
from .base import NullCatalysts, ProviderUnavailable
from .csv_provider import CSVEarnings

URL = "https://www.alphavantage.co/query"


class AlphaVantageEarnings:
    name = "Alpha Vantage earnings calendar"

    def __init__(self, api_key: str | None = None, cache_dir: Path = DATA / "cache", http=None):
        self.key = api_key or env("ALPHAVANTAGE_API_KEY")
        if not self.key:
            raise ProviderUnavailable("ALPHAVANTAGE_API_KEY is not set")
        self.cache, self.http = cache_dir, http or requests
        self._rows = None

    def _load(self) -> dict:
        if self._rows is not None:
            return self._rows
        path = self.cache / f"earnings_{date.today():%Y%m%d}.csv"
        if path.exists():
            text = path.read_text()
        else:
            try:
                r = self.http.get(URL, params={"function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": self.key},
                                  timeout=30)
            except requests.RequestException as e:
                raise ProviderUnavailable(f"Alpha Vantage request failed: {type(e).__name__}") from None
            if r.status_code != 200 or not r.text.lower().startswith("symbol"):
                raise ProviderUnavailable(f"Alpha Vantage returned HTTP {r.status_code} / unexpected body")
            text = r.text
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        rows: dict = {}
        for row in csv.DictReader(io.StringIO(text)):
            try:
                rows.setdefault(row["symbol"].upper(), []).append(date.fromisoformat(row["reportDate"]))
            except (KeyError, ValueError):
                continue
        self._rows = rows
        return rows

    def earnings_dates(self, symbol, start, end):
        return sorted(d for d in self._load().get(symbol.upper(), []) if start <= d <= end)


def from_env():
    """Alpha Vantage if a key is set, else data/earnings.csv if present, else none."""
    if env("ALPHAVANTAGE_API_KEY"):
        return AlphaVantageEarnings()
    if (DATA / "earnings.csv").exists():
        return CSVEarnings()
    return NullCatalysts()
