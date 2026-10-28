import math

import numpy as np
import pytest

import prob_engine as pe

# Hull, Options Futures and Other Derivatives: S=100, K=100, T=1, r=5%, sigma=20%, no dividend.
S, K, T, R, SIG = 100.0, 100.0, 1.0, 0.05, 0.20


def test_textbook_call_and_put():
    assert pe.bs_price(S, K, T, R, SIG, "call") == pytest.approx(10.4506, abs=1e-4)
    assert pe.bs_price(S, K, T, R, SIG, "put") == pytest.approx(5.5735, abs=1e-4)


def test_textbook_greeks():
    g = pe.bs_greeks(S, K, T, R, SIG, "call")
    assert g.delta == pytest.approx(0.6368, abs=1e-4)
    assert g.gamma == pytest.approx(0.018762, abs=1e-6)
    assert g.vega == pytest.approx(0.37524, abs=1e-5)          # per vol point
    assert g.theta * 365 == pytest.approx(-6.4140, abs=1e-3)   # per year
    assert g.rho == pytest.approx(0.53232, abs=1e-5)           # per rate point
    p = pe.bs_greeks(S, K, T, R, SIG, "put")
    assert p.delta == pytest.approx(g.delta - 1, abs=1e-12)
    assert p.gamma == pytest.approx(g.gamma)


def test_hull_dividend_example():
    # Hull Example 17.1: index option S=930, K=900, r=8%, q=3%, sigma=20%, T=2 months -> call 51.83
    assert pe.bs_price(930, 900, 2 / 12, 0.08, 0.20, "call", q=0.03) == pytest.approx(51.83, abs=0.01)


@pytest.mark.parametrize("s,k,t,r,sig,q", [(100, 100, 1, 0.05, 0.2, 0), (120, 100, 0.25, 0.03, 0.45, 0.01),
                                           (50, 70, 2, 0.01, 0.6, 0.02), (300, 280, 30 / 365, 0.045, 0.35, 0)])
def test_put_call_parity(s, k, t, r, sig, q):
    c = pe.bs_price(s, k, t, r, sig, "call", q)
    p = pe.bs_price(s, k, t, r, sig, "put", q)
    assert c - p == pytest.approx(s * math.exp(-q * t) - k * math.exp(-r * t), abs=1e-9)


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("sig", [0.08, 0.25, 0.6, 1.5])
@pytest.mark.parametrize("k", [70, 100, 140])
def test_iv_round_trip(kind, sig, k):
    price = pe.bs_price(100, k, 0.3, 0.04, sig, kind)
    if pe.bs_greeks(100, k, 0.3, 0.04, sig, kind).vega < 1e-4:
        pytest.skip("deep in or out of the money: no vega, so IV is not identifiable from price")
    assert pe.implied_vol(price, 100, k, 0.3, 0.04, kind) == pytest.approx(sig, abs=1e-5)


def test_iv_rejects_impossible_price():
    assert pe.implied_vol(1.0, 100, 50, 0.5, 0.0, "call") is None  # below intrinsic
    assert pe.implied_vol(150.0, 100, 50, 0.5, 0.0, "call") is None  # above spot


def test_vectorised_matches_scalar():
    xs = np.array([80.0, 100.0, 120.0])
    v = pe.bs_price(xs, 100, 0.5, 0.03, 0.3, "call")
    for x, y in zip(xs, v):
        assert y == pytest.approx(pe.bs_price(float(x), 100, 0.5, 0.03, 0.3, "call"), abs=1e-5)


def test_expected_move_and_probabilities():
    assert pe.expected_move(100, 0.365, 365) == pytest.approx(36.5)
    assert pe.expected_move(200, 0.30, 30) == pytest.approx(200 * 0.30 * math.sqrt(30 / 365))
    up = pe.prob_above(110, 100, 0.3, 45, 0.04)
    assert up + pe.prob_below(110, 100, 0.3, 45, 0.04) == pytest.approx(1)
    assert pe.prob_touch(110, 100, 0.3, 45, 0.04) == pytest.approx(min(1, 2 * up))
    # risk-neutral P(S_T > K) equals N(d2)
    d2 = (math.log(S / K) + (R - SIG ** 2 / 2) * T) / (SIG * math.sqrt(T))
    assert pe.prob_above(K, S, SIG, 365, R) == pytest.approx(pe.norm_cdf(d2))


def test_hist_vol_and_rank():
    rng = np.random.default_rng(1)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    hv = pe.hist_vol(closes, 250)
    assert hv == pytest.approx(0.02 * math.sqrt(252), rel=0.15)
    assert pe.hist_vol([1, 2], 20) is None
    hist = list(np.linspace(0.2, 0.6, 101))
    assert pe.iv_rank(0.4, hist) == pytest.approx(50)
    assert pe.iv_percentile(0.4, hist) == pytest.approx(50, abs=1)


def test_liquidity_grades():
    assert pe.liquidity_grade(2.00, 2.06, 5000, 2000)["grade"] == "A"
    assert pe.liquidity_grade(2.00, 2.16, 5000, 2000)["grade"] == "B"
    assert pe.liquidity_grade(2.00, 2.06, 100, 2000)["grade"] == "C"
    assert pe.liquidity_grade(2.00, 3.00, 5000, 2000)["grade"] == "F"
    assert pe.liquidity_grade(0, 0.10, 5000, 2000)["grade"] == "F"
    assert pe.worst_grade(["A", "C", "B"]) == "C"


def _bull_call(r=0.04, iv=0.3, dte=30):
    long_px = pe.bs_price(100, 100, dte / 365, r, iv, "call")
    short_px = pe.bs_price(100, 110, dte / 365, r, iv, "call")
    return pe.Position([pe.Leg("call", 1, 100, dte, long_px, iv), pe.Leg("call", -1, 110, dte, short_px, iv)])


def test_vertical_shape_and_fair_ev():
    pos = _bull_call()
    debit = pos.entry()
    a = pe.analyze_expiry(pos, 100, 0.3, 0.04)
    assert a["max_profit"] == pytest.approx((10 - debit) * 100, abs=0.5)
    assert a["max_loss"] == pytest.approx(-debit * 100, abs=0.5)
    assert a["breakevens"] == [pytest.approx(100 + debit, abs=0.01)]
    # priced at fair value with no costs, risk-neutral EV is about zero (forward value of zero)
    assert abs(a["ev"]) < 1.0
    # POP equals P(S_T > breakeven)
    assert a["pop"] == pytest.approx(pe.prob_above(100 + debit, 100, 0.3, 30, 0.04), abs=0.003)


def test_costs_reduce_ev_and_slippage_uses_half_of_half_spread():
    leg = pe.Leg("call", 1, 100, 30, None, 0.3, bid=2.00, ask=2.20)
    assert leg.fill() == pytest.approx(2.15)
    assert pe.Leg("call", -1, 100, 30, None, 0.3, bid=2.00, ask=2.20).fill() == pytest.approx(2.05)
    free = _bull_call()
    paid = _bull_call()
    paid.commission_per_contract, paid.fx_fee_pct = 0.75, 0.015
    c = paid.costs()
    assert c["commissions"] == pytest.approx(0.75 * 2 * 2)
    assert c["fx"] == pytest.approx(0.015 * paid.entry() * 100 * 2)
    assert pe.expected_value(paid, 100, 0.3, 0.04) == pytest.approx(pe.expected_value(free, 100, 0.3, 0.04) - c["total"], abs=1e-6)


def test_iron_condor_and_credit_sign():
    r, iv, d = 0.04, 0.3, 30
    px = lambda k, kind: pe.bs_price(100, k, d / 365, r, iv, kind)  # noqa: E731
    ic = pe.Position([pe.Leg("put", 1, 85, d, px(85, "put"), iv), pe.Leg("put", -1, 90, d, px(90, "put"), iv),
                      pe.Leg("call", -1, 110, d, px(110, "call"), iv), pe.Leg("call", 1, 115, d, px(115, "call"), iv)])
    credit = -ic.entry()
    assert credit > 0
    a = pe.analyze_expiry(ic, 100, iv, r)
    assert a["max_profit"] == pytest.approx(credit * 100, abs=0.5)
    assert a["max_loss"] == pytest.approx(-(5 - credit) * 100, abs=0.5)
    assert len(a["breakevens"]) == 2
    assert a["pop"] > 0.5


def test_covered_call_and_naked_flags():
    cc = pe.Position([pe.Leg("stock", 1, price=100.0), pe.Leg("call", -1, 105, 30, 2.0, 0.3)])
    a = pe.analyze_expiry(cc, 100, 0.3, 0.04)
    assert a["max_profit"] == pytest.approx(700, abs=1)
    assert a["max_loss"] < -9000
    naked = pe.Position([pe.Leg("call", -1, 105, 30, 2.0, 0.3)])
    assert pe.analyze_expiry(naked, 100, 0.3, 0.04)["max_loss"] == float("-inf")
    long_call = pe.Position([pe.Leg("call", 1, 105, 30, 2.0, 0.3)])
    assert pe.analyze_expiry(long_call, 100, 0.3, 0.04)["max_profit"] == float("inf")


def test_calendar_back_leg_priced_with_bs_and_mc_shocks():
    r = 0.04
    front = pe.Leg("call", -1, 100, 14, pe.bs_price(100, 100, 14 / 365, r, 0.40, "call"), 0.40)
    back = pe.Leg("call", 1, 100, 45, pe.bs_price(100, 100, 45 / 365, r, 0.32, "call"), 0.32)
    cal = pe.Position([front, back])
    assert cal.is_time_spread and cal.horizon == 14
    # at the front expiry, pinned at the strike, value = back call with 31 days left at back IV
    v = cal.value(np.array([100.0]), 14, r)[0]
    assert v == pytest.approx(pe.bs_price(100, 100, 31 / 365, r, 0.32, "call"), abs=1e-5)
    a = pe.analyze(cal, 100, None, 0.30, r, n_paths=20000)
    shocks = a["implied"]["iv_shock"]
    assert set(shocks) == {"-20%", "+20%"} and shocks["-20%"]["paths"] >= 20000
    assert shocks["+20%"]["ev"] > shocks["-20%"]["ev"]  # long vega
    assert a["max_loss"] == pytest.approx(-cal.entry() * 100, rel=0.05)
    assert 0 < a["implied"]["p_hit_50"] < 1


def test_mc_agrees_with_grid():
    pos = _bull_call()
    grid = pe.analyze_expiry(pos, 100, 0.3, 0.04)
    mc = pe.monte_carlo(pos, 100, 0.3, 0.04, n_paths=40000, path_check=False)
    assert mc["pop"] == pytest.approx(grid["pop"], abs=0.01)
    assert mc["ev"] == pytest.approx(grid["ev"], abs=8)


def test_two_models_and_edge_message():
    pos = _bull_call(iv=0.25)
    a = pe.analyze(pos, 100, 0.25, 0.45, 0.04, n_paths=5000)
    assert a["implied"]["pop"] != a["realized"]["pop"]
    assert "HV20 45.0%" in a["edge"]
    v = pe.verdict(a, "A", max_loss_limit=10_000)
    assert v["verdict"] in {"ENTER CANDIDATE", "MARGINAL", "THROW IT OUT"}
    assert pe.verdict(a, "F")["verdict"] == "THROW IT OUT"
    assert pe.verdict(a, "A", unplanned_event=True)["verdict"] == "THROW IT OUT"
    assert pe.verdict(a, "A", max_loss_limit=1)["verdict"] == "THROW IT OUT"


def test_edge_read_disagreement_wording():
    imp = {"ev": -40.0, "max_loss": -300.0}
    rea = {"ev": 40.0}
    assert "disagree" in pe.edge_read(imp, rea, 0.3, 0.45)
    assert "Both models show negative" in pe.edge_read({"ev": -40.0, "max_loss": -300.0}, {"ev": -40.0}, 0.3, 0.2)


def test_greek_attribution_regimes():
    pos = _bull_call()
    d = pe.dominant_greek(pos, 100, 0.3, 0.04)
    assert d["dominant"] in {"delta", "gamma", "vega", "theta", "rho"}
    t = d["terms"]
    assert t["total"] == pytest.approx(sum(v for k, v in t.items() if k != "total"))
    assert "event" in pe.dominant_greek(pos, 100, 0.3, 0.04, event_in_window=True)["regime"]
    assert "10 DTE" in pe.dominant_greek(_bull_call(dte=5), 100, 0.3, 0.04)["regime"]


def test_cli(tmp_path, capsys):
    import json
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"spot": 100, "iv": 0.3, "hv20": 0.35, "r": 0.04, "legs": [
        {"kind": "call", "qty": 1, "strike": 100, "dte": 30, "bid": 3.4, "ask": 3.6, "iv": 0.3, "oi": 3000, "volume": 900},
        {"kind": "call", "qty": -1, "strike": 110, "dte": 30, "bid": 0.9, "ask": 1.0, "iv": 0.3, "oi": 2000, "volume": 600}]}))
    assert pe.main([str(f)]) == 0
    out = capsys.readouterr().out
    assert "POP impl" in out and "model estimates" in out
