"""DataView for backtests: underlying history from one source, option bars from a
HistoricalOptionsProvider (IBKR cannot serve EXPIRED options), or an underlying proxy."""
from __future__ import annotations

from .. import pricing
from . import synthetic


class HistoricalView:
    def __init__(self, underlying, options=None, cfg=None):
        self.u, self.o, self.cfg = underlying, options, cfg
        self.proxy = options is None
        self.name = f"underlying: {underlying.name}; options: " + (options.name if options else "NONE -> UNDERLYING PROXY")
        self.has_quotes = bool(options and options.has_quotes)
        self.has_trade_counts = bool(options and options.has_trade_counts)

    def daily_bars(self, symbol, end, n):
        return self.u.daily_bars(symbol, end, n)

    def intraday_bars(self, symbol, day):
        return self.u.intraday_bars(symbol, day)

    def option_stats(self, symbol, day):
        return None   # historical ticker-level option volume/IV is not available from these sources

    def _vol(self, symbol, day):
        return pricing.realized_vol([b.close for b in self.u.daily_bars(symbol, day, 30)])

    def chain(self, symbol, day, target):
        daily = self.u.daily_bars(symbol, day, 1)
        if not daily:
            return []
        return synthetic.synth_chain(symbol, daily[-1].close, day, target, self._vol(symbol, day), self.cfg,
                                     spread_pct=self.cfg["fill_quality"]["proxy_spread_pct"])

    def option_bars(self, contract, day):
        if self.o is not None:
            return self.o.option_bars(contract, day)
        und = self.u.intraday_bars(contract.symbol, day)
        size = self.cfg["fill_quality"]["depth_multiple"] * self.cfg["contract"]["contracts"]
        bars = synthetic.option_path(contract, und, self._vol(contract.symbol, day),
                                     self.cfg["fill_quality"]["proxy_spread_pct"], volume_per_min=size)
        for b in bars:          # proxy bars carry no real quotes
            b.bid = b.ask = None
        return bars
