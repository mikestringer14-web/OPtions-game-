"""Run the REAL SDK's request building and schema validation, with HTTP stubbed out.
This catches argument and type mismatches that a MagicMock client cannot."""
from unittest.mock import patch

import pytest

from snaptrade_watch.client import build_client
from snaptrade_watch.config import Config
from snaptrade_watch.orders import OrderRequest, ResolvedSymbol, _impact_kwargs, validate_order

A = "11111111-2222-3333-4444-555566667777"
SYM = ResolvedSymbol("22222222-2222-3333-4444-555566667777", "XEQT.TO", "XEQT", None, "CAD", "TSX", "et")


class Sent(Exception):
    pass


@pytest.fixture
def captured():
    calls = []

    def fake(self, method, url, *a, **kw):
        calls.append((method, url, kw.get("body")))
        raise Sent()

    with patch("snaptrade_client.rest.RESTClientObject.request", fake):
        yield calls


@pytest.fixture
def client():
    return build_client(Config(client_id="cid", consumer_key="ck"))


@pytest.mark.parametrize("req", [
    OrderRequest(A, "BUY", "XEQT.TO", "Limit", "Day", units=1, price=30.0),
    OrderRequest(A, "SELL", "XEQT.TO", "StopLimit", "GTC", units=2, price=29.0, stop=29.5),
    OrderRequest(A, "BUY", "XEQT.TO", "Market", "Day", notional=100),
    OrderRequest(A, "BUY", "XEQT.TO", "Stop", "Day", units=3, stop=28.0),
])
def test_impact_request_passes_sdk_validation(client, captured, req):
    with pytest.raises(Sent):
        client.trading.get_order_impact(**_impact_kwargs(validate_order(req), SYM))
    method, url, _ = captured[0]
    assert method == "POST" and "/trade/impact" in url


@pytest.mark.parametrize("call", [
    lambda c: c.account_information.list_all_user_accounts(),
    lambda c: c.account_information.get_user_account_balance(account_id=A),
    lambda c: c.account_information.get_all_account_positions(account_id=A),
    lambda c: c.account_information.get_user_account_orders(account_id=A, state="open", days=30),
    lambda c: c.account_information.get_user_account_recent_orders(account_id=A, only_executed=False),
    lambda c: c.connections.list_brokerage_authorizations(),
    lambda c: c.reference_data.symbol_search_user_account(account_id=A, substring="XEQT"),
    lambda c: c.trading.get_user_account_quotes(account_id=A, symbols="XEQT.TO,VFV.TO", use_ticker=True),
    lambda c: c.authentication.login_snap_trade_user(connection_type="read", broker="SANDBOX"),
    lambda c: c.api_status.check(),
])
def test_read_requests_pass_sdk_validation(client, captured, call):
    with pytest.raises(Sent):
        call(client)
    assert captured


def test_user_scoped_requests_are_signed(client, captured):
    with pytest.raises(Sent):
        client.account_information.get_user_account_balance(account_id=A)
    url = captured[0][1]
    assert "clientId=cid" in url and "timestamp=" in url and "ck" not in url   # consumer key never in the URL
