"""Indicators. Value at index i only uses data up to and including bar i (no lookahead)."""
import math

NaN = float("nan")


def sma(x, n):
    out, s = [NaN] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(x, n):
    out, k, prev = [NaN] * len(x), 2.0 / (n + 1), None
    for i, v in enumerate(x):
        if i == n - 1:
            prev = sum(x[:n]) / n          # seed with SMA, like TradingView
        elif i >= n:
            prev = v * k + prev * (1 - k)
        if prev is not None:
            out[i] = prev
    return out


def rma(x, n):
    """Wilder smoothing (used by ATR and RSI)."""
    out, prev = [NaN] * len(x), None
    for i, v in enumerate(x):
        if i == n - 1:
            prev = sum(x[:n]) / n
        elif i >= n:
            prev = (prev * (n - 1) + v) / n
        if prev is not None:
            out[i] = prev
    return out


def atr(high, low, close, n):
    tr = [high[0] - low[0]] + [max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
                               for i in range(1, len(close))]
    return rma(tr, n)


def rsi(close, n):
    gains = [0.0] + [max(close[i] - close[i - 1], 0.0) for i in range(1, len(close))]
    losses = [0.0] + [max(close[i - 1] - close[i], 0.0) for i in range(1, len(close))]
    # first change is at index 1, so smoothing starts there
    g, l = rma(gains[1:], n), rma(losses[1:], n)
    out = [NaN]
    for a, b in zip(g, l):
        if math.isnan(a):
            out.append(NaN)
        elif b == 0:
            out.append(100.0)
        else:
            out.append(100.0 - 100.0 / (1 + a / b))
    return out


def highest_prior(x, n):
    """Highest of the n bars BEFORE bar i (TradingView: ta.highest(x, n)[1])."""
    return [max(x[i - n:i]) if i >= n else NaN for i in range(len(x))]


def lowest_prior(x, n):
    return [min(x[i - n:i]) if i >= n else NaN for i in range(len(x))]


def isnan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))
