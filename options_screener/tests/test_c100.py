"""C$100 single-position model, the signal fixes, banners, NO TRADE, Massive free tier (recorded
fixtures, no network), and running without ib_async."""
import json
import math
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import ASOF, EXPIRY, ROOT, TARGET
import fakes

from options_screener import fx, report, signals, sizing
from options_screener.models import ET, TORONTO, Contract, OptionStats
from options_screener.providers.base import AsOfView, NullNews, ProviderUnavailable
from options_screener.providers.massive import MassiveClient, MassiveView
from options_screener.screen import screen_day

FIX = Path(__file__).parent / "fixtures" / "massive"
FAKE_KEY = "k" * 8 + "-test"


# ---------------------------------------------------------------- sizing (section 2)

def test_budget_and_max_premium(cfg100):
    assert sizing.usd_budget(cfg100) == pytest.approx(100 * 0.72 * 0.985)                  # 70.92
    assert sizing.max_premium_per_contract(cfg100) == pytest.approx((70.92 - 0.10) / 100)  # 0.7082


def test_sizing_uses_the_ask_with_fees_and_fx(cfg100):
    z = sizing.size(0.50, 12.0, "C", cfg100)
    assert z.contracts == math.floor(70.92 / (0.50 * 100 + 0.10)) == 1
    assert z.entry_cost_usd == pytest.approx(50.10)
    assert z.entry_cost_cad == pytest.approx(50.10 / (0.72 * 0.985), abs=0.01)
    assert z.max_loss_cad == z.entry_cost_cad and z.pct_of_capital == pytest.approx(z.entry_cost_cad, abs=0.1)
    assert z.breakeven == pytest.approx(12.0 + 0.50 + 0.002)
    # -15% stop: sell 0.425 x 100 - fee, converted back with the FX buffer
    back = (0.425 * 100 - 0.10) * 0.985 / 0.72
    assert z.stop_loss_cad == pytest.approx(z.entry_cost_cad - back, abs=0.01)
    assert z.target_value_cad[5] < 0.05 * z.entry_cost_cad          # FX both ways eats most of a +5% move
    assert z.target_value_cad[10] > z.target_value_cad[5]


def test_mid_would_fit_but_the_ask_does_not(cfg100):
    # mid 0.70 fits under 0.708, ask 0.72 does not: the ask decides
    assert sizing.size(0.70, 12.0, "C", cfg100).affordable
    z = sizing.size(0.72, 12.0, "C", cfg100)
    assert z.contracts == 0 and not z.affordable and z.reason == sizing.UNAFFORDABLE == "unaffordable at C$100"


def test_several_cheap_contracts_but_one_position(cfg100):
    z = sizing.size(0.20, 5.0, "P", cfg100)
    assert z.contracts == 3 and z.entry_cost_cad <= 100          # several contracts of ONE position
    assert z.breakeven == pytest.approx(5.0 - 0.20 - 0.002)


def test_non_standard_multiplier_and_missing_ask_rejected(cfg100):
    assert sizing.size(0.30, 12.0, "C", cfg100, multiplier=50).reason.startswith("non-standard multiplier")
    assert sizing.size(None, 12.0, "C", cfg100).reason == "no ask price"


def test_fx_cost_and_rate_change_the_budget(cfg100):
    lower = sizing.usd_budget(cfg100, cad_usd=0.70)
    assert lower < sizing.usd_budget(cfg100) and lower == pytest.approx(100 * 0.70 * 0.985)


def test_single_position_cap_in_config(cfg100):
    a = cfg100["account"]
    assert (a["capital_cad"], a["max_risk_per_trade_pct"], a["max_open_positions"], a["max_new_trades_per_day"]) == (100, 100, 1, 1)
    assert cfg100["strategies"]["actionable"] == ["long_call", "long_put"]
    assert cfg100["strategies"]["max_actionable"] == 3


def test_fx_valet_parse_cache_and_fallback(tmp_path, cfg100):
    body = {"observations": [{"d": "2026-10-16", "FXUSDCAD": {"v": "1.3900"}}]}
    http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: body))
    r = fx.get_rate(cfg100, http=http, cache_dir=tmp_path, today=date(2026, 10, 19))
    assert r.tag == "VERIFIED" and r.cad_usd == pytest.approx(1 / 1.39, abs=1e-5) and r.as_of == "2026-10-16"
    assert (tmp_path / "fx_20261019.json").exists()
    bad = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=503, json=lambda: {}))
    f = fx.get_rate(cfg100, http=bad, cache_dir=tmp_path, today=date(2026, 10, 20))
    assert f.tag == "ASSUMPTION" and f.cad_usd == 0.72
    assert fx.get_rate(cfg100, use_network=False).tag == "ASSUMPTION"


# ---------------------------------------------------------------- screen + C$100

def test_affordable_candidate_carries_sizing_and_scenarios(world, cfg100):
    v, cats, sessions = world
    ideal = fakes.snapshot("ABC", EXPIRY, 100.0, mid=0.60)
    v.chains["ABC"] = [ideal]
    for d in sessions[-5:]:
        v.obars[(ideal.contract.occ, d)] = fakes.good_option_day(d, mid=0.60)
    res = screen_day(AsOfView(v, ASOF), ASOF, TARGET, cfg100, cats, NullNews())
    assert len(res.candidates) == 1, (res.rejected, [c.reject_reason for c in res.near_misses])
    c = res.candidates[0]
    assert c.sizing.contracts == 1 and c.sizing.entry_cost_cad <= 100
    assert set(c.scenarios) == {"underlying +1%", "underlying -1%", "flat", "IV +5pt", "IV -5pt"}
    assert c.scenarios["underlying +1%"]["option"] > c.scenarios["flat"]["option"] > c.scenarios["underlying -1%"]["option"]
    assert c.move_rate_legacy is not None and c.move_stretch_rate is not None
    md = report.render_screen(res, cfg100, source="FAKE", catalysts="FAKE", news="none",
                              run_time=datetime(2026, 10, 16, 20, 0, tzinfo=TORONTO), provider="mock")
    for s in ("| contracts | cost CAD | % of C$100 | max loss CAD |", "Scenarios at 10:30 ET (Black-Scholes, MODEL ESTIMATE)",
              "Size: 1 contract(s)", "at most 2 revisions", "Tags:", "Post-market review template"):
        assert s in md
    assert report.NO_TRADE not in md


def test_unaffordable_goes_to_funnel_and_near_misses(world, cfg100):
    v, cats, _ = world                 # the fixture contract asks ~US$2.81 = ~C$396
    res = screen_day(AsOfView(v, ASOF), ASOF, TARGET, cfg100, cats, NullNews())
    assert res.candidates == [] and res.rejected["unaffordable at C$100"] == 1
    assert res.near_misses and res.near_misses[0].reject_reason.startswith("unaffordable at C$100")


def test_no_trade_prints_exact_line(world, cfg100):
    v, cats, _ = world
    res = screen_day(AsOfView(v, ASOF), ASOF, TARGET, cfg100, cats, NullNews())
    md = report.render_screen(res, cfg100, source="FAKE", catalysts="FAKE", news="none",
                              run_time=datetime(2026, 10, 16, 20, 0, tzinfo=TORONTO), provider="mock")
    assert ("NO TRADE — no verified opportunity meets the capital, liquidity, pricing, and defined-risk "
            "requirements.") in md.splitlines()
    assert "| unaffordable at C$100 | 1 |" in md


def test_max_three_actionable(world, cfg):
    from options_screener import config as config_mod
    v, cats, sessions = world
    for s in ("ABD", "ABE", "ABF", "ABG"):
        v.daily[s], v.stats[s], v.chains[s] = v.daily["ABC"], v.stats["ABC"], []
        for d in sessions[-25:]:
            v.intraday[(s, d)] = v.intraday[("ABC", d)]
        snap = fakes.snapshot(s, EXPIRY, 100.0)
        v.chains[s] = [snap]
        for d in sessions[-5:]:
            v.obars[(snap.contract.occ, d)] = fakes.good_option_day(d)
        cats.dates[s] = [ASOF]
    c = config_mod.merge(cfg, {"universe": {"symbols": ["ABC", "ABD", "ABE", "ABF", "ABG"]}})
    res = screen_day(AsOfView(v, ASOF), ASOF, TARGET, c, cats, NullNews())
    assert len(res.candidates) == 3


def test_banner_selection():
    assert report.banner("mock", ASOF, ASOF) == [report.MOCK_BANNER]
    assert report.banner("synthetic", ASOF, ASOF) == [report.MOCK_BANNER]
    m = report.banner("massive", ASOF, ASOF)[0]
    assert m.startswith("> **DELAYED / END-OF-DAY DATA (Massive free tier).** Not live quotes.")
    assert f"as of {ASOF}" in m and "OLDER" not in m
    old = report.banner("massive", ASOF - timedelta(days=3), ASOF)[0]
    assert "OLDER than the requested close" in old
    assert "OLDER" in report.banner("massive", None, ASOF)[0]
    assert report.banner("csv", ASOF, ASOF) == []


# ---------------------------------------------------------------- section 3 fixes

def bars_from(day, prices_and_lows):
    out = []
    for i, (c, lo, hi) in enumerate(prices_and_lows):
        ts = datetime.combine(day, time(9, 30), tzinfo=ET) + timedelta(minutes=i)
        out.append(fakes.Bar(ts=ts, open=c, high=hi, low=lo, close=c, volume=1000))
    return out


def test_proxy_stops_out_where_legacy_counts_a_win(cfg):
    # break up at 9:36, then a sharp drop (stop) BEFORE a later rally the legacy proxy would count
    path = [(100.0, 99.95, 100.05)] * 5 + [(100.2, 100.1, 100.25)]
    path += [(100.2, 98.5, 100.25)]                    # adverse low: the option loses > 15%
    path += [(100.2 + 0.05 * i, 100.1, 100.3 + 0.05 * i) for i in range(1, 50)]
    bars = bars_from(ASOF, path)
    r = signals.morning_option_move_proxy(bars, 0.3, cfg)
    assert r.exit_reason == "stop" and not r.hit_target and r.ret_pct == -cfg["plan"]["stop_pct"]
    assert signals.morning_option_move_proxy_legacy(bars, 0.3, cfg) >= 5          # the old optimism


def test_proxy_time_stop_and_decay(cfg):
    path = [(100.0, 99.95, 100.05)] * 5 + [(100.1, 100.05, 100.12)] + [(100.1, 100.08, 100.12)] * 120
    r = signals.morning_option_move_proxy(bars_from(ASOF, path), 0.3, cfg)
    assert r.exit_reason == "time_stop" and r.exit_ts.astimezone(ET).time() == time(10, 30)
    assert r.ret_pct < 0                               # flat underlying: time decay loses money


def test_proxy_records_stretch(cfg):
    path = [(100.0, 99.95, 100.05)] * 5 + [(100.1 + 0.06 * i, 100.05 + 0.06 * i, 100.12 + 0.06 * i) for i in range(80)]
    r = signals.morning_option_move_proxy(bars_from(ASOF, path), 0.3, cfg)
    assert r.exit_reason == "target" and r.hit_target and r.hit_stretch and r.ret_pct == cfg["plan"]["target_pct"]


def test_gaps_are_detected_and_warned(cfg, caplog):
    bars = fakes.minute_bars(ASOF, lambda i: 100.0 if i < 5 else 100.0 + i * 0.02)
    del bars[20:25]
    assert signals.bar_gaps(bars) == [(bars[20].ts, 5)]
    with caplog.at_level("WARNING"):
        r = signals.morning_option_move_proxy(bars, 0.3, cfg)
    assert r.gaps and "gap" in caplog.text


def test_opening_range_of_30_minutes_or_more_does_not_crash(cfg):
    from options_screener import config as config_mod
    from options_screener import plan
    bars = fakes.minute_bars(ASOF, lambda i: 100.0 + (i % 7) * 0.01)
    assert signals.opening_range(bars, 45) is not None
    assert signals.after_open(ASOF, 45).time() == time(10, 15)
    c = config_mod.merge(cfg, {"plan": {"entry_after_minutes": 35, "entry_deadline": "10:20"}})
    assert signals.morning_option_move_proxy(bars, 0.3, c) is not None
    cand = SimpleNamespace(snapshot=fakes.snapshot("ABC", EXPIRY, 100.0), fill=None, direction="bull", sizing=None)
    assert plan.build(cand, c)["entry_trigger"].startswith("after 10:05 ET")


def test_iv_prev_zero_is_a_value_not_missing():
    st = OptionStats(iv=0.30, iv_prev=0.0, iv_history=[0.2 + 0.002 * i for i in range(100)])
    _, _, change = signals.iv_metrics(st)
    assert change == pytest.approx(0.30)
    assert signals.unusual_volume_score(OptionStats(option_volume=0.0, avg_option_volume_20d=100.0)) == 0.0


def test_earnings_timing_only_from_the_source(cfg):
    _, label, _ = signals.catalyst_score("X", ASOF, TARGET, [ASOF], None, cfg)
    assert label.endswith("(time unverified)")
    _, label, _ = signals.catalyst_score("X", ASOF, TARGET, [(TARGET, "bmo")], None, cfg)
    assert label.endswith("(BMO)")
    _, label, _ = signals.catalyst_score("X", ASOF, TARGET, [(ASOF, "during market")], None, cfg)
    assert label.endswith("(time unverified)")


def test_unverified_earnings_time_adds_iv_crush_warning(world, cfg):
    v, cats, _ = world
    res = screen_day(AsOfView(v, ASOF), ASOF, TARGET, cfg, cats, NullNews())
    c = res.candidates[0]
    assert not c.earnings_time_verified and any("time UNVERIFIED" in n for n in c.notes)
    assert any("IV-crush" in n for n in c.notes)


# ---------------------------------------------------------------- Massive free tier (recorded fixtures)

class RoutedHTTP:
    """Serves recorded responses by path. Records every call. Never touches the network."""

    def __init__(self, routes, status=200):
        self.routes, self.status, self.calls = routes, status, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        for frag, fname in self.routes.items():
            if frag in url:
                body = json.loads((FIX / fname).read_text())
                return SimpleNamespace(status_code=self.status, json=lambda body=body: body)
        return SimpleNamespace(status_code=200, json=lambda: {"results": []})


ROUTES = {"/v2/aggs/ticker/F/range/1/day/": "stocks_daily_F.json",
          "/v2/aggs/ticker/F/range/1/minute/": "stocks_minute_F.json",
          "/v3/reference/options/contracts": "options_contracts_F.json",
          "/v2/aggs/ticker/O:F261023C00012000/range/1/minute/": "options_minute_F261023C12.json"}
D0 = date(2026, 10, 19)


def massive(tmp_path, cfg, http=None, today=date(2026, 10, 21)):
    http = http or RoutedHTTP(ROUTES)
    client = MassiveClient(api_key=FAKE_KEY, cache_dir=tmp_path, session=http, rpm=10_000, sleep=lambda s: None, today=today)
    return MassiveView(D0, cfg, client), http


def test_massive_view_parses_bars_and_tracks_asof(tmp_path, cfg100):
    v, http = massive(tmp_path, cfg100)
    daily = v.daily_bars("F", D0, 80)
    assert len(daily) == 60 and daily[-1].ts.date() == D0 and v.latest_bar_date == D0
    mins = v.intraday_bars("F", D0)
    assert len(mins) == 3 and mins[0].et_time == time(9, 30)          # pre-market bar dropped
    assert v.option_stats("F", D0) is None                              # n/a on the free tier
    url, params, headers = http.calls[0]
    assert headers["Authorization"] == f"Bearer {FAKE_KEY}" and FAKE_KEY not in url and FAKE_KEY not in json.dumps(params)


def test_massive_chain_derives_iv_estimates_ask_and_checks_multiplier(tmp_path, cfg100):
    v, _ = massive(tmp_path, cfg100)
    chain = v.chain("F", D0, date(2026, 10, 20))
    priced = [s for s in chain if s.ask is not None]
    assert len(priced) == 1
    s = priced[0]
    assert s.contract == Contract("F", date(2026, 10, 23), 12.0, "C")
    assert s.bid is None and s.open_interest is None and s.ask_estimated and s.iv_source == "derived"
    assert s.last == pytest.approx(0.31) and s.ask == pytest.approx(round(0.31 + max(0.005, 0.31 * 0.015), 2))
    assert 0.0 < s.iv < 2.0 and 0.3 < s.delta < 0.8
    assert any(x.multiplier == 50 for x in chain) and all(x.ask is None for x in chain if x.multiplier != 100)
    from collections import Counter
    from options_screener import fill_quality
    rej = Counter()
    pool = fill_quality.eligible(chain, "C", date(2026, 10, 20), cfg100, rej)
    assert rej["non-standard multiplier (not 100)"] == 1 and all(p.multiplier == 100 for p in pool)
    assert any("n/a (free tier)" in d for d in v.degraded) and any("DEGRADED" in d for d in v.degraded)


def test_massive_cache_only_for_past_data(tmp_path, cfg100):
    v, http = massive(tmp_path, cfg100, today=date(2026, 10, 21))
    v.daily_bars("F", D0, 10)
    v2, http2 = massive(tmp_path, cfg100, today=date(2026, 10, 21))
    v2.daily_bars("F", D0, 10)
    assert len(http2.calls) == 0 and v2.client.cache_hits == 1
    fresh = tmp_path / "fresh"
    v3, _ = massive(fresh, cfg100, today=D0)                           # as-of today: not final, not cached
    v3.daily_bars("F", D0, 10)
    assert not any(fresh.rglob("*.json"))


def test_massive_rate_limiter_per_bucket():
    from options_screener.ratelimit import SlidingWindowLimiter
    now = [0.0]
    slept = []
    lim = SlidingWindowLimiter(5, 60.0, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    for _ in range(5):
        assert lim.acquire() == 0.0
    assert lim.acquire() == pytest.approx(60.0) and slept == [pytest.approx(60.0)]
    c = MassiveClient(api_key=FAKE_KEY, session=RoutedHTTP({}), sleep=lambda s: None)
    assert set(c.limiters) == {"stocks", "options", "reference"} and c.limiters["stocks"] is not c.limiters["options"]


def test_massive_429_retries_once_then_errors_without_key(tmp_path, cfg100):
    waits = []
    http = RoutedHTTP(ROUTES, status=429)
    client = MassiveClient(api_key=FAKE_KEY, cache_dir=tmp_path, session=http, rpm=10_000, sleep=waits.append)
    with pytest.raises(ProviderUnavailable) as e:
        MassiveView(D0, cfg100, client).daily_bars("F", D0, 10)
    assert len(http.calls) == 2 and waits == [60.0] and FAKE_KEY not in str(e.value)


def test_massive_requires_key_for_the_view(monkeypatch, cfg100):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable):
        MassiveView(D0, cfg100)


def test_massive_screen_end_to_end_is_degraded_not_faked(tmp_path, cfg100):
    v, _ = massive(tmp_path, cfg100)
    res = screen_day(AsOfView(v, D0), D0, date(2026, 10, 20), cfg100, fakes.FakeCatalysts({"F": [D0]}), NullNews(), ["F"])
    assert res.data_asof == D0
    assert any("n/a (free tier)" in m for m in res.missing)
    md = report.render_screen(res, cfg100, source=v.name, catalysts="FAKE", news="none",
                              run_time=datetime(2026, 10, 19, 20, 0, tzinfo=TORONTO), provider="massive")
    assert "DELAYED / END-OF-DAY DATA (Massive free tier)" in md and "MOCK DATA" not in md


# ---------------------------------------------------------------- no broker anywhere

def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)


BLOCK_IB = """
import sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in ('ib_async', 'ib_insync', 'ibapi'):
            raise ImportError('blocked for test: ' + name)
sys.meta_path.insert(0, Block())
"""


def test_screen_imports_and_runs_without_ib_async(tmp_path):
    code = BLOCK_IB + f"""
from datetime import date, datetime
from options_screener import config, report, screen, backtest, status
from options_screener.providers.base import AsOfView
from options_screener.models import TORONTO
cfg = config.load()
asof, target = date(2026, 10, 16), date(2026, 10, 19)
view, cats, news, syms = screen.build_provider('mock', cfg, asof, ['SPY', 'F', 'SOFI'])
res = screen.screen_day(AsOfView(view, asof), asof, target, cfg, cats, news, syms)
md, _ = report.write_screen(res, cfg, source=view.name, catalysts=cats.name, news=news.name,
                            run_time=datetime.now(TORONTO), provider='mock', out_dir=__import__('pathlib').Path({str(tmp_path)!r}))
view, cats, news, syms = screen.build_provider('synthetic', cfg, asof, ['SPY', 'F'])
screen.screen_day(AsOfView(view, asof), asof, target, cfg, cats, news, syms)
print('OK', md.name)
"""
    r = _run(code)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "OK morning_screen_2026-10-19.md" in r.stdout


BROKERISH = ("ib_async", "ib_insync", "ibapi", "options_screener.providers.ibkr", "options_screener.paper",
             "snaptrade_client", "alpaca", "questrade", "wealthsimple")


def test_screen_path_imports_no_broker_or_order_module():
    code = f"""
import sys
from datetime import date
from options_screener import config, screen, report, backtest, status
from options_screener.providers.base import AsOfView
from options_screener.providers import massive, mock, historical, catalysts
cfg = config.load()
asof = date(2026, 10, 16)
view, cats, news, syms = screen.build_provider('mock', cfg, asof, ['SPY'])
screen.screen_day(AsOfView(view, asof), asof, date(2026, 10, 19), cfg, cats, news, syms)
bad = [m for m in sys.modules if m.startswith({BROKERISH!r})]
print('BAD', bad)
"""
    r = _run(code)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "BAD []" in r.stdout
