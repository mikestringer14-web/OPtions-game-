"""Backtest: no lookahead, the PASS gate, PASS-file locking, proxy/mock never pass."""
import json
from datetime import date

import pytest
from conftest import ASOF, TARGET
import fakes

from options_screener import backtest
from options_screener.config import config_hash
from options_screener.providers.base import NullNews
from options_screener.sim import Trade


def test_collect_reads_only_prior_close(world, cfg):
    v, cats, _ = world
    dcs = backtest.collect(v, cats, NullNews(), [TARGET], cfg)
    assert dcs and dcs[0].day == TARGET
    assert all(day <= ASOF for _, day in v.requested)          # screening never touched the target day


def test_simulation_reads_the_target_day(world, cfg):
    v, cats, sessions = world
    dcs = backtest.collect(v, cats, NullNews(), [TARGET], cfg)
    v.intraday[("ABC", TARGET)] = fakes.minute_bars(TARGET, lambda i: 100.0 if i < 5 else 100.3)
    v.obars[(dcs[0].cand.snapshot.contract.occ, TARGET)] = fakes.good_option_day(TARGET)
    trades = backtest.Simulator(v, cfg).run(dcs, b_min=0.0)
    assert len(trades) == 1 and trades[0].status in ("filled", "no_fill")


class FakeSim:
    def __init__(self, trades):
        self.trades = trades

    def run(self, dcs, **kw):
        return [t for t in self.trades if t.day in {d.day for d in dcs}]


def trades(n, pnl=10.0, status="filled", start=0):
    days = [date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i) for i in range(start, start + n)]
    return [Trade(day=d, symbol="ABC", contract="c", right="C", dte=5, direction="bull", earnings=False, score=0.7,
                  fq_score=1.0, status=status, pnl=pnl + (i % 3), net_ret=0.05 + 0.01 * (i % 3),
                  minutes_to_fill=1.0, minutes_held=5.0) for i, d in enumerate(days)]


def dcs_for(ts):
    return [backtest.DayCandidate(t.day, None, 1.0, True) for t in ts]


def test_gate_passes_only_with_everything(cfg):
    ts = trades(400)
    days = sorted({t.day for t in ts})
    r = backtest.validate(dcs_for(ts), days, FakeSim(ts), cfg, "VERIFIED")
    assert r["verdict"] == "PASS", r["reasons"]


@pytest.mark.parametrize("mode", ["PROXY", "MOCK", "BARS-ONLY"])
def test_non_verified_data_never_passes(cfg, mode):
    ts = trades(400)
    r = backtest.validate(dcs_for(ts), sorted({t.day for t in ts}), FakeSim(ts), cfg, mode)
    assert r["verdict"] == "FAIL" and any("data mode" in x for x in r["reasons"])


def test_gate_fails_on_few_trades_losses_and_fill_rate(cfg):
    few = trades(150)
    r = backtest.validate(dcs_for(few), sorted({t.day for t in few}), FakeSim(few), cfg, "VERIFIED")
    assert any("OOS trades" in x for x in r["reasons"])
    losing = trades(400, pnl=-10.0)
    for t in losing:
        t.net_ret = -0.05
    r = backtest.validate(dcs_for(losing), sorted({t.day for t in losing}), FakeSim(losing), cfg, "VERIFIED")
    assert any("expectancy" in x for x in r["reasons"]) and any("bootstrap" in x for x in r["reasons"])
    mixed = trades(400) + trades(400, status="no_fill", start=0)
    r = backtest.validate(dcs_for(mixed), sorted({t.day for t in mixed}), FakeSim(mixed), cfg, "VERIFIED")
    assert any("fill rate" in x for x in r["reasons"])


def test_pass_file_written_and_removed(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(backtest, "PASS_FILE", tmp_path / "PASS.json")
    monkeypatch.setattr(backtest, "REPORTS", tmp_path)
    ts = trades(400)
    r = backtest.validate(dcs_for(ts), sorted({t.day for t in ts}), FakeSim(ts), cfg, "VERIFIED")
    backtest.write(r, date(2026, 1, 1), date(2027, 1, 1), "test", cfg)
    data = json.loads((tmp_path / "PASS.json").read_text())
    assert data["verdict"] == "PASS" and data["config_hash"] == config_hash(cfg) and data["mode"] == "VERIFIED"
    r2 = backtest.validate(dcs_for(ts), sorted({t.day for t in ts}), FakeSim(ts), cfg, "PROXY")
    backtest.write(r2, date(2026, 1, 1), date(2027, 1, 1), "test", cfg)
    assert not (tmp_path / "PASS.json").exists()


def test_mock_backtest_end_to_end_fails_cleanly(cfg):
    from options_screener.providers.mock import MockWorld
    world = MockWorld(["SPY", "NVDA", "TSLA"], end=date(2026, 9, 30), history_days=150, earnings_on={})
    from options_screener import market_calendar
    days = market_calendar.sessions_between(date(2026, 8, 1), date(2026, 9, 30))
    dcs = backtest.collect(world, world, NullNews(), days, cfg, world.symbols)
    r = backtest.validate(dcs, days, backtest.Simulator(world, cfg), cfg, "MOCK")
    assert r["verdict"] == "FAIL"
    md = backtest.render(r, days[0], days[-1], "MOCK", cfg)
    assert "GATE: FAIL" in md and "without C" in md and "Bootstrap" in md
