import json

from conftest import ACCOUNT_ID, BALANCES, POSITIONS, assert_nothing_placed

from snaptrade_watch import read_portfolio as rp
from snaptrade_watch.cli import run
from snaptrade_watch.client import plain, user_kwargs


def test_multi_currency_balances():
    b = rp.normalize_balances(BALANCES)
    assert [(x.currency, x.cash) for x in b] == [("CAD", 152.34), ("USD", 10.0)]


def test_positions_flag_unsupported_kinds():
    p = rp.normalize_positions(POSITIONS)
    assert [x.kind for x in p] == ["etf", "stock", "option"]
    assert [x.supported for x in p] == [True, True, False]
    assert p[0].market_value == 3 * 31.5 and p[0].currency == "CAD"


def test_account_number_is_masked():
    a = rp.normalize_account({"id": ACCOUNT_ID, "masked_account_number": "HQ12345678", "kind": "investment"})
    assert a.number_masked == "****5678"


def test_orders_normalized():
    o = rp.normalize_orders({"orders": [{"brokerage_order_id": "B1", "universal_symbol": {"symbol": "VFV.TO"},
                                         "action": "BUY", "status": "EXECUTED", "total_quantity": "2",
                                         "limit_price": "100.5"}]})
    assert (o[0].symbol, o[0].total_quantity, o[0].limit_price) == ("VFV.TO", 2.0, 100.5)


def test_disabled_connection_warning():
    c = rp.normalize_connection({"id": "conn-1234", "brokerage": {"slug": "WEALTHSIMPLETRADE"}, "disabled": True,
                                 "disabled_date": "2026-10-01"})
    w = rp.disabled_connection_warnings([c])
    assert len(w) == 1 and "DISABLED" in w[0] and "reconnect" in w[0].lower()


def test_personal_mode_sends_no_user_args(session_factory):
    s = session_factory()
    rp.list_accounts(s)
    _, kwargs = s.client.account_information.list_all_user_accounts.call_args
    assert "user_id" not in kwargs and "user_secret" not in kwargs
    assert user_kwargs(s.cfg) == {}


def test_commercial_mode_sends_user_args(session_factory):
    s = session_factory(auth_mode="commercial", user_id="mike-local-1")
    s.secret_reader = lambda path: "the-secret"
    rp.get_balances(s, ACCOUNT_ID)
    _, kwargs = s.client.account_information.get_user_account_balance.call_args
    assert kwargs["user_id"] == "mike-local-1" and kwargs["user_secret"] == "the-secret"


def test_portfolio_cli_json_masks_ids(session_factory, capsys):
    import io
    s = session_factory()
    out = io.StringIO()
    assert run(["portfolio", "--json"], session=s, out=out) == 0
    text = out.getvalue()
    data = json.loads(text)
    assert len(data) == 1                                  # deposit account skipped
    assert ACCOUNT_ID not in text and "HQ12345678" not in text
    assert data[0]["balances"][0]["currency"] == "CAD"
    assert_nothing_placed(s.client)


def test_accounts_cli_and_suffix_lookup(session_factory):
    import io
    s = session_factory()
    out = io.StringIO()
    assert run(["accounts"], session=s, out=out) == 0
    assert ACCOUNT_ID not in out.getvalue() and "****7777" in out.getvalue()
    out = io.StringIO()
    assert run(["portfolio", "--account", "7777"], session=s, out=out) == 0
    assert "Wealthsimple TFSA" in out.getvalue()


def test_plain_converts_sdk_types():
    from decimal import Decimal
    assert plain({"a": Decimal("2"), "b": [Decimal("1.5")], "c": None}) == {"a": 2, "b": [1.5], "c": None}
