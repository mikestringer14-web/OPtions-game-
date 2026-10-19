"""Deterministic, long-only, spot strategies. Signals are evaluated on a COMPLETED bar i
and acted on by the engine at a later bar's open. Every rule here only reads indicators
at index <= i."""
from . import indicators as ind
from .indicators import isnan


class Strategy:
    name = "base"
    defaults = {}

    def __init__(self, **params):
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise ValueError(f"unknown params for {self.name}: {unknown}")
        self.p = {**self.defaults, **params}

    def prepare(self, bars):
        self.bars = bars
        self.x = self.indicators(bars)
        return self

    def warmup(self):
        return max(v for k, v in self.p.items() if isinstance(v, int)) + 1

    # --- hooks
    def indicators(self, bars):
        return {}

    def entry(self, i):
        return False

    def initial_stop(self, i, fill_price):
        raise NotImplementedError

    def update_stop(self, i, pos):
        return pos["stop"]

    def exit_at_close(self, i, pos):
        return False


class TrendBreakout(Strategy):
    """Donchian-style breakout with a trend filter and ATR trailing stop (Turtle family)."""
    name = "A_trend_breakout"
    defaults = {"entry_len": 20, "exit_len": 10, "trend_len": 100, "atr_len": 14, "atr_mult": 3.0}

    def indicators(self, b):
        p = self.p
        return {"hi": ind.highest_prior(b.h, p["entry_len"]), "lo": ind.lowest_prior(b.l, p["exit_len"]),
                "ema": ind.ema(b.c, p["trend_len"]), "atr": ind.atr(b.h, b.l, b.c, p["atr_len"])}

    def entry(self, i):
        x, c = self.x, self.bars.c[i]
        if any(isnan(x[k][i]) for k in x):
            return False
        return c > x["hi"][i] and c > x["ema"][i]

    def initial_stop(self, i, fill_price):
        x = self.x
        return max(self.bars.c[i] - self.p["atr_mult"] * x["atr"][i], x["lo"][i])

    def update_stop(self, i, pos):
        x = self.x
        trail = max(pos.get("trail") or 0.0, self.bars.c[i] - self.p["atr_mult"] * x["atr"][i])
        pos["trail"] = trail
        return max(trail, x["lo"][i])


class RSI2Pullback(Strategy):
    """Short-term pullback inside a long-term uptrend (Connors-style RSI(2))."""
    name = "B_rsi2_pullback"
    defaults = {"rsi_len": 2, "buy_below": 10.0, "trend_len": 200, "exit_len": 5, "max_bars": 10, "stop_pct": 8.0}

    def indicators(self, b):
        p = self.p
        return {"rsi": ind.rsi(b.c, p["rsi_len"]), "trend": ind.sma(b.c, p["trend_len"]),
                "exit_ma": ind.sma(b.c, p["exit_len"])}

    def entry(self, i):
        x, c = self.x, self.bars.c[i]
        if any(isnan(x[k][i]) for k in x):
            return False
        return c > x["trend"][i] and x["rsi"][i] < self.p["buy_below"]

    def initial_stop(self, i, fill_price):
        return fill_price * (1 - self.p["stop_pct"] / 100.0)

    def exit_at_close(self, i, pos):
        return self.bars.c[i] > self.x["exit_ma"][i] or (i - pos["entry_index"]) >= self.p["max_bars"]


class TrendFilter200(Strategy):
    """Long-term trend filter: hold while close > SMA(n), exit on a close below.
    A wide ATR disaster stop is used for position sizing and gap protection."""
    name = "C_sma_trend_filter"
    defaults = {"trend_len": 200, "atr_len": 14, "disaster_atr": 4.0}

    def indicators(self, b):
        return {"sma": ind.sma(b.c, self.p["trend_len"]), "atr": ind.atr(b.h, b.l, b.c, self.p["atr_len"])}

    def entry(self, i):
        x = self.x
        if isnan(x["sma"][i]) or isnan(x["atr"][i]) or i == 0 or isnan(x["sma"][i - 1]):
            return False
        # enter on the cross, not on every bar above, so a stop-out doesn't immediately re-enter
        return self.bars.c[i] > x["sma"][i] and self.bars.c[i - 1] <= x["sma"][i - 1]

    def initial_stop(self, i, fill_price):
        return fill_price - self.p["disaster_atr"] * self.x["atr"][i]

    def exit_at_close(self, i, pos):
        return self.bars.c[i] < self.x["sma"][i]


STRATEGIES = {s.name: s for s in (TrendBreakout, RSI2Pullback, TrendFilter200)}
