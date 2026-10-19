"""Daily OHLCV data: Coinbase Exchange public candles (no API key) or a CSV you export."""
import csv
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/{}/candles"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass
class Bars:
    symbol: str
    t: list = field(default_factory=list)   # epoch seconds, candle open time (UTC)
    o: list = field(default_factory=list)
    h: list = field(default_factory=list)
    l: list = field(default_factory=list)
    c: list = field(default_factory=list)
    v: list = field(default_factory=list)

    def __len__(self):
        return len(self.c)

    def date(self, i):
        return datetime.fromtimestamp(self.t[i], timezone.utc).strftime("%Y-%m-%d")

    def slice(self, start, end):
        b = Bars(self.symbol)
        for name in ("t", "o", "h", "l", "c", "v"):
            setattr(b, name, getattr(self, name)[start:end])
        return b


def check_quality(bars, step=86400):
    """Return a list of human-readable data problems (gaps, bad candles)."""
    problems = []
    for i in range(1, len(bars)):
        gap = bars.t[i] - bars.t[i - 1]
        if gap != step:
            problems.append(f"{bars.symbol}: gap of {gap / step:.1f} days before {bars.date(i)}")
    for i in range(len(bars)):
        if not (bars.l[i] <= min(bars.o[i], bars.c[i]) <= max(bars.o[i], bars.c[i]) <= bars.h[i]) or bars.c[i] <= 0:
            problems.append(f"{bars.symbol}: inconsistent OHLC on {bars.date(i)}")
    return problems


def fetch_coinbase_daily(product, start="2017-01-01", end=None, pause=0.35):
    """Page through Coinbase daily candles, 300 per request, oldest first."""
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else datetime.now(timezone.utc)
    rows = {}
    cur = start_dt
    while cur < end_dt:
        nxt = min(cur + timedelta(days=299), end_dt)
        r = requests.get(COINBASE_CANDLES.format(product),
                         params={"granularity": 86400, "start": cur.isoformat(), "end": nxt.isoformat()},
                         headers={"User-Agent": "trading-research/1.0"}, timeout=15)
        r.raise_for_status()
        for t, low, high, op, close, vol in r.json():
            rows[int(t)] = (op, high, low, close, vol)
        cur = nxt
        time.sleep(pause)
    today_open = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    rows.pop(today_open, None)  # never keep the still-forming candle
    b = Bars(product)
    for t in sorted(rows):
        op, high, low, close, vol = rows[t]
        b.t.append(t); b.o.append(float(op)); b.h.append(float(high))
        b.l.append(float(low)); b.c.append(float(close)); b.v.append(float(vol))
    return b


def save_csv(bars, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for i in range(len(bars)):
            w.writerow([bars.t[i], bars.o[i], bars.h[i], bars.l[i], bars.c[i], bars.v[i]])


def load_csv(path, symbol=None):
    """Loads our cache or a TradingView 'Export chart data' CSV (time,open,high,low,close,Volume)."""
    path = Path(path)
    b = Bars(symbol or path.stem)
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): v for k, v in row.items()}
            t = row["time"]
            t = int(float(t)) if t.replace(".", "").isdigit() else int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
            b.t.append(t)
            for name, key in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
                getattr(b, name).append(float(row[key]))
            b.v.append(float(row.get("volume") or 0))
    return b


def load_or_fetch(product, start="2017-01-01", refresh=False):
    path = DATA_DIR / f"{product}_1d.csv"
    if path.exists() and not refresh:
        return load_csv(path, product)
    bars = fetch_coinbase_daily(product, start)
    save_csv(bars, path)
    return bars
