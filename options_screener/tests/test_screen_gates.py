"""All three gates are required; scoring math; lookahead guard; degradation."""
import copy

import pytest
from conftest import ASOF, EXPIRY, TARGET
import fakes

from options_screener import signals
from options_screener.models import OptionStats
from options_screener.providers.base import AsOfView, LookaheadError, ProviderUnavailable
from options_screener.screen import screen_day


def run(world, cfg, catalysts=None, **kw):
    v, cats, _ = world
    return screen_day(AsOfView(v, ASOF), ASOF, TARGET, cfg, catalysts or cats, None, **kw)


def test_baseline_passes_all_three(world, cfg):
    res = run(world, cfg)
    assert len(res.candidates) == 1
    c = res.candidates[0]
    assert c.gate_a and c.gate_b and c.gate_c and c.direction == "bull"
    assert c.snapshot.contract.right == "C" and c.fill.label == "VERIFIED"
    assert c.plan["time_stop"].startswith("10:30") and "limit between mid" in c.plan["entry_order"]
    assert c.iv_crush_risk is True


def test_fails_gate_a_without_catalyst(world, cfg):
    res = run(world, cfg, catalysts=fakes.FakeCatalysts({}))
    assert res.candidates == [] and res.rejected["A: no catalyst"] == 1


def test_fails_gate_b_on_flat_mornings(world, cfg):
    v, cats, sessions = world
    for d in sessions[-25:-1]:
        v.intraday[("ABC", d)] = fakes.minute_bars(d, [100.0] * 390)
    res = run(world, cfg)
    assert res.candidates == [] and res.rejected["B: move potential"] == 1


def test_fails_gate_c_goes_to_near_misses(world, cfg):
    v, cats, sessions = world
    snap = v.chains["ABC"][0]
    for d in sessions[-5:]:
        v.obars[(snap.contract.occ, d)] = fakes.good_option_day(d, spread_pct=9.0)
    res = run(world, cfg)
    assert res.candidates == []
    assert len(res.near_misses) == 1 and "morning_spread_pct" in res.near_misses[0].reject_reason


def test_adjacent_strike_substitution(world, cfg):
    v, cats, sessions = world
    bad = v.chains["ABC"][0]
    alt = fakes.snapshot("ABC", EXPIRY, 101.0, delta=0.40)
    v.chains["ABC"] = [bad, alt]
    for d in sessions[-5:]:
        v.obars[(bad.contract.occ, d)] = fakes.good_option_day(d, volume=1)        # ideal fails volume
        v.obars[(alt.contract.occ, d)] = fakes.good_option_day(d)
    res = run(world, cfg)
    c = res.candidates[0]
    assert c.snapshot.contract.strike == 101.0
    assert c.fill.substituted_from and "100" in c.fill.substituted_from
    assert any("adjacent" in n for n in c.notes)


def test_bearish_setup_picks_a_put(world, cfg):
    v, cats, sessions = world
    v.daily["ABC"] = fakes.daily(ASOF, n=60, start_px=110, end_px=100, sessions=sessions)
    v.intraday[("ABC", ASOF)] = fakes.minute_bars(ASOF, lambda i: 100.0 - max(0, i - 330) * 0.02)
    def drop(i):
        return 100.0 if i < 5 else 100.0 - min(i - 5, 60) * 0.025
    for d in sessions[-25:-1]:
        v.intraday[("ABC", d)] = fakes.minute_bars(d, drop)
    put = fakes.snapshot("ABC", EXPIRY, 100.0, right="P")
    v.chains["ABC"] = [put]
    for d in sessions[-5:]:
        v.obars[(put.contract.occ, d)] = fakes.good_option_day(d)
    res = run(world, cfg)
    assert res.candidates and res.candidates[0].direction == "bear" and res.candidates[0].snapshot.contract.right == "P"


def test_premium_cap_and_delta_band(world, cfg, cfg100):
    # the old US$300 premium cap is replaced by the C$100 affordability rule (ask + fees + FX)
    v, cats, sessions = world
    v.chains["ABC"] = [fakes.snapshot("ABC", EXPIRY, 90.0, delta=0.9)]
    res = run(world, cfg)
    assert res.candidates == [] and res.rejected["no eligible contract"] == 1
    v.chains["ABC"] = [fakes.snapshot("ABC", EXPIRY, 100.0, mid=3.5)]
    res = run(world, cfg100)
    assert res.candidates == [] and res.rejected["unaffordable at C$100"] == 1


def test_screen_refuses_unguarded_view(world, cfg):
    v, cats, _ = world
    with pytest.raises(LookaheadError):
        screen_day(v, ASOF, TARGET, cfg, cats)


def test_asof_view_blocks_future_reads(world):
    v, _, _ = world
    g = AsOfView(v, ASOF)
    with pytest.raises(LookaheadError):
        g.intraday_bars("ABC", TARGET)
    with pytest.raises(LookaheadError):
        g.option_bars(v.chains["ABC"][0].contract, TARGET)


def test_screen_never_reads_past_asof(world, cfg):
    v, _, _ = world
    run(world, cfg)
    assert all(day <= ASOF for _, day in v.requested)


def test_future_data_does_not_change_the_screen(world, cfg):
    v, cats, _ = world
    before = run(world, cfg)
    v2 = copy.deepcopy(v)
    v2.intraday[("ABC", TARGET)] = fakes.minute_bars(TARGET, [50.0] * 390)    # crash tomorrow
    after = screen_day(AsOfView(v2, ASOF), ASOF, TARGET, cfg, cats)
    assert [c.combined for c in before.candidates] == [c.combined for c in after.candidates]


def test_missing_providers_degrade(world, cfg):
    class Broken:
        name = "broken"

        def earnings_dates(self, *a):
            raise ProviderUnavailable("down")
    res = run(world, cfg, catalysts=Broken())
    assert res.candidates == [] and any("earnings provider: down" in m for m in res.missing)
    assert any("news" in m for m in res.missing)


def test_one_bad_symbol_does_not_stop_the_run(world, cfg):
    v, cats, _ = world
    cfg2 = {**cfg, "universe": {**cfg["universe"], "symbols": ["ZZZ", "ABC"]}}

    def boom(symbol, end, n):
        if symbol == "ZZZ":
            raise RuntimeError("bad data")
        return fakes.FakeView.daily_bars(v, symbol, end, n)
    v.daily_bars = boom
    res = screen_day(AsOfView(v, ASOF), ASOF, TARGET, cfg2, cats)
    assert len(res.candidates) == 1 and res.errors and res.errors[0].startswith("ZZZ")


# ---------------------------------------------------------------- scoring math

def test_catalyst_scores(cfg):
    assert signals.catalyst_score("X", ASOF, TARGET, [ASOF], None, cfg)[0] == 1.0
    assert signals.catalyst_score("X", ASOF, TARGET, [TARGET], None, cfg)[2] is True
    assert signals.catalyst_score("X", ASOF, TARGET, [], None, cfg)[0] == 0.0
    s, label, _ = signals.catalyst_score("X", ASOF, TARGET, None, [2] * 20 + [10], cfg)
    assert 0.5 <= s <= 1.0 and "news spike" in label
    cfg_ev = {**cfg, "events": [{"date": TARGET.isoformat(), "name": "CPI"}]}
    assert signals.catalyst_score("X", ASOF, TARGET, None, None, cfg_ev) == (0.6, "scheduled: CPI", False)


def test_unusual_volume_and_iv():
    assert signals.unusual_volume_score(OptionStats(option_volume=300, avg_option_volume_20d=100)) == 1.0
    assert signals.unusual_volume_score(OptionStats(option_volume=100, avg_option_volume_20d=100)) == 0.0
    assert signals.unusual_volume_score(None) is None
    score, rank, change = signals.iv_metrics(OptionStats(iv=0.30, iv_prev=0.25, iv_history=[0.2 + 0.01 * i for i in range(21)]))
    assert rank == pytest.approx(0.5) and change == pytest.approx(0.05) and score == pytest.approx(0.5)


def test_weighted_renormalizes_missing(cfg):
    assert signals.weighted({"momentum": 1.0, "iv": None}, cfg, ["momentum", "iv"]) == 1.0
    assert signals.weighted({}, cfg, ["momentum"]) is None


def test_move_proxy(cfg):
    d = ASOF
    up = fakes.minute_bars(d, lambda i: 100.0 if i < 5 else 100.0 + min(i - 5, 60) * 0.025)
    flat = fakes.minute_bars(d, [100.0] * 390)
    # proxy now returns a walk-forward MoveResult; the old float behaviour lives on as *_legacy
    r = signals.morning_option_move_proxy(up, 0.3, cfg)
    assert r.hit_target and r.exit_reason == "target"
    assert signals.morning_option_move_proxy(flat, 0.3, cfg).exit_reason == "no_trigger"
    assert signals.morning_option_move_proxy_legacy(up, 0.3, cfg) > 5
    assert signals.morning_option_move_proxy_legacy(flat, 0.3, cfg) == 0.0
    assert signals.move_potential_rate([up] * 6 + [flat] * 4, 0.3, cfg) == pytest.approx(0.6)
