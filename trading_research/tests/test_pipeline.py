"""End-to-end plumbing on SYNTHETIC data. These numbers are not results."""
import json
from datetime import datetime, timezone

import pytest

from rt import paper, validate
from rt.data import load_csv, save_csv, check_quality

from conftest import DAY, random_walk

CFG = validate.load_config()


def synthetic(n=1500):
    return {s: random_walk(n, seed, symbol=s) for seed, s in enumerate(CFG["symbols"], start=1)}


def test_validate_runs_and_has_all_sections(tmp_path):
    cfg = {**CFG, "split": {"oos_start": "2023-01-01"}}
    r = validate.validate("A_trend_breakout", synthetic(), cfg, log_path=tmp_path / "log.jsonl")
    for k in ("dev", "oos", "per_symbol_oos", "by_year", "cost_stress", "perturbation", "gates",
              "oos_regimes", "worked_example", "risk_levels_oos"):
        assert k in r
    assert len(r["gates"]) == 11 and r["verdict"].split(":")[0] in ("PASS", "FAIL")
    lines = (tmp_path / "log.jsonl").read_text().splitlines()
    assert len(lines) == r["total_backtests_run"]       # every run is on record
    md = validate.render_markdown(r)
    assert "SIMULATION RESULTS, NOT REAL TRADING" in md and "## $100 worked example" in md


@pytest.mark.parametrize("name", ["B_rsi2_pullback", "C_sma_trend_filter"])
def test_validate_other_strategies(name):
    r = validate.validate(name, synthetic(1200), CFG)
    assert r["gates"]


def test_csv_round_trip_and_quality(tmp_path):
    b = random_walk(50, 3, symbol="BTC-USD")
    save_csv(b, tmp_path / "BTC-USD_1d.csv")
    b2 = load_csv(tmp_path / "BTC-USD_1d.csv", "BTC-USD")
    assert b2.c == pytest.approx(b.c) and b2.t == b.t
    b2.t[10] += DAY
    assert check_quality(b2)


def _now_after(bars):
    last = max(b.t[-1] for b in bars.values())
    return datetime.fromtimestamp(last + DAY + 3600, timezone.utc)


def test_paper_is_idempotent(isolate_paper, monkeypatch):
    bars = synthetic(1200)
    cfg = {**CFG}
    first = next(iter(bars.values()))
    start = datetime.fromtimestamp(first.t[400], timezone.utc).strftime("%Y-%m-%d")
    paper.save_state({"started_at": start, "seen_trades": 0, "seen_log": 0, "halted": False, "halt_windows": [],
                      "consecutive_errors": 0, "last_equity": None, "alerts": []})
    now = _now_after(bars)
    s1 = paper.run_once(cfg, bars=bars, now=now, sample_spreads=False)
    lines1 = (isolate_paper / "journal.jsonl").read_text().splitlines()
    s2 = paper.run_once(cfg, bars=bars, now=now, sample_spreads=False)
    lines2 = (isolate_paper / "journal.jsonl").read_text().splitlines()
    closed = lambda ls: [l for l in ls if '"paper_trade_closed"' in l]
    assert s1["seen_trades"] == s2["seen_trades"] > 0
    assert closed(lines1) == closed(lines2)               # no duplicate trades on re-run
    assert (isolate_paper / "daily_report.md").exists()


def test_paper_stale_data_alerts_and_does_nothing(isolate_paper):
    bars = synthetic(400)
    late = datetime.fromtimestamp(max(b.t[-1] for b in bars.values()) + 5 * DAY, timezone.utc)
    s = paper.run_once(CFG, bars=bars, now=late, sample_spreads=False)
    assert "stale" in (isolate_paper / "ALERT.txt").read_text()
    assert s["seen_trades"] == 0


def test_paper_halt_and_resume(isolate_paper):
    bars = synthetic(600)
    now = _now_after(bars)
    paper.run_once(CFG, bars=bars, now=now, sample_spreads=False)
    st = paper.load_state()
    st["last_equity"] = 1000.0                               # force a huge "daily loss"
    paper.save_state(st)
    s = paper.run_once(CFG, bars=bars, now=now, sample_spreads=False)
    assert s["halted"] and s["halt_windows"][-1][1] is None
    paper.main(["--resume"])
    st = paper.load_state()
    assert not st["halted"] and st["halt_windows"][-1][1] is not None


def test_paper_fetch_errors_halt_after_three(isolate_paper, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("network down")
    monkeypatch.setattr(paper, "fetch_bars", boom)
    for _ in range(3):
        s = paper.run_once(CFG)
    assert s["halted"] and s["consecutive_errors"] == 3
