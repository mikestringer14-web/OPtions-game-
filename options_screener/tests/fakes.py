"""Small hand-built data for tests (no network, no randomness)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from options_screener.models import ET, Bar, Contract, OptionSnapshot, OptionStats


def minute_bars(day: date, prices, volume=50_000.0, spread_pct=None, trades=None, option=False, start=time(9, 30)):
    """prices: list of closes (one per minute from `start`) or a function minute_index -> price."""
    n = len(prices) if isinstance(prices, list) else 390
    out, prev = [], None
    for i in range(n):
        px = prices[i] if isinstance(prices, list) else prices(i)
        o = prev if prev is not None else px
        ts = datetime.combine(day, start, tzinfo=ET) + timedelta(minutes=i)
        b = Bar(ts=ts, open=o, high=max(o, px) * 1.0005, low=min(o, px) * 0.9995, close=px, volume=volume,
                trades=trades)
        if spread_pct is not None:
            half = px * spread_pct / 200
            b.bid, b.ask = px - half, px + half
        out.append(b)
        prev = px
    return out


def daily(end: date, n=60, start_px=90.0, end_px=100.0, volume=5_000_000.0, sessions=None):
    days = sessions[-n:]
    out = []
    for i, d in enumerate(days):
        px = start_px + (end_px - start_px) * i / max(1, n - 1)
        out.append(Bar(ts=datetime.combine(d, time(16, 0), tzinfo=ET), open=px * 0.998, high=px * 1.004,
                       low=px * 0.994, close=px, volume=volume))
    return out


class FakeView:
    name = "FAKE"

    def __init__(self, has_quotes=True, has_trade_counts=True):
        self.has_quotes, self.has_trade_counts = has_quotes, has_trade_counts
        self.daily, self.intraday, self.chains, self.obars, self.stats = {}, {}, {}, {}, {}
        self.requested = []

    def daily_bars(self, symbol, end, n):
        self.requested.append(("daily", end))
        return [b for b in self.daily.get(symbol, []) if b.ts.date() <= end][-n:]

    def intraday_bars(self, symbol, day):
        self.requested.append(("intraday", day))
        return self.intraday.get((symbol, day), [])

    def option_stats(self, symbol, day):
        return self.stats.get(symbol)

    def chain(self, symbol, day, target):
        self.requested.append(("chain", day))
        return self.chains.get(symbol, [])

    def option_bars(self, contract, day):
        self.requested.append(("option", day))
        return self.obars.get((contract.occ, day), [])


class FakeCatalysts:
    name = "FAKE earnings"

    def __init__(self, dates):
        self.dates = dates

    def earnings_dates(self, symbol, start, end):
        return [d for d in self.dates.get(symbol, []) if start <= d <= end]


def snapshot(symbol, expiry, strike, right="C", mid=2.8, spread_pct=0.8, delta=0.5, oi=5000, prev_oi=5000,
             size=100, volume=3000):
    half = mid * spread_pct / 200
    return OptionSnapshot(contract=Contract(symbol, expiry, strike, right), bid=mid - half, ask=mid + half, last=mid,
                          volume=volume, open_interest=oi, prev_open_interest=prev_oi, delta=delta if right == "C" else -delta,
                          iv=0.3, bid_size=size, ask_size=size)


def good_option_day(day, mid=2.8, spread_pct=0.8, volume=20.0, trades=10):
    return minute_bars(day, [mid] * 390, volume=volume, spread_pct=spread_pct, trades=trades)


STATS = OptionStats(option_volume=300_000, avg_option_volume_20d=100_000, open_interest=900_000, iv=0.30,
                    iv_prev=0.27, iv_history=[0.2 + 0.002 * i for i in range(100)])
