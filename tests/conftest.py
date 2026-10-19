"""Shared fixtures. A MagicMock stands in for the SnapTrade SDK: no test touches the network."""
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from snaptrade_watch.audit_log import AuditLog  # noqa: E402
from snaptrade_watch.client import AccountRateLimiter, Session  # noqa: E402
from snaptrade_watch.config import Config  # noqa: E402

ACCOUNT_ID = "11111111-2222-3333-4444-555566667777"
CONN_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff0001"
CONSUMER_KEY = "CK_super_secret_consumer_key_123"

# Every SDK method that could place, change or cancel an order (sync and async).
FORBIDDEN_TRADING = ["place_order", "place_force_order", "cancel_order", "replace_order", "place_mleg_order",
                     "place_complex_order", "place_crypto_order", "get_option_impact", "preview_crypto_order"]
FORBIDDEN_TRADING += ["a" + n for n in FORBIDDEN_TRADING]


def resp(body, headers=None):
    return SimpleNamespace(body=body, headers=headers or {}, status=200)


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


class NotTTY(io.StringIO):
    def isatty(self):
        return False


ACCOUNTS = {"results": [
    {"kind": "investment", "id": ACCOUNT_ID, "connection_id": CONN_ID, "masked_account_number": "HQ12345678",
     "display_name": "Wealthsimple TFSA", "raw_type": "TFSA", "cash_or_margin": "cash", "is_paper": False,
     "institution_id": "ws"},
    {"kind": "deposit", "id": "99999999-0000-0000-0000-000000000009", "connection_id": CONN_ID,
     "masked_account_number": "CASH9876", "display_name": "Cash", "is_paper": False},
]}
BALANCES = [{"currency": {"code": "CAD", "id": "c1"}, "cash": 152.34, "buying_power": 152.34},
            {"currency": {"code": "USD", "id": "c2"}, "cash": 10.0, "buying_power": 10.0}]
POSITIONS = {"results": [
    {"instrument": {"kind": "etf", "id": "s1", "symbol": "XEQT.TO", "raw_symbol": "XEQT", "description": "iShares Core Equity",
                    "currency": "CAD", "exchange": "TSX"}, "units": "3", "price": "31.50", "cost_basis": "29.00", "currency": "CAD"},
    {"instrument": {"kind": "stock", "id": "s2", "symbol": "AAPL", "raw_symbol": "AAPL", "currency": "USD", "exchange": "NASDAQ"},
     "units": "1", "price": "200", "cost_basis": "180", "currency": "USD"},
    {"instrument": {"kind": "option", "id": "o1", "symbol": "AAPL 261218C00200000"}, "units": "1", "price": "5"},
], "data_freshness": {}}
XEQT_TSX = {"id": "usym-xeqt", "symbol": "XEQT.TO", "raw_symbol": "XEQT", "description": "iShares Core Equity ETF",
            "currency": {"code": "CAD"}, "exchange": {"code": "TSX", "name": "Toronto Stock Exchange"},
            "type": {"code": "et", "description": "ETF"}}
IMPACT = {"trade": {"id": "trade-abc-123", "account": ACCOUNT_ID, "order_type": "Limit", "time_in_force": "Day",
                    "action": "BUY", "units": 1, "price": 30.0, "symbol": {"universal_symbol_id": "usym-xeqt"}},
          "trade_impacts": [{"currency": "CAD", "remaining_cash": 122.34, "estimated_commission": 0, "forex_fees": 0}],
          "combined_remaining_balance": {"cash": 122.34}}
CONNECTIONS = [{"id": CONN_ID, "name": "Wealthsimple", "brokerage": {"slug": "WEALTHSIMPLETRADE"}, "type": "read",
                "disabled": False}]


def make_client():
    c = MagicMock(name="SnapTrade")
    c.account_information.list_all_user_accounts.return_value = resp(ACCOUNTS)
    c.account_information.get_user_account_balance.return_value = resp(BALANCES)
    c.account_information.get_all_account_positions.return_value = resp(POSITIONS)
    c.account_information.get_user_account_orders.return_value = resp([])
    c.account_information.get_user_account_recent_orders.return_value = resp({"orders": []})
    c.connections.list_brokerage_authorizations.return_value = resp(CONNECTIONS)
    c.reference_data.symbol_search_user_account.return_value = resp([XEQT_TSX])
    c.reference_data.list_all_brokerages.return_value = resp([{"slug": "WEALTHSIMPLETRADE"}, {"slug": "QUESTRADE"}])
    c.trading.get_order_impact.return_value = resp(IMPACT)
    c.trading.get_user_account_quotes.return_value = resp([{"symbol": {"symbol": "XEQT.TO"}, "last_trade_price": 31.0}])
    c.trading.place_order.return_value = resp({"brokerage_order_id": "BRK-777", "status": "PENDING"})
    c.authentication.login_snap_trade_user.return_value = resp({"redirectURI": "https://app.snaptrade.com/portal?x=1"})
    c.api_status.check.return_value = resp({"online": True, "version": 1})
    return c


def assert_nothing_placed(client):
    for name in FORBIDDEN_TRADING:
        getattr(client.trading, name).assert_not_called()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY", "SNAPTRADE_AUTH_MODE", "SNAPTRADE_USER_ID",
              "SNAPTRADE_USER_SECRET_FILE", "LIVE_TRADING", "MAX_ORDER_VALUE_CAD", "LOG_FILE",
              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CAP_USD_CAD_RATE"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def cfg_factory(tmp_path):
    def make(**kw):
        base = dict(client_id="client-id", consumer_key=CONSUMER_KEY, log_file=tmp_path / "logs" / "audit.jsonl",
                    user_secret_file=tmp_path / "secret" / "user_secret")
        base.update(kw)
        return Config(**base)
    return make


@pytest.fixture
def session_factory(cfg_factory):
    def make(**cfg_kw):
        cfg = cfg_factory(**cfg_kw)
        return Session(cfg=cfg, client=make_client(), audit=AuditLog(cfg.log_file, cfg.secrets(), not cfg.live_trading),
                       limiter=AccountRateLimiter(interval=0))
    return make


@pytest.fixture
def live_env(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING", "true")
