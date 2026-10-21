import math

import pytest

from options_coach import black_scholes as bs
from options_coach.cli import main
from options_coach.strategy import Position, parse_leg


def test_textbook_call_and_put_parity():
    # Hull: S=K=100, T=1, r=5%, sigma=20% -> call 10.4506
    c = bs.price("C", 100, 100, 1, 0.05, 0.20)
    p = bs.price("P", 100, 100, 1, 0.05, 0.20)
    assert c == pytest.approx(10.4506, abs=1e-4)
    assert c - p == pytest.approx(100 - 100 * math.exp(-0.05), abs=1e-9)


def test_greeks_match_finite_differences():
    args = dict(K=105, T=0.25, r=0.04, sigma=0.3, q=0.01)
    g = bs.greeks("P", 100, **args)
    h = 0.01
    up, dn = bs.price("P", 100 + h, **args), bs.price("P", 100 - h, **args)
    assert g.delta == pytest.approx((up - dn) / (2 * h), abs=1e-4)
    assert g.gamma == pytest.approx((up - 2 * g.price + dn) / h ** 2, abs=1e-3)
    vol_up = bs.price("P", 100, 105, 0.25, 0.04, 0.31, 0.01)
    assert g.vega == pytest.approx(vol_up - g.price, abs=2e-3)


def test_implied_vol_round_trip_and_bad_quote():
    px = bs.price("P", 50, 45, 30 / 365, 0.04, 0.55)
    assert bs.implied_vol("P", px, 50, 45, 30 / 365, 0.04) == pytest.approx(0.55, abs=1e-5)
    with pytest.raises(ValueError):
        bs.implied_vol("C", 0.5, 100, 90, 0.1, 0.04)  # below intrinsic


def test_parse_leg_formats():
    leg = parse_leg("-2P140@1.10~45")
    assert (leg.qty, leg.kind, leg.strike, leg.premium, leg.iv) == (-2, "P", 140, 1.10, 0.45)
    assert parse_leg("+100S@148.5").premium == 148.5
    for bad in ["1X150", "+1C", "+100S", "0C150@1"]:
        with pytest.raises(ValueError):
            parse_leg(bad)


def test_bull_call_spread_profile():
    pos = Position([parse_leg("+1C150@4.10"), parse_leg("-1C160@1.30")], S=150, dte=30)
    assert pos.cost == pytest.approx(280)
    assert pos.max_profit_loss() == (pytest.approx(720), pytest.approx(-280))
    assert pos.breakevens() == [152.8]
    assert 0.3 < pos.prob_of_profit() < 0.5


def test_iron_condor_and_naked_call():
    legs = [parse_leg(x) for x in ["-1P140@2.10", "+1P135@1.20", "-1C160@1.90", "+1C165@0.95"]]
    pos = Position(legs, S=150, dte=45)
    assert pos.max_profit_loss() == (pytest.approx(185), pytest.approx(-315))
    assert pos.breakevens() == [138.15, 161.85]
    naked = Position([parse_leg("-1C155@3")], S=150, dte=30)
    assert naked.max_profit_loss()[1] is None


def test_covered_call_and_expired_position():
    pos = Position([parse_leg("+100S@100"), parse_leg("-1C105@2")], S=100, dte=0, iv=0.3)
    assert pos.max_profit_loss() == (pytest.approx(700), pytest.approx(-9800))
    assert pos.prob_of_profit() == 1.0  # at expiry the spot is known: 100 > breakeven 98


def test_cli_strategy_with_negative_first_leg(capsys):
    assert main(["strategy", "--spot", "150", "--dte", "30", "-1C155@3", "--account", "5000"]) == 0
    out = capsys.readouterr().out
    assert "UNDEFINED RISK" in out and "Max loss:    UNLIMITED" in out


def test_cli_size_and_errors(capsys):
    assert main(["size", "--account", "5000", "--risk-per-contract", "120", "--max-risk-pct", "5"]) == 0
    assert "size: 2 contract(s)" in capsys.readouterr().out
    assert main(["strategy", "--spot", "150", "--dte", "30", "+1C150"]) == 2
