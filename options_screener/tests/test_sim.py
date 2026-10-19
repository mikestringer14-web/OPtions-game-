"""Morning simulation: triggers, fill timeout / no fill, every exit rule, costs."""

import pytest
from conftest import TARGET
import fakes

from options_screener import sim
from options_screener.models import Contract

K = Contract("ABC", TARGET.replace(day=23), 100.0, "C")


def und_breakout():
    # 5-min range at 100, breakout at 9:36, stays above
    return fakes.minute_bars(TARGET, lambda i: 100.0 if i < 5 else 100.2 + 0.001 * i)


def opt(path, volume=50.0, spread=1.0):
    return fakes.minute_bars(TARGET, path, volume=volume, spread_pct=spread, trades=5)


def go(cfg, ob, ub=None, **kw):
    return sim.simulate(day=TARGET, contract=K, direction="bull", option_bars=ob, underlying_bars=ub or und_breakout(),
                        cfg=cfg, hist_median_spread_pct=1.0, quotes=True, **kw)


def test_target_exit(cfg):
    ob = opt(lambda i: 2.0 if i < 8 else 2.0 + (i - 7) * 0.05)
    t = go(cfg, ob)
    assert t.filled and t.exit_reason == "target" and t.hit_target_mid
    assert t.entry_price == pytest.approx(2.0 * 1.005, rel=1e-3)          # paid the ask
    assert t.pnl < (2.10 - 2.01) * 100                                     # commissions taken out


def test_stop_exit(cfg):
    t = go(cfg, opt(lambda i: 2.0 if i < 8 else 2.0 - (i - 7) * 0.05))
    assert t.exit_reason == "stop" and t.pnl < 0


def test_time_stop(cfg):
    t = go(cfg, opt(lambda i: 2.0 + 0.0001 * i))
    assert t.exit_reason == "time_stop" and t.exited_at == "10:30"


def test_spread_widening_exit(cfg):
    ob = opt(lambda i: 2.0)
    for b in ob[20:]:
        b.bid, b.ask = 1.9, 2.1                   # 10% spread vs 1% historical
    assert go(cfg, ob).exit_reason == "spread_widened"


def test_range_reclaim_exit(cfg):
    ub = fakes.minute_bars(TARGET, lambda i: 100.0 if i < 5 else (100.2 if i < 15 else 99.9))
    t = go(cfg, opt(lambda i: 2.0), ub)
    assert t.exit_reason == "range_reclaimed"


def test_no_fill_when_no_volume(cfg):
    ob = opt(lambda i: 2.0, volume=0)
    assert go(cfg, ob).status == "no_fill"


def test_no_fill_when_price_runs_away(cfg):
    ob = opt(lambda i: 2.0 if i <= 5 else 2.5)     # breakout triggers at 9:35 (i=5)
    for b in ob[6:]:
        b.open = b.low = 2.45                     # gapped up: never trades back down to the 2.00 limit
    assert go(cfg, ob).status == "no_fill"


def test_skip_when_live_spread_too_wide(cfg):
    assert go(cfg, opt(lambda i: 2.0, spread=8.0)).status == "skipped_spread"


def test_no_trigger(cfg):
    ub = fakes.minute_bars(TARGET, [100.0] * 390)
    assert go(cfg, opt(lambda i: 2.0), ub).status == "no_trigger"


def test_entry_delay_and_cost_multiplier(cfg):
    ob = opt(lambda i: 2.0 if i < 8 else 2.0 + (i - 7) * 0.05)
    base, delayed, costly = go(cfg, ob), go(cfg, ob, entry_delay_min=1), go(cfg, ob, cost_mult=2.0)
    assert delayed.placed_at > base.placed_at
    assert costly.pnl < base.pnl


def test_stop_checked_before_target_in_same_bar(cfg):
    ob = opt(lambda i: 2.0)
    ob[10].high, ob[10].low = 2.5, 1.0
    assert go(cfg, ob).exit_reason == "stop"
