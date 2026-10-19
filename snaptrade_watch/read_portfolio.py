"""Read-only views: accounts, balances, positions, orders, connections. Normalized to dataclasses."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Optional

from .config import mask_id

SUPPORTED_POSITION_KINDS = {"stock", "etf"}


def _f(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _code(cur: Any) -> Optional[str]:
    if isinstance(cur, dict):
        return cur.get("code")
    return cur if isinstance(cur, str) else None


@dataclass
class Account:
    id: str
    name: Optional[str]
    number_masked: str
    kind: str
    connection_id: Optional[str]
    institution: Optional[str]
    raw_type: Optional[str]
    cash_or_margin: Optional[str]
    is_paper: bool


@dataclass
class Balance:
    currency: Optional[str]
    cash: Optional[float]
    buying_power: Optional[float]


@dataclass
class Position:
    symbol: Optional[str]
    description: Optional[str]
    kind: Optional[str]
    exchange: Optional[str]
    currency: Optional[str]
    units: Optional[float]
    price: Optional[float]
    cost_basis: Optional[float]
    market_value: Optional[float]
    supported: bool


@dataclass
class Order:
    brokerage_order_id: Optional[str]
    symbol: Optional[str]
    action: Optional[str]
    status: Optional[str]
    order_type: Optional[str]
    time_in_force: Optional[str]
    total_quantity: Optional[float]
    filled_quantity: Optional[float]
    execution_price: Optional[float]
    limit_price: Optional[float]
    stop_price: Optional[float]
    time_placed: Optional[str]


@dataclass
class Connection:
    id: str
    name: Optional[str]
    brokerage: Optional[str]
    type: Optional[str]
    disabled: bool
    disabled_date: Optional[str]


# ---------------------------------------------------------------- normalizers (pure)

def normalize_account(a: dict) -> Account:
    return Account(
        id=a.get("id", ""),
        name=a.get("display_name") or a.get("name"),
        number_masked=mask_id(a.get("masked_account_number") or a.get("number")),
        kind=a.get("kind") or "investment",
        connection_id=a.get("connection_id") or a.get("brokerage_authorization"),
        institution=a.get("institution_name") or a.get("institution_id"),
        raw_type=a.get("raw_type"),
        cash_or_margin=a.get("cash_or_margin"),
        is_paper=bool(a.get("is_paper")),
    )


def normalize_balances(body: Any) -> list[Balance]:
    rows = body if isinstance(body, list) else (body or {}).get("results", [])
    return [Balance(currency=_code(b.get("currency")), cash=_f(b.get("cash")), buying_power=_f(b.get("buying_power")))
            for b in rows]


def normalize_positions(body: Any) -> list[Position]:
    rows = body if isinstance(body, list) else (body or {}).get("results", [])
    out = []
    for p in rows:
        inst = p.get("instrument") or {}
        kind = inst.get("kind")
        units, price = _f(p.get("units")), _f(p.get("price"))
        out.append(Position(
            symbol=inst.get("symbol"), description=inst.get("description"), kind=kind,
            exchange=inst.get("exchange") if isinstance(inst.get("exchange"), str) else _code(inst.get("exchange")),
            currency=p.get("currency") or inst.get("currency"),
            units=units, price=price, cost_basis=_f(p.get("cost_basis")),
            market_value=units * price if units is not None and price is not None else None,
            supported=kind in SUPPORTED_POSITION_KINDS,
        ))
    return out


def normalize_orders(body: Any) -> list[Order]:
    rows = body if isinstance(body, list) else (body or {}).get("orders", [])
    out = []
    for o in rows:
        sym = o.get("universal_symbol") or {}
        out.append(Order(
            brokerage_order_id=o.get("brokerage_order_id"),
            symbol=sym.get("symbol") if isinstance(sym, dict) else None,
            action=o.get("action"), status=o.get("status"), order_type=o.get("order_type"),
            time_in_force=o.get("time_in_force"),
            total_quantity=_f(o.get("total_quantity")), filled_quantity=_f(o.get("filled_quantity")),
            execution_price=_f(o.get("execution_price")), limit_price=_f(o.get("limit_price")),
            stop_price=_f(o.get("stop_price")), time_placed=o.get("time_placed"),
        ))
    return out


def normalize_connection(c: dict) -> Connection:
    b = c.get("brokerage") or {}
    return Connection(
        id=c.get("id", ""), name=c.get("name"),
        brokerage=b.get("slug") or b.get("name") if isinstance(b, dict) else None,
        type=c.get("type"), disabled=bool(c.get("disabled")), disabled_date=c.get("disabled_date"),
    )


# ---------------------------------------------------------------- SDK calls (read only)

def list_accounts(session) -> list[Account]:
    body = session.read(session.client.account_information.list_all_user_accounts)
    rows = body.get("results", []) if isinstance(body, dict) else (body or [])
    return [normalize_account(a) for a in rows]


def get_balances(session, account_id: str) -> list[Balance]:
    return normalize_balances(session.read(session.client.account_information.get_user_account_balance,
                                           account_id=account_id))


def get_positions(session, account_id: str) -> list[Position]:
    return normalize_positions(session.read(session.client.account_information.get_all_account_positions,
                                            account_id=account_id))


def get_orders(session, account_id: str, state: str = "all", days: Optional[int] = None) -> list[Order]:
    kw = {"account_id": account_id, "state": state}
    if days:
        kw["days"] = days
    return normalize_orders(session.read(session.client.account_information.get_user_account_orders, **kw))


def get_recent_orders(session, account_id: str, only_executed: bool = False) -> list[Order]:
    return normalize_orders(session.read(session.client.account_information.get_user_account_recent_orders,
                                         account_id=account_id, only_executed=only_executed))


def list_connections(session) -> list[Connection]:
    body = session.read(session.client.connections.list_brokerage_authorizations)
    rows = body if isinstance(body, list) else (body or {}).get("results", [])
    return [normalize_connection(c) for c in rows]


def disabled_connection_warnings(connections: list[Connection]) -> list[str]:
    return [f"Connection {mask_id(c.id)} ({c.brokerage or c.name}) is DISABLED since {c.disabled_date or 'unknown'}. "
            f"Reconnect: python -m snaptrade_watch.cli link --reconnect <connection id>"
            for c in connections if c.disabled]


# ---------------------------------------------------------------- output

def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return str(v)


def table(rows: list[list[Any]], headers: list[str]) -> str:
    cells = [headers] + [[_fmt(c) for c in r] for r in rows]
    widths = [max(len(str(r[i])) for r in cells) for i in range(len(headers))]
    lines = ["  ".join(str(c).ljust(w) for c, w in zip(r, widths)) for r in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def portfolio_snapshot(session, account: Account) -> dict:
    return {
        "account": {**asdict(account), "id": mask_id(account.id), "connection_id": mask_id(account.connection_id)},
        "balances": [asdict(b) for b in get_balances(session, account.id)],
        "positions": [asdict(p) for p in get_positions(session, account.id)],
        "open_orders": [asdict(o) for o in get_orders(session, account.id, state="open")],
        "recent_orders_24h": [asdict(o) for o in get_recent_orders(session, account.id)],
    }


def render_snapshot(snap: dict) -> str:
    a = snap["account"]
    out = [f"\n=== {a['name'] or 'Account'}  {a['number_masked']}  ({a['raw_type'] or a['kind']}, id {a['id']})"]
    out.append(table([[b["currency"], b["cash"], b["buying_power"]] for b in snap["balances"]],
                     ["currency", "cash", "buying_power"]))
    pos = snap["positions"]
    if pos:
        out.append("")
        out.append(table([[p["symbol"], p["kind"], p["units"], p["price"], p["market_value"], p["currency"],
                           "" if p["supported"] else "NOT stock/etf"] for p in pos],
                         ["symbol", "kind", "units", "price", "value", "ccy", "note"]))
    else:
        out.append("(no positions)")
    for title, key in (("Open orders", "open_orders"), ("Last 24h orders", "recent_orders_24h")):
        rows = snap[key]
        out.append(f"\n{title}: {len(rows)}")
        if rows:
            out.append(table([[o["symbol"], o["action"], o["total_quantity"], o["order_type"], o["limit_price"],
                               o["status"], o["time_placed"]] for o in rows],
                             ["symbol", "action", "qty", "type", "limit", "status", "placed"]))
    return "\n".join(out)


def to_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)
