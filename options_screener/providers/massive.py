"""Massive (formerly Polygon.io) historical options adapter. PAID data source.

Endpoints, from Massive's official REST docs (massive.com/docs/rest/options/...):
  * Custom Bars: GET /v2/aggs/ticker/{optionsTicker}/range/{multiplier}/{timespan}/{from}/{to}
      fields t (ms), o, h, l, c, v, vw, n (number of transactions). Included in Options Basic and
      above; history depth depends on the plan (Basic/Starter: 2 years).
  * Quotes:      GET /v3/quotes/{optionsTicker}?timestamp.gte=..&timestamp.lt=..  (bid/ask/sizes)
      Only on Options Advanced (individual). Set MASSIVE_HAS_QUOTES=true only if your plan has it.
Options tickers are OCC style with an "O:" prefix, e.g. O:SPY241220P00720000.
Authentication: the API key is sent in an Authorization: Bearer header; it is never logged.
Plan rate limits differ (Basic is very limited), so requests are spaced by MASSIVE_RPM.
"""
from __future__ import annotations

import json
import time as _time
from datetime import date, datetime, time, timezone
from pathlib import Path

import requests

from ..config import DATA, env
from ..models import ET, Bar, Contract
from .base import ProviderUnavailable

BASE = "https://api.massive.com"


class MassiveOptions:
    name = "Massive (Polygon) options"

    def __init__(self, api_key: str | None = None, has_quotes: bool | None = None, rpm: float | None = None,
                 cache_dir: Path = DATA / "cache" / "massive", session=None):
        self.key = api_key or env("MASSIVE_API_KEY")
        if not self.key:
            raise ProviderUnavailable("MASSIVE_API_KEY is not set")
        self.has_quotes = (env("MASSIVE_HAS_QUOTES") == "true") if has_quotes is None else has_quotes
        self.has_trade_counts = True
        self.min_gap = 60.0 / float(rpm or env("MASSIVE_RPM", "5") or 5)
        self.cache = cache_dir
        self.http = session or requests.Session()
        self._last = 0.0

    def _get(self, url: str, params: dict | None = None) -> dict:
        wait = self._last + self.min_gap - _time.monotonic()
        if wait > 0:
            _time.sleep(wait)
        self._last = _time.monotonic()
        try:
            r = self.http.get(url, params=params, headers={"Authorization": f"Bearer {self.key}"}, timeout=30)
        except requests.RequestException as e:
            raise ProviderUnavailable(f"Massive request failed: {type(e).__name__}") from None
        if r.status_code != 200:
            raise ProviderUnavailable(f"Massive HTTP {r.status_code}")
        return r.json()

    def _cached(self, kind: str, contract: Contract, day: date, fetch):
        path = self.cache / kind / f"{contract.occ}_{day}.json"
        if path.exists():
            return json.loads(path.read_text())
        data = fetch()
        if day < date.today():          # past sessions never change
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
        return data

    def option_bars(self, contract: Contract, day: date) -> list[Bar]:
        tk = f"O:{contract.occ}"
        aggs = self._cached("aggs", contract, day, lambda: self._get(
            f"{BASE}/v2/aggs/ticker/{tk}/range/1/minute/{day}/{day}",
            {"adjusted": "true", "sort": "asc", "limit": 50000}).get("results") or [])
        bars = []
        for a in aggs:
            ts = datetime.fromtimestamp(a["t"] / 1000, tz=timezone.utc).astimezone(ET)
            if time(9, 30) <= ts.time() < time(16, 0):
                bars.append(Bar(ts=ts, open=a["o"], high=a["h"], low=a["l"], close=a["c"], volume=a.get("v", 0),
                                trades=a.get("n")))
        if self.has_quotes and bars:
            self._attach_quotes(contract, day, bars)
        return bars

    def _attach_quotes(self, contract: Contract, day: date, bars: list[Bar]) -> None:
        def fetch():
            out, url = [], f"{BASE}/v3/quotes/O:{contract.occ}"
            params = {"timestamp.gte": f"{day}T13:30:00Z", "timestamp.lt": f"{day}T21:00:00Z",
                      "order": "asc", "sort": "timestamp", "limit": 50000}
            while url:
                page = self._get(url, params)
                out += [[q["sip_timestamp"], q.get("bid_price"), q.get("ask_price"), q.get("bid_size"), q.get("ask_size")]
                        for q in page.get("results") or []]
                url, params = page.get("next_url"), None
            return out
        last_by_minute = {}
        for ns, bid, ask, bs, az in self._cached("quotes", contract, day, fetch):
            ts = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).astimezone(ET)
            last_by_minute[(ts.hour, ts.minute)] = (bid, ask, bs, az)
        for b in bars:
            q = last_by_minute.get((b.et_time.hour, b.et_time.minute))
            if q:
                b.bid, b.ask, b.bid_size, b.ask_size = q


class ThetaDataOptions:
    """Placeholder. ThetaData's endpoints were not verified for this build, so this adapter is
    intentionally not implemented rather than guessed. Use Massive or CSV."""
    name = "ThetaData (not implemented)"

    def __init__(self, *a, **k):
        raise ProviderUnavailable("ThetaData adapter not implemented (endpoints not verified); use massive or csv")
