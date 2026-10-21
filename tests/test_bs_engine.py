from partner.bs_engine import bs, implied_vol, pnl_grid


def test_put_call_parity():
    S, K, T, r, sigma = 100, 105, 30 / 365, 0.045, 0.40
    c = bs(S, K, T, r, sigma)["price"]
    p = bs(S, K, T, r, sigma, kind="put")["price"]
    from math import exp
    assert abs((c - p) - (S - K * exp(-r * T))) < 1e-9


def test_implied_vol_round_trip():
    price = bs(250, 250, 14 / 365, 0.045, 0.55, kind="put")["price"]
    assert abs(implied_vol(price, 250, 250, 14 / 365, 0.045, kind="put") - 0.55) < 1e-6


def test_calendar_pnl_grid_flat_at_entry():
    legs = [dict(K=250, T=7 / 365, sigma=0.50, kind="call", qty=-1),
            dict(K=250, T=21 / 365, sigma=0.45, kind="call", qty=1)]
    grid = pnl_grid(legs, 250, 0.045)
    assert grid["+0%"] == 0
    # a calendar loses on big moves once time passes
    later = pnl_grid(legs, 250, 0.045, days_forward=7)
    assert later["+0%"] > later["+10%"] and later["+0%"] > later["-10%"]
