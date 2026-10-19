"""Providers degrade gracefully; reports render; status works without any config."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from options_screener import config as config_mod
from options_screener import report, status
from options_screener.models import TORONTO, Contract
from options_screener.providers import catalysts
from options_screener.providers.base import AsOfView, NullCatalysts, NullNews, ProviderUnavailable
from options_screener.providers.historical import HistoricalView
from options_screener.providers.massive import MassiveOptions, ThetaDataOptions

FAKE_KEY = "k" * 8 + "-test"
K = Contract("SPY", date(2026, 10, 23), 580.0, "C")


def test_massive_requires_key(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable):
        MassiveOptions()


class FakeHTTP:
    def __init__(self, status=200, body=None):
        self.status, self.body, self.calls = status, body or {}, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return SimpleNamespace(status_code=self.status, json=lambda: self.body)


def test_massive_bars_parse_and_auth_header(tmp_path):
    t = int(datetime(2026, 10, 16, 9, 31, tzinfo=TORONTO).timestamp() * 1000)
    pre = int(datetime(2026, 10, 16, 8, 0, tzinfo=TORONTO).timestamp() * 1000)
    http = FakeHTTP(body={"results": [{"t": pre, "o": 1, "h": 1, "l": 1, "c": 1, "v": 5, "n": 2},
                                      {"t": t, "o": 2.0, "h": 2.1, "l": 1.9, "c": 2.05, "v": 40, "n": 7}]})
    m = MassiveOptions(api_key=FAKE_KEY, has_quotes=False, rpm=10_000, cache_dir=tmp_path, session=http)
    bars = m.option_bars(K, date(2026, 10, 16))
    assert len(bars) == 1 and bars[0].trades == 7 and bars[0].bid is None       # pre-market dropped
    url, params, headers = http.calls[0]
    assert "/v2/aggs/ticker/O:SPY261023C00580000/range/1/minute/2026-10-16/2026-10-16" in url
    assert headers["Authorization"] == f"Bearer {FAKE_KEY}" and FAKE_KEY not in url


def test_massive_errors_never_leak_key(tmp_path):
    m = MassiveOptions(api_key=FAKE_KEY, rpm=10_000, cache_dir=tmp_path, session=FakeHTTP(status=403))
    with pytest.raises(ProviderUnavailable) as e:
        m.option_bars(K, date(2026, 10, 16))
    assert FAKE_KEY not in str(e.value)


def test_thetadata_is_not_guessed():
    with pytest.raises(ProviderUnavailable, match="not implemented"):
        ThetaDataOptions()


def test_alpha_vantage_parses_csv(tmp_path):
    csv_text = "symbol,name,reportDate,fiscalDateEnding,estimate,currency\nNVDA,NVIDIA,2026-11-19,2026-10-31,0.9,USD\n"
    http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=200, text=csv_text))
    av = catalysts.AlphaVantageEarnings(api_key=FAKE_KEY, cache_dir=tmp_path, http=http)
    assert av.earnings_dates("NVDA", date(2026, 11, 1), date(2026, 11, 30)) == [date(2026, 11, 19)]


def test_alpha_vantage_bad_body_degrades(tmp_path):
    http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=200, text='{"Note": "rate limit"}'))
    av = catalysts.AlphaVantageEarnings(api_key=FAKE_KEY, cache_dir=tmp_path, http=http)
    with pytest.raises(ProviderUnavailable):
        av.earnings_dates("NVDA", date(2026, 11, 1), date(2026, 11, 30))


def test_from_env_falls_back_to_none(monkeypatch, tmp_path):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.setattr(catalysts, "DATA", tmp_path)
    assert isinstance(catalysts.from_env(), NullCatalysts)


class Und:
    name = "fake underlying"

    def __init__(self, world):
        self.w = world

    def daily_bars(self, s, e, n):
        return self.w.daily_bars(s, e, n)

    def intraday_bars(self, s, d):
        return self.w.intraday_bars(s, d)


def test_historical_view_without_options_is_proxy(world, cfg):
    v, _, sessions = world
    hv = HistoricalView(Und(v), None, cfg)
    assert hv.proxy and not hv.has_quotes and "PROXY" in hv.name and hv.option_stats("ABC", sessions[-1]) is None
    chain = hv.chain("ABC", sessions[-1], sessions[-1])
    assert chain and all(s.synthetic for s in chain)
    bars = hv.option_bars(chain[0].contract, sessions[-2])
    assert bars and all(b.bid is None for b in bars)


def test_mock_screen_report_renders(tmp_path):
    from options_screener.providers.mock import MockWorld
    from options_screener.screen import screen_day
    cfg = config_mod.load()
    asof, target = date(2026, 10, 16), date(2026, 10, 19)
    w = MockWorld(["SPY", "NVDA", "TSLA", "XOM"], end=asof)
    res = screen_day(AsOfView(w, asof), asof, target, cfg, w, NullNews(), w.symbols)
    md, js = report.write_screen(res, cfg, source="MOCK", catalysts="MOCK", news="none",
                                 run_time=datetime(2026, 10, 16, 20, 0, tzinfo=TORONTO), mock=True, out_dir=tmp_path)
    text = md.read_text()
    for s in ("Research only", "MOCK DATA", "America/Toronto", "Near-misses", "Screen funnel", "fill quality"):
        assert s in text
    assert js.exists()


def test_status_defaults_to_research(monkeypatch):
    for k in ("IBKR_PORT", "HISTORICAL_OPTIONS_PROVIDER", "ALPHAVANTAGE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    s = status.gather(config_mod.load())
    assert s["mode"] == "RESEARCH" and "(paper port)" in s["ibkr"]


def test_csv_providers_round_trip(tmp_path):
    from options_screener.providers.csv_provider import CSVEarnings, CSVOptions, CSVUnderlying
    (tmp_path / "underlying").mkdir()
    (tmp_path / "options").mkdir()
    (tmp_path / "underlying" / "SPY_1d.csv").write_text("date,open,high,low,close,volume\n2026-10-15,1,2,0.5,1.5,100\n2026-10-16,1.5,2,1,1.8,200\n")
    (tmp_path / "underlying" / "SPY_1m.csv").write_text(
        "ts,open,high,low,close,volume\n2026-10-16T09:29:00-04:00,1,1,1,1,1\n2026-10-16T09:30:00-04:00,1,1.1,0.9,1.05,10\n")
    (tmp_path / "options" / f"{K.occ}.csv").write_text(
        "ts,open,high,low,close,volume,trades,bid,ask\n2026-10-16T09:31:00-04:00,2,2.1,1.9,2.05,40,7,2.0,2.1\n")
    u = CSVUnderlying(tmp_path)
    assert [b.close for b in u.daily_bars("SPY", date(2026, 10, 16), 5)] == [1.5, 1.8]
    assert len(u.intraday_bars("SPY", date(2026, 10, 16))) == 1                 # pre-market dropped
    o = CSVOptions(tmp_path)
    assert o.has_quotes and o.has_trade_counts
    b = o.option_bars(K, date(2026, 10, 16))[0]
    assert (b.trades, b.bid, b.ask) == (7, 2.0, 2.1)
    (tmp_path / "earnings.csv").write_text("symbol,date\nspy,2026-10-20\n")
    assert CSVEarnings(tmp_path / "earnings.csv").earnings_dates("SPY", date(2026, 10, 1), date(2026, 10, 31)) == [date(2026, 10, 20)]
