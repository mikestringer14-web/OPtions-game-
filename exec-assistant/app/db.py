"""SQLite access. One file, WAL mode, safe for a single small server."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings

_SCHEMA = Path(__file__).with_name("schema.sql").read_text()
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | None = None) -> sqlite3.Connection:
    global _conn, _conn_path
    path = path or settings.db_path
    with _lock:
        if _conn is not None and _conn_path == path:
            return _conn
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        _conn, _conn_path = conn, path
        return conn


def reset(path: str) -> sqlite3.Connection:
    """Used by tests: drop the cached connection and open a new DB."""
    global _conn, _conn_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn, _conn_path = None, None
    return connect(path)


def q(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with _lock:
        cur = connect().execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def ex(sql: str, params: tuple | list = ()) -> int:
    with _lock:
        cur = connect().execute(sql, params)
        return cur.lastrowid


def get_setting(key: str, default: str | None = None) -> str | None:
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def audit(actor: str, event: str, detail: Any = "") -> None:
    if not isinstance(detail, str):
        detail = json.dumps(detail, default=str)[:4000]
    ex("INSERT INTO audit_log(ts,actor,event,detail) VALUES(?,?,?,?)", (now_iso(), actor, event, detail))
