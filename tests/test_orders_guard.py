"""The live gate. Dry-run must never reach a placing SDK method."""
import io

import pytest
from conftest import ACCOUNT_ID, FakeTTY, NotTTY, assert_nothing_placed, resp

from snaptrade_watch import orders
from snaptrade_watch.cli import run
from snaptrade_watch.orders import (
    LiveOrderUncertain,
    LiveTradingDisabled,
    OrderError,
    OrderRequest,
    PreviewExpired,
    cancel_order,
    place_live,
    preview_order,
    require_live_trading_allowed,
    validate_order,
)


def req(**kw):
    base = dict(account_id=ACCOUNT_ID, side="BUY", symbol="XEQT.TO", order_type="Limit", time_in_force="Day",
                units=1, price=30.0)
    base.update(kw)
    return OrderRequest(**base)


# ---------------------------------------------------------------- dry-run never places

def test_preview_calls_only_impact(session_factory):
    s = session_factory()
    p = preview_order(s, req())
    assert p.trade_id == "trade-abc-123" and p.source == "Brokerage preview"
    s.client.trading.get_order_impact.assert_called_once()
    _, kw = s.client.trading.get_order_impact.call_args
    assert kw["universal_symbol_id"] == "usym-xeqt" and kw["units"] == 1 and "notional_value" not in kw
    assert_nothing_placed(s.client)


def test_cli_preview_dry_run_never_places(session_factory):
    s = session_factory()
    out = io.StringIO()
    code = run(["preview", "--account", "7777", "--side", "BUY", "--symbol", "XEQT.TO", "--units", "1",
                "--type", "Limit", "--price", "30", "--tif", "Day"], session=s, out=out)
    assert code == 0 and "DRY-RUN PREVIEW" in out.getvalue() and "TSX" in out.getvalue()
    assert_nothing_placed(s.client)


@pytest.mark.parametrize("argv_extra", [[], ["--live"]])
def test_cli_place_refused_in_dry_run_before_any_call(session_factory, argv_extra):
    s = session_factory()                       # live_trading False
    out = io.StringIO()
    code = run(["place", "--account", "7777", "--side", "BUY", "--symbol", "XEQT.TO", "--units", "1",
                "--type", "Limit", "--price", "30", "--tif", "Day", *argv_extra], session=s, out=out)
    assert code == 3 and "REFUSED" in out.getvalue()
    assert_nothing_placed(s.client)
    s.client.trading.get_order_impact.assert_not_called()


def test_cli_cancel_refused_in_dry_run(session_factory):
    s = session_factory()
    code = run(["cancel", "--account", "7777", "--order", "BRK-777", "--live"], session=s, out=io.StringIO())
    assert code == 3
    assert_nothing_placed(s.client)


# ---------------------------------------------------------------- the three-part gate

def test_live_flag_without_env_fails(session_factory):
    s = session_factory(live_trading=False)
    with pytest.raises(LiveTradingDisabled, match="LIVE_TRADING"):
        place_live(s, req(), live_flag=True, stdin=FakeTTY("PLACE BUY 1 XEQT\n"))
    assert_nothing_placed(s.client)


def test_config_true_but_process_env_not_true_fails(session_factory, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING", "True")
    s = session_factory(live_trading=True)
    with pytest.raises(LiveTradingDisabled):
        place_live(s, req(), live_flag=True, stdin=FakeTTY("PLACE BUY 1 XEQT\n"))
    assert_nothing_placed(s.client)


def test_env_without_live_flag_fails(session_factory, live_env):
    s = session_factory(live_trading=True)
    with pytest.raises(LiveTradingDisabled, match="--live"):
        place_live(s, req(), live_flag=False, stdin=FakeTTY("PLACE BUY 1 XEQT\n"))
    assert_nothing_placed(s.client)


def test_non_tty_fails_even_with_correct_phrase(session_factory, live_env):
    s = session_factory(live_trading=True)
    with pytest.raises(LiveTradingDisabled, match="terminal"):
        place_live(s, req(), live_flag=True, stdin=NotTTY("PLACE BUY 1 XEQT\n"))
    assert_nothing_placed(s.client)


@pytest.mark.parametrize("typed", ["yes\n", "y\n", "PLACE BUY 1 XEQT.TO\n", "place buy 1 xeqt\n", "\n", "PLACE BUY 2 XEQT\n"])
def test_wrong_phrase_places_nothing(session_factory, live_env, typed):
    s = session_factory(live_trading=True)
    assert place_live(s, req(), live_flag=True, stdin=FakeTTY(typed), stdout=io.StringIO()) is None
    assert_nothing_placed(s.client)


def test_all_conditions_met_places_once_via_impact_trade_id(session_factory, live_env):
    s = session_factory(live_trading=True)
    out = io.StringIO()
    res = place_live(s, req(), live_flag=True, stdin=FakeTTY("PLACE BUY 1 XEQT\n"), stdout=out)
    assert res is not None
    s.client.trading.place_order.assert_called_once()
    _, kw = s.client.trading.place_order.call_args
    assert kw["trade_id"] == "trade-abc-123"
    s.client.trading.place_force_order.assert_not_called()
    s.client.account_information.get_user_account_recent_orders.assert_called()   # reconciled
    text = out.getvalue()
    assert "Brokerage preview" in text and "TSX" in text and "Day" in text and ACCOUNT_ID not in text


def test_place_failure_is_not_retried_and_reconciles(session_factory, live_env):
    s = session_factory(live_trading=True)
    s.client.trading.place_order.side_effect = TimeoutError("read timed out")
    with pytest.raises(LiveOrderUncertain, match="NOT retried"):
        place_live(s, req(), live_flag=True, stdin=FakeTTY("PLACE BUY 1 XEQT\n"), stdout=io.StringIO())
    assert s.client.trading.place_order.call_count == 1
    s.client.account_information.get_user_account_recent_orders.assert_called()


def test_expired_preview_gets_fresh_preview_and_new_confirmation(session_factory, live_env):
    s = session_factory(live_trading=True)
    t = {"now": 1000.0}

    def clock():
        return t["now"]

    class SlowTTY(FakeTTY):
        def readline(self):
            t["now"] += 400                 # Mike took longer than the 5-minute trade id lifetime
            return super().readline()

    with pytest.raises(PreviewExpired):
        place_live(s, req(), live_flag=True, stdin=SlowTTY("PLACE BUY 1 XEQT\n" * 3), stdout=io.StringIO(), clock=clock)
    assert s.client.trading.get_order_impact.call_count == 3
    assert_nothing_placed(s.client)


def test_submit_rechecks_guard(session_factory, monkeypatch, live_env):
    s = session_factory(live_trading=True)
    p = preview_order(s, req())
    monkeypatch.setenv("LIVE_TRADING", "false")     # flipped off between preview and submit
    with pytest.raises(LiveTradingDisabled):
        orders._submit_live_order(s, p, live_flag=True, stdin=FakeTTY(""))
    assert_nothing_placed(s.client)


def test_cancel_guarded_and_confirmed(session_factory, live_env):
    s = session_factory(live_trading=True)
    assert cancel_order(s, ACCOUNT_ID, "BRK-000777", live_flag=True, stdin=FakeTTY("nope\n"), stdout=io.StringIO()) is None
    s.client.trading.cancel_order.assert_not_called()
    cancel_order(s, ACCOUNT_ID, "BRK-000777", live_flag=True, stdin=FakeTTY("CANCEL 000777\n"), stdout=io.StringIO())
    s.client.trading.cancel_order.assert_called_once()


def test_require_guard_directly(cfg_factory, live_env):
    cfg = cfg_factory(live_trading=True)
    require_live_trading_allowed(cfg, True, FakeTTY(""))      # all three met: no exception
    with pytest.raises(LiveTradingDisabled):
        require_live_trading_allowed(cfg, True, NotTTY(""))


# ---------------------------------------------------------------- scope: no options, no crypto

@pytest.mark.parametrize("side", ["BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_CLOSE"])
def test_option_actions_rejected(side):
    with pytest.raises(OrderError, match="[Oo]ptions"):
        validate_order(req(side=side))


@pytest.mark.parametrize("sym", ["AAPL 261218C00200000", "AAPL261218P00150000", "SPY  261218C00500000"])
def test_option_symbols_rejected(sym):
    with pytest.raises(OrderError, match="option"):
        validate_order(req(symbol=sym))


def test_crypto_pair_rejected():
    with pytest.raises(OrderError, match="[Cc]rypto"):
        validate_order(req(symbol="BTC/CAD"))


def test_non_stock_security_type_rejected(session_factory):
    s = session_factory()
    s.client.reference_data.symbol_search_user_account.return_value = resp([
        {"id": "x", "symbol": "BTC", "raw_symbol": "BTC", "currency": {"code": "CAD"}, "type": {"code": "crypto"}}])
    with pytest.raises(OrderError, match="only stocks and ETFs"):
        preview_order(s, req(symbol="BTC"))
    s.client.trading.get_order_impact.assert_not_called()


# ---------------------------------------------------------------- Wealthsimple rules and the cap

@pytest.mark.parametrize("tif", ["FOK", "IOC", "fok"])
def test_no_fok_ioc(tif):
    with pytest.raises(OrderError, match="not supported"):
        validate_order(req(time_in_force=tif))


def test_notional_only_market_day():
    ok = validate_order(req(order_type="Market", price=None, units=None, notional=100))
    assert ok.notional == 100.0
    with pytest.raises(OrderError, match="Market"):
        validate_order(req(order_type="Limit", units=None, notional=100))
    with pytest.raises(OrderError, match="Market"):
        validate_order(req(order_type="Market", price=None, units=None, notional=100, time_in_force="GTC"))


@pytest.mark.parametrize("units", [0, -1, 1.5])
def test_whole_positive_shares_only(units):
    with pytest.raises(OrderError):
        validate_order(req(units=units))


def test_exactly_one_size():
    with pytest.raises(OrderError, match="exactly one"):
        validate_order(req(units=1, notional=50))


def test_price_and_stop_requirements():
    with pytest.raises(OrderError, match="price"):
        validate_order(req(price=None))
    with pytest.raises(OrderError, match="stop"):
        validate_order(req(order_type="StopLimit", stop=None))
    with pytest.raises(OrderError, match="not used"):
        validate_order(req(order_type="Market", price=30.0))
    assert validate_order(req(order_type="Stop", price=None, stop=28.0)).stop == 28.0


def test_cap_enforced_in_dry_run(session_factory):
    s = session_factory(max_order_value_cad=500)
    with pytest.raises(OrderError, match="MAX_ORDER_VALUE_CAD"):
        preview_order(s, req(units=20, price=30.0))        # 600 CAD
    s.client.trading.get_order_impact.assert_not_called()


def test_cap_rechecked_with_brokerage_price(session_factory):
    s = session_factory(max_order_value_cad=500)
    impact = {"trade": {"id": "t", "price": 60.0}, "trade_impacts": []}
    s.client.trading.get_order_impact.return_value = resp(impact)
    with pytest.raises(OrderError, match="MAX_ORDER_VALUE_CAD"):
        preview_order(s, req(units=10, price=30.0))        # 300 by limit, 600 by brokerage price


def test_usd_cap_uses_conservative_rate(session_factory):
    s = session_factory(max_order_value_cad=500, usd_cad_cap_rate=1.5)
    s.client.reference_data.symbol_search_user_account.return_value = resp([
        {"id": "u", "symbol": "SPY", "raw_symbol": "SPY", "currency": {"code": "USD"}, "type": {"code": "et"},
         "exchange": {"code": "ARCA"}}])
    with pytest.raises(OrderError, match="MAX_ORDER_VALUE_CAD"):
        preview_order(s, req(symbol="SPY", units=1, price=400.0))      # 400 USD -> 600 CAD


def test_market_units_uses_quote_for_cap(session_factory):
    s = session_factory()
    preview_order(s, req(order_type="Market", price=None))
    s.client.trading.get_user_account_quotes.assert_called_once()


def test_ambiguous_symbol_refused(session_factory):
    s = session_factory()
    s.client.reference_data.symbol_search_user_account.return_value = resp([
        {"id": "a", "symbol": "SHOP", "raw_symbol": "SHOP", "currency": {"code": "USD"}, "type": {"code": "cs"}, "exchange": {"code": "NYSE"}},
        {"id": "b", "symbol": "SHOP", "raw_symbol": "SHOP", "currency": {"code": "CAD"}, "type": {"code": "cs"}, "exchange": {"code": "TSX"}},
    ])
    with pytest.raises(OrderError, match="ambiguous"):
        preview_order(s, req(symbol="SHOP"))
    s.client.trading.get_order_impact.assert_not_called()


def test_no_exact_match_refused(session_factory):
    s = session_factory()
    with pytest.raises(OrderError, match="no exact match"):
        preview_order(s, req(symbol="XEQ"))


def test_raw_symbol_match_works(session_factory):
    s = session_factory()
    assert preview_order(s, req(symbol="XEQT")).symbol.exchange == "TSX"


def test_live_code_only_in_one_function():
    """place_order / place_force_order are referenced only inside _submit_live_order."""
    import inspect
    src = inspect.getsource(orders)
    assert src.count(".place_order(") == 1 and ".place_force_order(" not in src
    assert ".place_order(" in inspect.getsource(orders._submit_live_order)
    for name in ("place_mleg_order", "get_option_impact", "place_crypto_order", "experimental_endpoints"):
        assert name not in src


@pytest.mark.parametrize("argv", [
    ["preview", "--side", "BUY_TO_OPEN", "--symbol", "AAPL", "--units", "1", "--type", "Limit", "--price", "1", "--tif", "Day"],
    ["preview", "--side", "BUY", "--symbol", "BTC/CAD", "--units", "1", "--type", "Limit", "--price", "1", "--tif", "Day"],
    ["preview", "--side", "BUY", "--symbol", "XEQT", "--units", "1", "--type", "Limit", "--price", "1", "--tif", "FOK"],
])
def test_cli_rejects_invalid_orders_with_zero_api_calls(session_factory, argv):
    s = session_factory()
    code = run([argv[0], "--account", "7777", *argv[1:]], session=s, out=io.StringIO())
    assert code == 1
    assert s.client.mock_calls == []          # not a single SDK call was made
