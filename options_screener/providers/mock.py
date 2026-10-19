"""Deterministic synthetic market for tests, the sample report and backtest plumbing.
NOT market data. Same seed -> same numbers."""
from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, time, timedelta

from .. import market_calendar
from ..models import ET, Bar, Contract, OptionStats
from . import synthetic

PROFILE = {
    # symbol: (start price, annual vol, liquidity tier 0=deep..3=thin)
    "SPY": (560, 0.16, 0), "QQQ": (480, 0.21, 0), "AAPL": (225, 0.27, 0), "NVDA": (130, 0.55, 0),
    "TSLA": (240, 0.62, 0), "AMD": (150, 0.55, 1), "META": (560, 0.38, 1), "AMZN": (190, 0.33, 0),
    "MSFT": (420, 0.24, 1), "NFLX": (700, 0.42, 2), "JPM": (210, 0.22, 2), "XOM": (115, 0.24, 3),
}
TIER = {0: dict(spread=0.8, vol=60, trades=14, oi=20000, size=200), 1: dict(spread=1.6, vol=25, trades=6, oi=6000, size=60),
        2: dict(spread=4.5, vol=6, trades=1.5, oi=1500, size=12), 3: dict(spread=12.0, vol=1, trades=0.3, oi=300, size=4)}


def _rng(*key) -> random.Random:
    h = hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


class MockWorld:
    DEFAULT_SYMBOLS = list(PROFILE)
    name = "MOCK"
    has_quotes = True
    has_trade_counts = True

    def __init__(self, symbols=None, end: date | None = None, history_days: int = 200, future_days: int = 10,
                 earnings_on: dict | None = None, seed: int = 7):
        self.symbols = [s for s in (symbols or self.DEFAULT_SYMBOLS) if s in PROFILE]
        self.end = end or date.today()
        start = self.end - timedelta(days=history_days)
        self.sessions = market_calendar.sessions_between(start, self.end + timedelta(days=future_days))
        self.seed = seed
        # by default a few names report on the as-of session (demo); plus a regular cadence
        if earnings_on is None:
            earnings_on = {s: [self.end] for s in ("NVDA", "TSLA", "AMD", "NFLX", "XOM")}
        self._earn = {s: set(earnings_on.get(s, [])) for s in self.symbols}
        for i, s in enumerate(self.symbols):
            self._earn[s] |= {d for j, d in enumerate(self.sessions) if (j + 11 * i) % 45 == 0}
        self._minutes: dict = {}
        self._build()

    # ---------------------------------------------------------------- generation
    def _build(self):
        for s in self.symbols:
            p0, vol, _ = PROFILE[s]
            px = p0
            for d in self.sessions:
                r = _rng(self.seed, s, d)
                earn_boost = 2.5 if (market_calendar.previous_session(d) in self._earn[s]) else 1.0
                gap = r.gauss(0, vol / math.sqrt(252) * 0.45 * earn_boost)
                o = px * (1 + gap)
                trend = r.choice([-1, 1]) * abs(r.gauss(0, vol / math.sqrt(252) * 0.5))   # morning drift
                sig = vol / math.sqrt(252 * 390)
                bars, p = [], o
                for m in range(390):
                    ts = datetime.combine(d, time(9, 30), tzinfo=ET) + timedelta(minutes=m)
                    drift = trend / 60 if m < 60 else -trend / 400                   # morning move, then fade
                    nxt = p * math.exp(drift + r.gauss(0, sig * (1.6 if m < 30 else 1.0)))
                    hi = max(p, nxt) * (1 + abs(r.gauss(0, sig / 3)))
                    lo = min(p, nxt) * (1 - abs(r.gauss(0, sig / 3)))
                    bars.append(Bar(ts=ts, open=p, high=hi, low=lo, close=nxt, volume=r.randint(20_000, 60_000)))
                    p = nxt
                self._minutes[(s, d)] = bars
                px = p

    def _vol(self, s):
        return PROFILE[s][1]

    # ---------------------------------------------------------------- DataView
    def intraday_bars(self, symbol, day):
        return list(self._minutes.get((symbol, day), []))

    def daily_bars(self, symbol, end, n):
        days = [d for d in self.sessions if d <= end][-n:]
        out = []
        for d in days:
            m = self._minutes.get((symbol, d))
            if not m:
                continue
            out.append(Bar(ts=datetime.combine(d, time(16, 0), tzinfo=ET), open=m[0].open, high=max(b.high for b in m),
                           low=min(b.low for b in m), close=m[-1].close, volume=sum(b.volume for b in m)))
        return out

    def _pre_earn(self, symbol, day) -> bool:
        nxt = [d for d in self.sessions if d > day][:1]
        return day in self._earn[symbol] or bool(nxt and nxt[0] in self._earn[symbol])

    def option_stats(self, symbol, day):
        r = _rng(self.seed, "stats", symbol, day)
        tier = TIER[PROFILE[symbol][2]]
        avg = tier["vol"] * 390 * 40
        spike = 2.8 if self._pre_earn(symbol, day) else 1.0
        iv = self._vol(symbol) * (1.25 if self._pre_earn(symbol, day) else 1.0)
        hist = [self._vol(symbol) * (0.8 + 0.5 * _rng(self.seed, "ivh", symbol, i).random()) for i in range(252)]
        return OptionStats(option_volume=avg * spike * (0.8 + 0.4 * r.random()), avg_option_volume_20d=avg,
                           open_interest=tier["oi"] * 60, iv=iv, iv_prev=iv * (0.93 if spike > 1 else 1.0), iv_history=hist)

    def chain(self, symbol, day, target):
        spot = self._minutes[(symbol, day)][-1].close
        tier = TIER[PROFILE[symbol][2]]
        snaps = synthetic.synth_chain(symbol, spot, day, target, self._vol(symbol), {"contract": self._ccfg,
                                      "backtest": {}}, spread_pct=tier["spread"])
        for sn in snaps:
            dist = abs(sn.contract.strike - spot) / spot
            r = _rng(self.seed, "oi", sn.contract.occ, day)
            sn.open_interest = round(tier["oi"] * math.exp(-dist * 25) * (0.7 + 0.6 * r.random()))
            sn.prev_open_interest = round(sn.open_interest * (0.95 + 0.1 * r.random()))
            sn.volume = round(tier["vol"] * 390 * math.exp(-dist * 30))
            sn.bid_size = sn.ask_size = round(tier["size"] * math.exp(-dist * 20)) + 1
            sn.synthetic = False   # in the mock world this IS the "real" chain
        return snaps

    _ccfg = {"dte_min": 1, "dte_max": 30}

    def option_bars(self, contract: Contract, day):
        und = self._minutes.get((contract.symbol, day))
        if not und:
            return []
        tier = TIER[PROFILE[contract.symbol][2]]
        spot = und[0].open
        dist = abs(contract.strike - spot) / spot
        bars = synthetic.option_path(contract, und, self._vol(contract.symbol), tier["spread"])
        r = _rng(self.seed, "ob", contract.occ, day)
        liq = math.exp(-dist * 30)
        for b in bars:
            lam = tier["vol"] * liq * (1.8 if b.et_time < time(10, 30) else 1.0)
            v = max(0, round(r.gauss(lam, math.sqrt(lam + 1))))
            b.volume = v
            b.trades = min(v, max(0, round(r.gauss(tier["trades"] * liq, 1.0)))) if v else 0
            widen = 1.6 if b.et_time < time(9, 40) else 1.0                   # wide open
            if b.bid is not None:
                mid = (b.bid + b.ask) / 2
                half = (b.ask - b.bid) / 2 * widen
                b.bid, b.ask = max(0.0, mid - half), mid + half
            b.bid_size = b.ask_size = round(tier["size"] * liq) + 1
        return bars

    # ---------------------------------------------------------------- CatalystProvider
    def earnings_dates(self, symbol, start, end):
        return sorted(d for d in self._earn.get(symbol, set()) if start <= d <= end)
