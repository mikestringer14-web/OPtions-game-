import io
import json
import logging

from conftest import ACCOUNT_ID, CONSUMER_KEY

from snaptrade_watch.audit_log import AuditLog, RedactingFilter
from snaptrade_watch.orders import OrderRequest, preview_order


def test_jsonl_valid_and_redacted(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl", secrets=[CONSUMER_KEY])
    log.write("preview", account_id=ACCOUNT_ID, symbol="XEQT.TO", note=f"key={CONSUMER_KEY} acct={ACCOUNT_ID}",
              user_secret="hunter2", trade_id="trade-abcdef-999", nested={"account": "HQ12345678"})
    log.write("error", error="boom")
    lines = (tmp_path / "a.jsonl").read_text().splitlines()
    recs = [json.loads(line) for line in lines]
    raw = "\n".join(lines)
    assert len(recs) == 2 and recs[0]["account_last4"] == "7777" and recs[0]["dry_run"] is True
    assert "+" in recs[0]["ts"] or "-" in recs[0]["ts"][19:]            # ISO-8601 with offset
    for bad in (CONSUMER_KEY, ACCOUNT_ID, "hunter2", "HQ12345678", "trade-abcdef-999"):
        assert bad not in raw


def test_std_logger_filter_redacts():
    stream = io.StringIO()
    logger = logging.getLogger("t_redact")
    logger.handlers = [logging.StreamHandler(stream)]
    logger.addFilter(RedactingFilter([CONSUMER_KEY]))
    logger.warning("failed with key %s for %s", CONSUMER_KEY, ACCOUNT_ID)
    out = stream.getvalue()
    assert CONSUMER_KEY not in out and ACCOUNT_ID not in out and "****7777" in out


def test_preview_writes_audit_line(session_factory):
    s = session_factory()
    preview_order(s, OrderRequest(ACCOUNT_ID, "BUY", "XEQT.TO", "Limit", "Day", units=1, price=30.0))
    recs = [json.loads(line) for line in s.cfg.log_file.read_text().splitlines()]
    assert recs[-1]["event"] == "preview" and recs[-1]["dry_run"] is True and recs[-1]["symbol"] == "XEQT.TO"
    assert ACCOUNT_ID not in s.cfg.log_file.read_text()
