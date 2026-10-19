"""Massive (formerly Polygon.io) adapters.

MassiveView: the FREE-tier DataView used by `screen --provider massive` (see below).
MassiveOptions: historical option minute bars for backtests (any plan with option aggregates).

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

import hashlib
import json
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import requests

from .. import pricing
from ..config import DATA, env
from ..models import ET, Bar, Contract, OptionSnapshot
from ..ratelimit import SlidingWindowLimiter
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




# =====================================================================================
# FREE TIER DataView (screen --provider massive)
# =====================================================================================
# Verified against Massive's docs (Oct 2026):
#   Stocks custom bars   GET /v2/aggs/ticker/{stocksTicker}/range/{mult}/{timespan}/{from}/{to}
#                        massive.com/docs/rest/stocks/aggregates/custom-bars
#   Options contracts    GET /v3/reference/options/contracts   (strike, expiry, type, shares_per_contract)
#                        massive.com/docs/rest/options/contracts/all-contracts
#   Options custom bars  GET /v2/aggs/ticker/{optionsTicker}/range/{mult}/{timespan}/{from}/{to}
#                        massive.com/docs/rest/options/aggregates/custom-bars   (t,o,h,l,c,v,vw,n)
#   NOT on the free tier: option chain snapshot (OI, greeks, IV, quotes)
#                        massive.com/docs/rest/options/snapshots/option-chain-snapshot
#                        and quotes (Options Advanced only).
#   Rate limit: 5 requests/minute, counted separately for stocks, options and reference data
#                        massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis
# Data is END-OF-DAY / delayed, never live. Fields the free tier lacks are never invented:
#   bid/ask           -> None; the ask used for sizing is a MODEL ESTIMATE (close + proxy half-spread)
#   IV / delta        -> "derived": Black-Scholes implied vol from the option's EOD close
#   open interest, displayed size, ticker option volume, IV history -> n/a (free tier), checks DEGRADED


FREE_TIER_RPM = 5


class MassiveClient:
    """GET with Bearer auth, per-bucket rate limiting and a disk cache for responses about the past."""

    def __init__(self, api_key: str | None = None, cache_dir: Path = DATA / "cache" / "massive", session=None,
                 rpm: int = FREE_TIER_RPM, clock=_time.monotonic, sleep=_time.sleep, today: date | None = None):
        self.key = api_key or env("MASSIVE_API_KEY")
        if not self.key:
            raise ProviderUnavailable("MASSIVE_API_KEY is not set")
        self.cache, self.http, self.today = cache_dir, session or requests.Session(), today or date.today()
        self.limiters = {b: SlidingWindowLimiter(rpm, 60.0, clock, sleep) for b in ("stocks", "options", "reference")}
        self.sleep = sleep
        self.calls = {b: 0 for b in self.limiters}
        self.cache_hits = 0

    def _path(self, bucket: str, path: str, params: dict) -> Path:
        h = hashlib.sha256((path + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:24]
        return self.cache / bucket / f"{h}.json"

    def get(self, bucket: str, path: str, params: dict | None = None, cache_until: date | None = None) -> dict:
        """cache_until = the latest date the response covers; it is cached only if that is in the past."""
        params = dict(params or {})
        cp = self._path(bucket, path, params)
        if cp.exists():
            self.cache_hits += 1
            return json.loads(cp.read_text())
        for attempt in (1, 2):
            self.limiters[bucket].acquire()
            self.calls[bucket] += 1
            try:
                r = self.http.get(BASE + path, params=params, headers={"Authorization": f"Bearer {self.key}"}, timeout=30)
            except requests.RequestException as e:
                raise ProviderUnavailable(f"Massive request failed: {type(e).__name__}") from None
            if r.status_code == 429 and attempt == 1:
                self.sleep(60.0)            # free tier: 5/min; wait out the window once
                continue
            if r.status_code != 200:
                raise ProviderUnavailable(f"Massive HTTP {r.status_code} on {path.split('/')[1]} {bucket}")
            body = r.json()
            if cache_until is not None and cache_until < self.today:
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_text(json.dumps(body))
            return body
        raise ProviderUnavailable("Massive HTTP 429 (rate limit)")  # pragma: no cover


def _bars(results, regular_only=True, daily=False) -> list[Bar]:
    out = []
    for a in results or []:
        ts = datetime.fromtimestamp(a["t"] / 1000, tz=timezone.utc).astimezone(ET)
        if daily:
            ts = datetime.combine(ts.date(), time(16, 0), tzinfo=ET)
        elif regular_only and not (time(9, 30) <= ts.time() < time(16, 0)):
            continue
        out.append(Bar(ts=ts, open=a["o"], high=a["h"], low=a["l"], close=a["c"], volume=a.get("v", 0) or 0,
                       trades=a.get("n")))
    return out


class MassiveView:
    """DataView over the Massive FREE tier for one as-of date. Everything is end-of-day data."""
    name = "Massive free tier (end-of-day, delayed)"
    has_quotes = False
    has_trade_counts = True

    def __init__(self, asof: date, cfg: dict, client: MassiveClient | None = None, max_contracts_per_right: int = 4):
        self.asof, self.cfg = asof, cfg
        self.client = client or MassiveClient()
        self.max_per_right = max_contracts_per_right
        self.latest_bar_date: date | None = None
        self._minutes: dict = {}
        self._daily: dict = {}
        self._opt: dict = {}
        self.degraded = [
            "live bid/ask: n/a (free tier) -> ask is a MODEL ESTIMATE (EOD close + proxy half-spread); affordability DEGRADED",
            "open interest, displayed size: n/a (free tier) -> OI / OI-collapse / depth checks DEGRADED",
            "ticker option volume, IV history: n/a (free tier) -> unusual-volume and IV-rank signals DEGRADED",
            "contract IV and delta: derived (Black-Scholes from the EOD close)",
            "option quotes: n/a (free tier) -> fill-quality spreads are PROXY (bar high-low)",
        ]

    # ------------------------------------------------------------ underlying
    def daily_bars(self, symbol, end, n):
        if symbol not in self._daily:
            start = self.asof - timedelta(days=int(130 * 1.5))
            body = self.client.get("stocks", f"/v2/aggs/ticker/{symbol}/range/1/day/{start}/{self.asof}",
                                   {"adjusted": "true", "sort": "asc", "limit": 50000}, cache_until=self.asof)
            bars = _bars(body.get("results"), daily=True)
            self._daily[symbol] = bars
            if bars:
                d = bars[-1].ts.date()
                self.latest_bar_date = max(self.latest_bar_date or d, d)
        return [b for b in self._daily[symbol] if b.ts.date() <= end][-n:]

    def intraday_bars(self, symbol, day):
        if symbol not in self._minutes:
            start = self.asof - timedelta(days=40)       # covers the 20-session move-potential lookback
            body = self.client.get("stocks", f"/v2/aggs/ticker/{symbol}/range/1/minute/{start}/{self.asof}",
                                   {"adjusted": "true", "sort": "asc", "limit": 50000}, cache_until=self.asof)
            by_day: dict = {}
            for b in _bars(body.get("results")):
                by_day.setdefault(b.ts.date(), []).append(b)
            self._minutes[symbol] = by_day
        return list(self._minutes[symbol].get(day, []))

    def option_stats(self, symbol, day):
        return None                                      # n/a on the free tier (needs the chain snapshot)

    # ------------------------------------------------------------ options
    def _option_minutes(self, contract: Contract) -> dict:
        if contract.occ not in self._opt:
            start = self.asof - timedelta(days=10)       # covers the fill-quality lookback
            body = self.client.get("options", f"/v2/aggs/ticker/O:{contract.occ}/range/1/minute/{start}/{self.asof}",
                                   {"adjusted": "true", "sort": "asc", "limit": 50000}, cache_until=self.asof)
            by_day: dict = {}
            for b in _bars(body.get("results")):
                by_day.setdefault(b.ts.date(), []).append(b)
            self._opt[contract.occ] = by_day
        return self._opt[contract.occ]

    def option_bars(self, contract, day):
        return list(self._option_minutes(contract).get(day, []))

    def contracts(self, symbol, day, target, spot):
        c = self.cfg["contract"]
        lo, hi = target + timedelta(days=max(0, c["dte_min"])), target + timedelta(days=c["dte_max"])
        body = self.client.get("reference", "/v3/reference/options/contracts",
                               {"underlying_ticker": symbol, "as_of": str(day), "expiration_date.gte": str(lo),
                                "expiration_date.lte": str(hi), "strike_price.gte": round(spot * 0.85, 2),
                                "strike_price.lte": round(spot * 1.15, 2), "limit": 1000}, cache_until=day)
        out = []
        for r in body.get("results") or []:
            right = {"call": "C", "put": "P"}.get(r.get("contract_type"))
            if right is None:
                continue
            k = Contract(symbol, date.fromisoformat(r["expiration_date"]), float(r["strike_price"]), right)
            mult = int(r.get("shares_per_contract") or 0)
            if r.get("ticker") != f"O:{k.occ}":
                mult = mult if mult != 100 else 0       # adjusted / non-standard root: never treated as standard
            out.append((k, mult))
        return out

    def chain(self, symbol, day, target):
        daily = self.daily_bars(symbol, day, 30)
        if not daily:
            return []
        spot = daily[-1].close
        rv = pricing.realized_vol([b.close for b in daily])
        c, fq = self.cfg["contract"], self.cfg["fill_quality"]
        listed = self.contracts(symbol, day, target, spot)
        expiries = sorted({k.expiry for k, _ in listed})[:2]
        pick, odd = [], []
        for right in ("C", "P"):
            cands = []
            for k, mult in listed:
                if k.right != right or k.expiry not in expiries:
                    continue
                if mult != 100:
                    odd.append(OptionSnapshot(contract=k, bid=None, ask=None, multiplier=mult))   # rejected by eligible()
                    continue
                d = abs(pricing.delta(spot, k.strike, pricing.year_fraction((k.expiry - day).days), rv, right))
                if c["delta_min"] - 0.10 <= d <= c["delta_max"] + 0.10:     # pre-filter only; real delta is derived below
                    cands.append((abs(d - (c["delta_min"] + c["delta_max"]) / 2), k, mult))
            pick += sorted(cands, key=lambda x: x[0])[: self.max_per_right]
        snaps = list(odd)
        for _, k, mult in pick:
            bars = self._option_minutes(k).get(day, [])
            if not bars:
                continue                                  # no prints that day: nothing to price
            close = bars[-1].close
            t = pricing.year_fraction((k.expiry - day).days + 0.25)
            iv = pricing.implied_vol(close, spot, k.strike, t, k.right)
            half = close * fq["proxy_spread_pct"] / 200
            snaps.append(OptionSnapshot(
                contract=k, bid=None, ask=round(close + max(0.005, half), 2), last=close,
                volume=sum(b.volume for b in bars), open_interest=None, prev_open_interest=None,
                delta=round(pricing.delta(spot, k.strike, t, iv, k.right), 3) if iv else None, iv=iv,
                multiplier=mult, ask_estimated=True, iv_source="derived"))
        return snaps


class ThetaDataOptions:
    """Placeholder. ThetaData's endpoints were not verified for this build, so this adapter is
    intentionally not implemented rather than guessed. Use Massive or CSV."""
    name = "ThetaData (not implemented)"

    def __init__(self, *a, **k):
        raise ProviderUnavailable("ThetaData adapter not implemented (endpoints not verified); use massive or csv")
