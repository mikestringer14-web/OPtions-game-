import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rt.data import Bars  # noqa: E402

DAY = 86400
T0 = 1_577_836_800  # 2020-01-01 UTC


def make_bars(closes, symbol="TEST-USD", spread=0.01, t0=T0):
    """OHLC from a close path: open = prior close, high/low a little outside."""
    b = Bars(symbol)
    prev = closes[0]
    for k, c in enumerate(closes):
        o = prev
        b.t.append(t0 + k * DAY)
        b.o.append(o)
        b.h.append(max(o, c) * (1 + spread))
        b.l.append(min(o, c) * (1 - spread))
        b.c.append(c)
        b.v.append(1000.0)
        prev = c
    return b


def random_walk(n, seed, drift=0.0005, vol=0.03, start=100.0, symbol="RW-USD"):
    rng = random.Random(seed)
    closes, p = [], start
    for _ in range(n):
        p *= math.exp(rng.gauss(drift, vol))
        closes.append(p)
    return make_bars(closes, symbol)


@pytest.fixture
def isolate_paper(tmp_path, monkeypatch):
    import rt.paper as paper
    monkeypatch.setattr(paper, "PAPER", tmp_path / "paper")
    return tmp_path / "paper"
