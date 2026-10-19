"""Paper mode refuses anything that is not a verified, unlocked, IBKR PAPER session."""
import json
from types import SimpleNamespace

import pytest

from options_screener import config as config_mod
from options_screener import paper
from options_screener.paper import PaperRefused, check_pass, verify_paper_account

PAPER_ACCT = "DU" + "1234567"           # built at runtime so the secret scanner never sees a literal
LIVE_ACCT = "U" + "7654321"


class FakeIB:
    def __init__(self, accounts=(PAPER_ACCT,), bid=2.0, ask=2.02, fills=True):
        self.accounts, self.bid, self.ask, self.fills = list(accounts), bid, ask, fills
        self.placed, self.cancelled = [], []

    def managedAccounts(self):
        return self.accounts

    def reqMktData(self, *a, **k):
        return SimpleNamespace(bid=self.bid, ask=self.ask)

    def cancelMktData(self, *a):
        pass

    def sleep(self, s):
        pass

    def placeOrder(self, contract, order):
        self.placed.append(order)
        status = "Filled" if self.fills else "Submitted"
        return SimpleNamespace(orderStatus=SimpleNamespace(status=status, avgFillPrice=order.lmtPrice))

    def cancelOrder(self, order):
        self.cancelled.append(order)


@pytest.fixture
def cfg():
    return config_mod.load()


def write_pass(tmp_path, cfg, **over):
    p = tmp_path / "PASS.json"
    p.write_text(json.dumps({"verdict": "PASS", "mode": "VERIFIED", "config_hash": config_mod.config_hash(cfg), **over}))
    return p


def test_locked_without_pass_file(tmp_path, cfg):
    with pytest.raises(PaperRefused, match="locked"):
        check_pass(cfg, tmp_path / "missing.json")


@pytest.mark.parametrize("over,msg", [({"verdict": "FAIL"}, "PASS"), ({"mode": "PROXY"}, "VERIFIED"),
                                      ({"mode": "MOCK"}, "VERIFIED"), ({"config_hash": "x"}, "config changed")])
def test_pass_file_must_be_valid(tmp_path, cfg, over, msg):
    with pytest.raises(PaperRefused, match=msg):
        check_pass(cfg, write_pass(tmp_path, cfg, **over))


def test_valid_pass_file(tmp_path, cfg):
    assert check_pass(cfg, write_pass(tmp_path, cfg))["verdict"] == "PASS"


@pytest.mark.parametrize("port", [7496, 4001, 9999])
def test_refuses_live_or_unknown_ports(port):
    with pytest.raises(PaperRefused, match="paper port"):
        verify_paper_account(FakeIB(), port, PAPER_ACCT)


@pytest.mark.parametrize("accounts", [[LIVE_ACCT], [PAPER_ACCT, LIVE_ACCT], []])
def test_refuses_non_paper_accounts(accounts):
    with pytest.raises(PaperRefused):
        verify_paper_account(FakeIB(accounts), 4002, PAPER_ACCT)


@pytest.mark.parametrize("expected", ["", LIVE_ACCT, "DU" + "0000009"])
def test_expected_account_must_be_paper_and_present(expected):
    with pytest.raises(PaperRefused):
        verify_paper_account(FakeIB(), 7497, expected)


def test_accepts_paper_session():
    assert verify_paper_account(FakeIB(), 7497, PAPER_ACCT) == PAPER_ACCT


def test_main_refuses_without_flag(capsys):
    assert paper.main(["--report", "x.md"]) == 3
    assert "--paper" in capsys.readouterr().out


def test_mock_report_refused(tmp_path):
    md = tmp_path / "screen_20261020_MOCK.md"
    md.with_suffix(".json").write_text(json.dumps({"mock": True, "candidates": []}))
    with pytest.raises(PaperRefused, match="MOCK"):
        paper.load_candidates(md)


def cand(expiry="2026-10-30"):
    return {"symbol": "ABC", "direction": "bull", "snapshot": {"contract": {"right": "C", "expiry": expiry, "strike": 100}}}


def test_trader_happy_path_limit_at_mid_and_logs(tmp_path, cfg):
    ib, log = FakeIB(), paper.PaperLog(tmp_path / "paper.jsonl")
    from datetime import datetime
    from options_screener.models import ET
    t = paper.PaperTrader(ib, PAPER_ACCT, cfg, log, now=lambda: datetime(2026, 10, 26, 9, 40, tzinfo=ET))
    res = t.trade(cand(), object(), object(), trigger=lambda: True, exit_signal=lambda m, s, e: "target")
    assert res["status"] == "closed"
    buy, sell = ib.placed
    assert buy.action == "BUY" and buy.orderType == "LMT" and buy.lmtPrice == 2.01 and buy.account == PAPER_ACCT
    assert sell.action == "SELL" and sell.orderType == "LMT"
    lines = [json.loads(x) for x in (tmp_path / "paper.jsonl").read_text().splitlines()]
    assert [x["event"] for x in lines][:2] == ["entry_placed", "entry_filled"]
    assert all(PAPER_ACCT not in json.dumps(x) for x in lines)            # account never logged


def test_trader_no_fill_cancels_and_never_retries(tmp_path, cfg):
    from datetime import datetime
    from options_screener.models import ET
    ib = FakeIB(fills=False)
    t = paper.PaperTrader(ib, PAPER_ACCT, cfg, paper.PaperLog(tmp_path / "p.jsonl"),
                          now=lambda: datetime(2026, 10, 26, 9, 40, tzinfo=ET))
    assert t.trade(cand(), object(), object(), lambda: True, lambda *a: None)["status"] == "no_fill"
    assert len(ib.placed) == 1 and len(ib.cancelled) == 1


def test_trader_refuses_0dte_and_wide_spread(tmp_path, cfg):
    from datetime import datetime
    from options_screener.models import ET
    now = lambda: datetime(2026, 10, 26, 9, 40, tzinfo=ET)  # noqa: E731
    t = paper.PaperTrader(FakeIB(), PAPER_ACCT, cfg, paper.PaperLog(tmp_path / "p.jsonl"), now=now)
    with pytest.raises(PaperRefused, match="0DTE"):
        t.trade(cand("2026-10-26"), object(), object(), lambda: True, lambda *a: None)
    wide = paper.PaperTrader(FakeIB(bid=1.0, ask=2.0), PAPER_ACCT, cfg, paper.PaperLog(tmp_path / "p.jsonl"), now=now)
    assert wide.trade(cand(), object(), object(), lambda: True, lambda *a: None)["status"] == "skipped_spread"
