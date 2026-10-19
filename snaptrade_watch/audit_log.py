"""JSON-lines audit log with redaction, plus a redacting filter for the std logger."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import mask_id, redact

# Fields that hold identifiers: always reduced to the last 4 characters.
ID_FIELDS = {"account_id", "account", "account_number", "authorization_id", "connection_id",
             "brokerage_order_id", "order_id", "trade_id", "user_id", "id"}
# Fields that must never be written at all.
DROP_FIELDS = {"user_secret", "userSecret", "consumer_key", "consumerKey", "token", "telegram_bot_token"}


def scrub(value: Any, secrets: Iterable[str], key: str = "") -> Any:
    if key in DROP_FIELDS:
        return "***"
    if isinstance(value, dict):
        return {k: scrub(v, secrets, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, secrets, key) for v in value]
    if isinstance(value, str):
        if key in ID_FIELDS:
            return mask_id(value)
        return redact(value, secrets)
    return value


class AuditLog:
    def __init__(self, path: Path, secrets: Iterable[str] = (), dry_run: bool = True):
        self.path = Path(path)
        self.secrets = list(secrets)
        self.dry_run = dry_run
        self._lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> dict:
        account = fields.pop("account_id", None)
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            "mode": "dry-run" if self.dry_run else "live-enabled",
            "dry_run": self.dry_run,
        }
        if account:
            record["account_last4"] = str(account)[-4:]
        record.update(fields)
        record = scrub(record, self.secrets)
        line = json.dumps(record, default=str, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return record


class RedactingFilter(logging.Filter):
    """Rewrites every log record so secrets and full IDs never reach a handler."""

    def __init__(self, secrets: Iterable[str] = ()):
        super().__init__()
        self.secrets = list(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = redact(message, self.secrets)
        record.args = ()
        return True


def get_logger(secrets: Iterable[str] = (), name: str = "snaptrade_watch") -> logging.Logger:
    logger = logging.getLogger(name)
    for f in list(logger.filters):
        if isinstance(f, RedactingFilter):
            logger.removeFilter(f)
    logger.addFilter(RedactingFilter(secrets))
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger
