"""OPTIONAL, UNUSED BY DEFAULT. Nothing in the screen, report or backtest imports this module, and
ib_async is not a requirement. Kept only in case a read-only IBKR data feed is wanted later.

IBKR (TWS / IB Gateway) READ-ONLY data view via ib_async.

  * Connects with readonly=True and only to the paper ports (7497 TWS, 4002 Gateway).
  * Every historical request goes through the pacing limiter (see ratelimit.py).
  * IBKR serves bars for listed (not expired) options only; EXPIRED options have no history,
    so backtests need a HistoricalOptionsProvider (Massive / CSV).
  * Option bars: TRADES (with barCount = number of prints) + BID_ASK, where per IBKR's
    historical data types the BID_ASK bar's open is the time-average bid and its close is the
    time-average ask. BID_ASK requests count double against pacing.
  * Market data needs subscriptions on the live account that the paper account shares:
    OPRA (US options, L1) and US equity data (see README). Without them IBKR returns delayed
    data or errors; the screen degrades and the report says what was missing.
This module is NOT exercised against a live gateway in CI; tests use mocks.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from ..config import PAPER_PORTS, env
from ..models import ET, Bar, Contract, OptionSnapshot, OptionStats
from ..ratelimit import PacingLimiter
from .base import ProviderUnavailable


class IBKRView:
    name = "IBKR TWS API (read-only)"
    has_quotes = True
    has_trade_counts = True

    def __init__(self, ib, cfg, limiter: Optional[PacingLimiter] = None, small_bar_limiter: Optional[PacingLimiter] = None):
        self.ib, self.cfg = ib, cfg
        # Bars >= 1 min: IBKR lifted the hard 60/10min cap but still soft-throttles, so we keep the
        # identical-request and same-contract rules and a configurable budget (default 300 per 10 min).
        self.limiter = limiter or PacingLimiter(max_per_window=int(env("IBKR_SOFT_REQ_PER_10MIN", "300")))
        # Bars <= 30 s: the documented hard limits (60 per 10 minutes). Not used by the screen today.
        self.small_bar_limiter = small_bar_limiter or PacingLimiter()
        self._stock_cache: dict = {}

    @classmethod
    def connect_readonly(cls, cfg):
        from ib_async import IB

        host, port = env("IBKR_HOST", "127.0.0.1"), int(env("IBKR_PORT", "4002"))
        if port not in PAPER_PORTS:
            raise ProviderUnavailable(f"port {port} is not a paper port {sorted(PAPER_PORTS)}; refusing to connect")
        ib = IB()
        try:
            ib.connect(host, port, clientId=int(env("IBKR_CLIENT_ID", "17")), readonly=True, timeout=15)
        except Exception as e:
            raise ProviderUnavailable(f"could not connect to IB Gateway/TWS at {host}:{port}: {type(e).__name__}") from None
        return cls(ib, cfg)

    # ---------------------------------------------------------------- helpers
    def _stock(self, symbol):
        from ib_async import Stock

        if symbol not in self._stock_cache:
            c = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(c)
            self._stock_cache[symbol] = c
        return self._stock_cache[symbol]

    def _hist(self, contract, key, end, duration, bar, what, use_rth=True):
        small = bar.split()[-1].startswith("sec")
        (self.small_bar_limiter if small else self.limiter).acquire(str(getattr(contract, "conId", key)), f"{key}|{end}|{duration}|{bar}|{what}", what)
        return self.ib.reqHistoricalData(contract, endDateTime=end, durationStr=duration, barSizeSetting=bar,
                                         whatToShow=what, useRTH=use_rth, formatDate=2)

    @staticmethod
    def _bar(b) -> Bar:
        ts = b.date if isinstance(b.date, datetime) else datetime.combine(b.date, time(16, 0))
        ts = ts.replace(tzinfo=ET) if ts.tzinfo is None else ts.astimezone(ET)
        return Bar(ts=ts, open=b.open, high=b.high, low=b.low, close=b.close, volume=float(b.volume or 0),
                   trades=int(b.barCount) if getattr(b, "barCount", None) not in (None, -1) else None)

    # ---------------------------------------------------------------- DataView
    def daily_bars(self, symbol, end, n):
        bars = self._hist(self._stock(symbol), symbol, f"{end:%Y%m%d} 23:59:59 US/Eastern", f"{int(n * 1.6) + 5} D",
                          "1 day", "TRADES")
        return [self._bar(b) for b in bars][-n:]

    def intraday_bars(self, symbol, day):
        bars = self._hist(self._stock(symbol), symbol, f"{day:%Y%m%d} 16:00:00 US/Eastern", "1 D", "1 min", "TRADES")
        return [x for x in (self._bar(b) for b in bars) if x.ts.date() == day]

    def option_stats(self, symbol, day):
        stock = self._stock(symbol)
        t = self.ib.reqMktData(stock, genericTickList="100,101,105,106")   # opt volume, OI, avg opt volume, IV
        self.ib.sleep(2.5)
        self.ib.cancelMktData(stock)
        ivh = self._hist(stock, symbol, "", "1 Y", "1 day", "OPTION_IMPLIED_VOLATILITY")
        hist = [b.close for b in ivh if b.close and b.close > 0]
        vol = (t.callVolume or 0) + (t.putVolume or 0)
        oi = (t.callOpenInterest or 0) + (t.putOpenInterest or 0)
        iv = t.impliedVolatility if t.impliedVolatility == t.impliedVolatility else (hist[-1] if hist else None)
        return OptionStats(option_volume=vol or None, avg_option_volume_20d=t.avOptionVolume or None,
                           open_interest=oi or None, iv=iv, iv_prev=hist[-2] if len(hist) >= 2 else None, iv_history=hist)

    def chain(self, symbol, day, target):
        from ib_async import Option

        stock = self._stock(symbol)
        spot = self.daily_bars(symbol, day, 1)[-1].close
        params = [p for p in self.ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId) if p.exchange == "SMART"]
        if not params:
            return []
        c = self.cfg["contract"]
        exps = sorted(e for e in params[0].expirations
                      if c["dte_min"] <= (datetime.strptime(e, "%Y%m%d").date() - target).days <= c["dte_max"])[:4]
        strikes = sorted(params[0].strikes, key=lambda k: abs(k - spot))[:12]
        contracts = [Option(symbol, e, k, r, "SMART", tradingClass=params[0].tradingClass) for e in exps
                     for k in strikes for r in ("C", "P")]
        contracts = [q for q in self.ib.qualifyContracts(*contracts) if q.conId]
        out = []
        for i in range(0, len(contracts), 40):                      # stay well under market-data line limits
            batch = contracts[i:i + 40]
            tickers = [self.ib.reqMktData(q, genericTickList="100,101") for q in batch]
            self.ib.sleep(3)
            for q, t in zip(batch, tickers, strict=True):
                g = t.modelGreeks
                oi = t.callOpenInterest if q.right == "C" else t.putOpenInterest
                out.append(OptionSnapshot(
                    contract=Contract(symbol, datetime.strptime(q.lastTradeDateOrContractMonth, "%Y%m%d").date(), q.strike, q.right),
                    bid=t.bid if t.bid and t.bid > 0 else None, ask=t.ask if t.ask and t.ask > 0 else None,
                    last=t.last if t.last == t.last else None, volume=t.volume if t.volume == t.volume else None,
                    open_interest=oi if oi == oi else None, delta=g.delta if g else None, iv=g.impliedVol if g else None,
                    bid_size=t.bidSize, ask_size=t.askSize))
                self.ib.cancelMktData(q)
        return out

    def option_bars(self, contract: Contract, day: date):
        from ib_async import Option

        q = Option(contract.symbol, f"{contract.expiry:%Y%m%d}", contract.strike, contract.right, "SMART")
        self.ib.qualifyContracts(q)
        end = f"{day:%Y%m%d} 16:00:00 US/Eastern"
        trades = {b.ts: b for b in (self._bar(x) for x in self._hist(q, contract.occ, end, "1 D", "1 min", "TRADES"))}
        for x in self._hist(q, contract.occ, end, "1 D", "1 min", "BID_ASK"):
            b = self._bar(x)
            tb = trades.get(b.ts)
            if tb is None:      # a minute with quotes but no trades
                tb = trades[b.ts] = Bar(ts=b.ts, open=(x.open + x.close) / 2, high=(x.open + x.close) / 2,
                                        low=(x.open + x.close) / 2, close=(x.open + x.close) / 2, volume=0, trades=0)
            tb.bid, tb.ask = x.open, x.close        # time-average bid / ask
        return [b for b in sorted(trades.values(), key=lambda b: b.ts) if b.ts.date() == day]
