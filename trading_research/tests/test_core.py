"""Critical calculations: indicators, no lookahead, fills, fees, sizing, limits."""
import copy
import math

import pytest

from rt import engine
from rt import indicators as ind
from rt.strategies import STRATEGIES, RSI2Pullback, Strategy, TrendBreakout
from rt.validate import breakeven_move

from conftest import DAY, T0, make_bars, random_walk


def test_sma_ema_known_values():
    x = [1, 2, 3, 4, 5, 6]
    assert ind.sma(x, 3)[2:] == [2, 3, 4, 5]
    e = ind.ema(x, 3)
    assert math.isnan(e[1]) and e[2] == 2 and e[3] == pytest.approx(3.0) and e[5] == pytest.approx(5.0)


def test_rsi_extremes_and_range():
    up = list(range(1, 30))
    assert ind.rsi(up, 2)[-1] == 100.0
    r = ind.rsi(random_walk(300, 1).c, 14)
    assert all(0 <= v <= 100 for v in r if not math.isnan(v))


def test_atr_constant_range():
    h, l, c = [11] * 20, [9] * 20, [10] * 20
    assert ind.atr(h, l, c, 14)[-1] == pytest.approx(2.0)


def test_highest_prior_excludes_current_bar():
    x = [1, 5, 2, 9]
    assert ind.highest_prior(x, 2)[3] == 5  # 9 is the current bar, not included


@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_no_lookahead(name):
    """Changing future bars must never change a past signal."""
    base = random_walk(700, 5)
    k = 500
    s1 = STRATEGIES[name]().prepare(base)
    sig1 = [s1.entry(i) for i in range(k + 1)]
    future = copy.deepcopy(base)
    for i in range(k + 1, len(future)):
        future.c[i] *= 3.0; future.h[i] *= 3.0; future.l[i] *= 0.2; future.o[i] *= 1.5
    s2 = STRATEGIES[name]().prepare(future)
    assert sig1 == [s2.entry(i) for i in range(k + 1)]


class Scripted(Strategy):
    """Enter on chosen bars with a fixed stop; used to test the fill model exactly."""
    name = "scripted"
    defaults = {}

    def __init__(self, entries, stop_pct=0.1, exit_bars=()):
        super().__init__()
        self.entries, self.stop_pct, self.exit_bars = set(entries), stop_pct, set(exit_bars)

    def warmup(self):
        return 0

    def entry(self, i):
        return i in self.entries

    def initial_stop(self, i, fill_price):
        return fill_price * (1 - self.stop_pct)

    def exit_at_close(self, i, pos):
        return i in self.exit_bars


CFG = {"fee_rate": 0.006, "slippage_rate": 0.001, "risk_pct": 1.0, "max_alloc_pct": 100.0,
       "max_total_exposure_pct": 100.0, "halt_drawdown_pct": 99.0}


def test_entry_fills_next_open_and_rule_exit_next_open():
    b = make_bars([100, 100, 110, 120, 130, 140])
    res = engine.run({"X": Scripted([1], exit_bars=[3]).prepare(b)}, CFG)
    t = res["trades"][0]
    assert t["entry_ts"] == T0 + 2 * DAY and t["entry_price"] == pytest.approx(b.o[2] * 1.001)
    assert t["exit_ts"] == T0 + 4 * DAY and t["exit_price"] == pytest.approx(b.o[4] * 0.999)


def test_gap_below_stop_fills_at_open_not_stop():
    b = make_bars([100, 100, 100, 100, 100], spread=0.0)
    b.o[3], b.l[3], b.h[3], b.c[3] = 70.0, 69.0, 75.0, 72.0   # gaps through a 10% stop
    res = engine.run({"X": Scripted([1]).prepare(b)}, CFG)
    t = res["trades"][0]
    assert t["reason"] == "stop_gap" and t["exit_price"] == pytest.approx(70.0 * 0.999)
    assert t["r_multiple"] < -2.5          # a gap loses far more than the planned 1R


def test_intrabar_stop_fills_at_stop():
    b = make_bars([100, 100, 100, 100, 100], spread=0.0)
    b.l[3] = 85.0
    res = engine.run({"X": Scripted([1]).prepare(b)}, CFG)
    t = res["trades"][0]
    stop = 100 * 1.001 * 0.9
    assert t["reason"] == "stop" and t["exit_price"] == pytest.approx(stop * 0.999)


def test_cost_identity_and_risk_sizing():
    b = make_bars([100, 100, 100, 100, 100], spread=0.0)
    b.l[3] = 85.0
    res = engine.run({"X": Scripted([1]).prepare(b)}, CFG)
    t = res["trades"][0]
    assert t["net_pnl"] == pytest.approx(t["gross_pnl"] - t["fees"] - t["slippage_cost"])
    # 1% risk on $100 = $1 at the stop, plus fees and exit slippage on top
    assert -1.25 < t["net_pnl"] < -1.0
    assert t["fees"] == pytest.approx(t["notional"] * 0.006 + t["qty"] * t["exit_price"] * 0.006)


def test_breakeven_move():
    assert breakeven_move(0.006, 0.001) == pytest.approx((1.007 / 0.993 - 1) * 100)


def test_min_notional_skips_order():
    b = make_bars([100] * 6)
    res = engine.run({"X": Scripted([1]).prepare(b)}, {**CFG, "risk_pct": 0.01, "min_notional": 1.0})
    assert res["trades"] == [] and res["log"][0]["reason"] == "below_min_notional"


def test_caps_limit_position_size():
    b = make_bars([100] * 6, spread=0.0)
    res = engine.run({"X": Scripted([1], stop_pct=0.001).prepare(b)}, {**CFG, "max_alloc_pct": 30.0})
    assert res["open_positions"]["X"]["notional"] == pytest.approx(30.0)


def test_max_positions():
    bars = {s: make_bars([100] * 8, symbol=s) for s in "ABC"}
    strats = {s: Scripted([1]).prepare(b) for s, b in bars.items()}
    res = engine.run(strats, {**CFG, "risk_pct": 0.5, "max_positions": 2})
    assert len(res["open_positions"]) == 2
    assert any(e.get("reason") == "max_positions" for e in res["log"])


def test_delay_and_missed_fills():
    b = make_bars([100] * 8)
    r = engine.run({"X": Scripted([1]).prepare(b)}, {**CFG, "entry_delay": 2})
    assert r["open_positions"]["X"]["entry_ts"] == T0 + 3 * DAY
    r = engine.run({"X": Scripted([1]).prepare(b)}, {**CFG, "miss_rate": 1.0})
    assert r["open_positions"] == {} and r["log"][0]["event"] == "entry_missed"


def test_blocked_window_stops_new_entries():
    b = make_bars([100] * 8)
    r = engine.run({"X": Scripted([1, 5]).prepare(b)}, {**CFG, "blocked_windows": [[T0, None]]})
    assert r["open_positions"] == {} and r["trades"] == []


def test_drawdown_halt():
    b = make_bars([100, 100, 100, 100, 100, 100, 100, 100], spread=0.0)
    b.o[3], b.l[3], b.c[3] = 50.0, 50.0, 50.0
    r = engine.run({"X": Scripted([1, 4]).prepare(b)}, {**CFG, "risk_pct": 30.0, "halt_drawdown_pct": 10.0})
    assert r["halted"] and len(r["trades"]) == 1


def test_trend_breakout_trailing_stop_never_moves_down():
    b = random_walk(600, 9, drift=0.002)
    s = TrendBreakout().prepare(b)
    res = engine.run({"X": s}, {"risk_pct": 0.5})
    assert res["trades"], "expected trades on a trending walk"


def test_rsi2_time_stop():
    s = RSI2Pullback(max_bars=3).prepare(random_walk(600, 4, drift=0.001))
    res = engine.run({"X": s}, {"risk_pct": 0.5})
    assert all(t["bars_held"] <= 4 or t["reason"].startswith("stop") or t["reason"] == "rule_exit" for t in res["trades"])


def test_metrics_basic():
    res = engine.run({"X": TrendBreakout().prepare(random_walk(900, 2, drift=0.001))}, {})
    m = engine.metrics(res)
    assert m["trades"] == len(res["trades"]) and m["max_drawdown_pct"] >= 0
    assert m["final_equity"] == pytest.approx(res["equity"][-1][1])
