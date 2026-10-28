import sys
from datetime import date, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

import prob_engine as pe
import screener as sc

TODAY = date(2026, 10, 28)  # a Wednesday


def make_history(n=300, drift=0.001, vol=0.02, seed=3, start=100.0):
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol_ = rng.integers(8_000_000, 12_000_000, n).astype(float)
    idx = pd.bdate_range(end=pd.Timestamp(TODAY), periods=n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol_}, index=idx)


def make_chain(spot, expiries_iv, r=0.04, skew=0.10, oi=3000, vol=800, spread=0.03):
    """Synthetic chain priced with Black-Scholes, with a simple put skew. expiries_iv: {date: atm_iv}."""
    rows = []
    for exp, atm in expiries_iv.items():
        dte = (exp - TODAY).days
        for k in np.arange(round(spot * 0.6), round(spot * 1.4) + 1, 2.5):
            m = np.log(k / spot)
            iv = max(0.05, atm - skew * m)
            for kind in ("call", "put"):
                px = pe.bs_price(spot, k, dte / 365, r, iv, kind)
                half = max(0.01, px * spread / 2)
                rows.append({"expiry": exp, "dte": float(dte), "kind": kind, "strike": float(k), "bid": max(0.0, px - half),
                             "ask": px + half, "last": px, "volume": float(vol), "oi": float(oi), "iv": iv})
    return pd.DataFrame(rows)


def third_friday(y, m):
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


EXPS = [date(2026, 10, 30), date(2026, 11, 6), third_friday(2026, 11), third_friday(2026, 12), third_friday(2027, 1)]


def settings(**kw):
    base = dict(watchlist=["TEST"], commission=0.75, fx_fee_pct=0.015, n_paths=4000)
    base.update(kw)
    return sc.Settings(**base)


def test_is_monthly():
    assert sc.is_monthly(date(2026, 11, 20)) and sc.is_monthly(date(2026, 12, 18))
    assert not sc.is_monthly(date(2026, 11, 13)) and not sc.is_monthly(date(2026, 11, 27))
    assert sc.is_monthly(date(2027, 1, 15))


def test_technicals_basic_ranges():
    t = sc.technicals(make_history())
    assert 0 <= t["rsi"] <= 100 and t["atr_pct"] > 0 and t["rvol"] > 0
    assert t["lean"] in {"BULL", "BEAR", "NEUTRAL"} and t["sma200"] is not None
    assert t["hv20"] and t["hv60"]
    if t["support"] is not None:
        assert t["support"] < t["price"]
    if t["resistance"] is not None:
        assert t["resistance"] > t["price"]


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert sc.rsi(up).iloc[-1] > 99


def test_chain_stats_term_skew_em():
    spot = 100.0
    ivs = dict(zip(EXPS, [0.50, 0.45, 0.40, 0.33, 0.31]))
    ch = sc.clean_chain(make_chain(spot, ivs), spot, 0.04)
    st = sc.chain_stats(ch, spot)
    assert st["weekly"] == EXPS[0]
    assert st["monthly"] == third_friday(2026, 11)
    assert st["front"] == third_friday(2026, 11) and st["back"] == third_friday(2026, 12)
    assert st["term"] == "BACKWARDATION"
    assert st["skew25"] > 0  # puts richer
    assert st["front_iv"] == pytest.approx(0.40, abs=0.01)
    dte = st["monthly_dte"]
    assert st["monthly_em"] == pytest.approx(pe.expected_move(spot, st["front_iv"], dte), rel=1e-6)
    assert st["monthly_straddle"] / 0.7979 == pytest.approx(st["monthly_em"], rel=0.08)
    assert 0.33 < st["iv30"] < 0.40
    assert len(st["top_oi_calls"]) == 3 and st["pcr_oi"] == pytest.approx(1.0)
    assert st["atm_liquidity"] in "AB"


def test_structure_rules():
    tech = {"score": 4, "lean": "BULL", "hv20": 0.30}
    base = {"iv30": 0.30, "front_iv": 0.30, "back_iv": 0.30, "monthly_dte": 23}
    assert sc.choose_structure(tech, base, 20, None)[0] == "bull_call"
    assert sc.choose_structure({**tech, "score": -4, "lean": "BEAR"}, base, 20, None)[0] == "bear_put"
    assert sc.choose_structure({**tech, "score": 0, "lean": "NEUTRAL"}, base, 70, None)[0] == "iron_condor"
    assert sc.choose_structure({**tech, "score": 2}, base, 70, None)[0] == "bull_put"
    back = {**base, "front_iv": 0.45, "back_iv": 0.32}
    assert sc.choose_structure(tech, back, 50, None)[0] == "calendar"
    # earnings before the front expiry blocks the calendar
    assert sc.choose_structure(tech, back, 50, 5)[0] != "calendar"
    # without IV rank, IV/HV is the fallback
    assert "IV/HV" in sc.choose_structure({**tech, "score": 0, "lean": "NEUTRAL"}, {**base, "iv30": 0.45}, None, None)[1]
    assert sc.choose_structure({**tech, "score": 0, "lean": "NEUTRAL"}, base, 40, None)[0] == "none"


def test_iv_history(tmp_path):
    f = tmp_path / "d" / "iv.csv"
    for i in range(25):
        h = sc.update_iv_history(f, "TEST", TODAY - timedelta(days=25 - i), 0.30 + i * 0.01)
    h = sc.update_iv_history(f, "TEST", TODAY, 0.40)
    h = sc.update_iv_history(f, "TEST", TODAY, 0.41)  # same day overwrites
    assert len(h) == 26 and h[-1] == pytest.approx(0.41)
    sc.update_iv_history(f, "OTHER", TODAY, 0.2)
    assert len(sc.update_iv_history(f, "TEST", TODAY, 0.41)) == 26


@pytest.mark.parametrize("ivs,ivr,expect", [
    (dict(zip(EXPS, [0.50, 0.45, 0.42, 0.32, 0.31])), 50, "calendar"),
    (dict(zip(EXPS, [0.30, 0.30, 0.30, 0.31, 0.32])), 10, "debit"),
])
def test_evaluate_end_to_end(ivs, ivr, expect):
    hist = make_history(drift=0.003)
    spot = float(hist["Close"].iloc[-1])
    chain = make_chain(spot, ivs)
    iv_hist = list(np.linspace(0.2, 0.6, 100)) if ivr == 50 else list(np.linspace(0.29, 0.9, 100))
    extras = {"earnings": TODAY + timedelta(days=60), "ex_div": None, "short_pct_float": 0.02, "days_to_cover": 1.3,
              "yahoo_fundamentals": {"trailingPE": 30.0, "revenueGrowth": 0.12, "freeCashflow": 1e9, "marketCap": 5e10}}
    res = sc.evaluate("TEST", hist, chain, spot, extras, settings(max_risk=2000), TODAY, iv_hist)
    assert expect in res["idea"].name
    assert res["idea"].position is not None
    a = res["analysis"]
    assert 0 < a["implied"]["pop"] < 1 and 0 < a["realized"]["pop"] < 1
    assert res["verdict"]["verdict"] in {"ENTER CANDIDATE", "MARGINAL", "THROW IT OUT"}
    card = sc.format_card(res)
    for needle in ("TEST $", "RSI", "IV30", "Term", "Skew25", "EM ", "OI C", "OI P", "P/C", "Events", "Earn", "Fund RevG 12%", "PE 30",
                   "FCFy 2.0%", "IDEA:", "POP impl", "EV impl", ">> "):
        assert needle in card, needle
    assert "—" not in card  # no em dashes
    if expect == "calendar":
        assert "IV shock EV" in card
    assert max(len(line) for line in card.splitlines()) < 160


def test_earnings_inside_window_throws_it_out():
    hist = make_history(drift=0.003)
    spot = float(hist["Close"].iloc[-1])
    chain = make_chain(spot, dict(zip(EXPS, [0.30, 0.30, 0.30, 0.31, 0.32])))
    extras = {"earnings": TODAY + timedelta(days=10)}
    res = sc.evaluate("TEST", hist, chain, spot, extras, settings(), TODAY, [])
    assert res["verdict"]["verdict"] == "THROW IT OUT"
    assert any("earnings inside" in w for w in res["idea"].warnings)
    assert "IVR building 0/20d" in sc.format_card(res)


def test_illiquid_chain_is_auto_rejected():
    hist = make_history(drift=0.003)
    spot = float(hist["Close"].iloc[-1])
    chain = make_chain(spot, dict(zip(EXPS, [0.30, 0.30, 0.30, 0.31, 0.32])), oi=10, vol=0, spread=0.6)
    res = sc.evaluate("TEST", hist, chain, spot, {}, settings(), TODAY, [])
    assert res["liquidity"] == "F" and res["verdict"]["verdict"] == "THROW IT OUT"
    assert "AUTO REJECT" in sc.format_card(res)


def test_finnhub_extras_with_fake_http():
    calls = []

    def get(url, params, timeout):
        calls.append((url, params))
        assert params["token"] == "k"
        if url.endswith("/calendar/earnings"):
            body = {"earningsCalendar": [{"date": "2026-11-19", "symbol": "NVDA"}]}
        else:
            body = {"metric": {"peTTM": 40.1, "roeTTM": 90.0, "revenueGrowthTTMYoy": 80.0}}
        return SimpleNamespace(status_code=200, json=lambda: body)

    out = sc.finnhub_extras("NVDA", "k", TODAY, get=get)
    assert out["earnings"] == date(2026, 11, 19)
    assert out["fundamentals"]["pe"] == 40.1 and out["fundamentals"]["eps_growth"] is None
    bad = sc.finnhub_extras("NVDA", "k", TODAY, get=lambda *a, **k: SimpleNamespace(status_code=403))
    assert bad == {}


def test_telegram_noop_and_no_token_leak(caplog):
    assert sc.send_telegram("x", "", "") is False
    tok = "123:SECRET"

    def boom(url, **kw):
        raise ConnectionError(url)

    assert sc.send_telegram("x", tok, "1", post=boom) is False
    assert tok not in caplog.text


def test_moomoo_source_uses_documented_fields(monkeypatch):
    """Fake moomoo module returning DataFrames with the column names from moomoo-api 10.11.7108."""
    exp = third_friday(2026, 11)
    ctx = MagicMock()
    ctx.get_option_expiration_date.return_value = (0, pd.DataFrame({"strike_time": [exp.isoformat()],
                                                                    "option_expiry_date_distance": [23]}))
    ctx.get_option_chain.return_value = (0, pd.DataFrame({"code": ["US.X1", "US.X2"], "option_type": ["CALL", "PUT"],
                                                          "strike_time": [exp.isoformat()] * 2, "strike_price": [100.0, 100.0]}))

    def snap(codes):
        if codes == ["US.TEST"]:
            return 0, pd.DataFrame({"code": ["US.TEST"], "last_price": [101.5]})
        return 0, pd.DataFrame({"code": codes, "bid_price": [2.0, 1.9], "ask_price": [2.1, 2.0], "last_price": [2.05, 1.95],
                                "volume": [500, 400], "option_open_interest": [3000, 2500],
                                "option_implied_volatility": [32.5, 34.0], "option_delta": [0.5, -0.5]})

    ctx.get_market_snapshot.side_effect = snap
    fake = ModuleType("moomoo")
    fake.RET_OK = 0
    fake.OpenQuoteContext = MagicMock(return_value=ctx)
    monkeypatch.setitem(sys.modules, "moomoo", fake)
    monkeypatch.setattr(sc, "YahooSource", MagicMock())
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)
    src = sc.MoomooSource("127.0.0.1", 11111)
    ch = src.chain("TEST", TODAY)
    ctx.get_option_chain.assert_called_with("US.TEST", start=exp.isoformat(), end=exp.isoformat())
    assert list(ch["kind"]) == ["call", "put"]
    assert ch["iv"].tolist() == pytest.approx([0.325, 0.34])  # percent -> decimal
    assert ch["oi"].tolist() == [3000, 2500]
    assert src.spot("TEST", None) == 101.5
    # nothing order-related exists on the quote context we use
    assert not any("order" in c[0] for c in ctx.method_calls)


def test_settings_presets(monkeypatch):
    monkeypatch.setenv("ACCOUNT_PROFILE", "moomoo")
    monkeypatch.setenv("WATCHLIST", "nvda, tsla")
    monkeypatch.setenv("MAX_RISK_PER_TRADE", "300")
    s = sc.Settings.from_env()
    assert s.watchlist == ["NVDA", "TSLA"] and s.fx_fee_pct == 0.0 and s.max_risk == 300
    monkeypatch.setenv("FX_FEE_PCT", "0.02")
    assert sc.Settings.from_env().fx_fee_pct == 0.02
