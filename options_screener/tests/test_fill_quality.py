"""Each fill-quality check rejects on its own; PROXY labeling; round-trip math."""
import pytest
from conftest import ASOF, EXPIRY
import fakes

from options_screener import fill_quality as fqm


def assess(cfg, snap=None, days=None, quotes=True, counts=True):
    snap = snap or fakes.snapshot("ABC", EXPIRY, 100.0)
    days = days if days is not None else [fakes.good_option_day(ASOF) for _ in range(3)]
    return fqm.evaluate(snap.contract, snap, days, has_quotes=quotes, has_trade_counts=counts, cfg=cfg, source="test")


def status(fq, name):
    return next(c.status for c in fq.checks if c.name == name)


def test_good_contract_passes(cfg):
    fq = assess(cfg)
    assert fq.passed and fq.label == "VERIFIED" and fq.score == 1.0


@pytest.mark.parametrize("kwargs,check", [
    ({"spread_pct": 6.0}, "morning_spread_pct"),
    ({"volume": 2.0}, "first_hour_volume"),
    ({"trades": 2}, "median_seconds_between_prints"),
])
def test_bad_bars_reject(cfg, kwargs, check):
    fq = assess(cfg, days=[fakes.good_option_day(ASOF, **kwargs) for _ in range(3)])
    assert not fq.passed and status(fq, check) == "FAIL"


def test_close_spread_rejects(cfg):
    days = []
    for _ in range(3):
        bars = fakes.good_option_day(ASOF)
        for b in bars[-5:]:
            b.bid, b.ask = b.close * 0.95, b.close * 1.05
        days.append(bars)
    assert status(assess(cfg, days=days), "close_spread_pct") == "FAIL"


def test_low_day_volume_and_inactive_minutes(cfg):
    days = []
    for _ in range(3):
        bars = fakes.good_option_day(ASOF, volume=0, trades=0)
        for b in bars[:40]:
            b.volume, b.trades = 30, 5    # active in the first 40 min only
        days.append(bars)
    fq = assess(cfg, days=days)
    assert status(fq, "day_volume") == "FAIL" and status(fq, "active_first_hour_minutes") == "FAIL"


def test_open_interest_and_collapse(cfg):
    assert status(assess(cfg, snap=fakes.snapshot("ABC", EXPIRY, 100.0, oi=200, prev_oi=200)), "open_interest") == "FAIL"
    assert status(assess(cfg, snap=fakes.snapshot("ABC", EXPIRY, 100.0, oi=2000, prev_oi=5000)), "oi_drop_pct") == "FAIL"


def test_depth_rejects(cfg):
    assert status(assess(cfg, snap=fakes.snapshot("ABC", EXPIRY, 100.0, size=5)), "displayed_depth") == "FAIL"


def test_round_trip_cost_rejects_cheap_options(cfg):
    # $0.60 option: commissions alone (2 x $1.05) are 3.5% of a $60 position > 40% of the +5% target
    cheap = fakes.snapshot("ABC", EXPIRY, 100.0, mid=0.60)
    fq = assess(cfg, snap=cheap, days=[fakes.good_option_day(ASOF, mid=0.60) for _ in range(3)])
    assert status(fq, "round_trip_cost_pct") == "FAIL"


def test_round_trip_math(cfg):
    c = cfg["costs"]
    assert fqm.commission_per_side(1, c) == pytest.approx(1.05)        # max(1.00, 0.65) + 0.05
    assert fqm.round_trip_cost_pct(1.0, 2.0, 1, c) == pytest.approx(1.0 + 2.10 / 200 * 100)


def test_proxy_label_without_quotes(cfg):
    days = []
    for _ in range(3):
        bars = fakes.good_option_day(ASOF)
        for b in bars:
            b.bid = b.ask = None
        days.append(bars)
    fq = assess(cfg, days=days, quotes=False, counts=False)
    assert fq.label == "PROXY"
    spread = next(c for c in fq.checks if c.name == "morning_spread_pct")
    assert "PROXY" in spread.note
    assert status(fq, "median_seconds_between_prints") == "N/A"


def test_no_bars_fails(cfg):
    fq = assess(cfg, days=[[], [], []])
    assert not fq.passed and status(fq, "first_hour_volume") == "FAIL"
