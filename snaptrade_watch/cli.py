"""Command line: python -m snaptrade_watch.cli <command> ...  (dry-run unless the live gate is met)."""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from . import link_account, notify, orders, read_portfolio
from .audit_log import AuditLog, get_logger
from .client import AccountRateLimiter, Session, build_client
from .config import ConfigError, load_config, mask_id, redact


def make_session(cfg) -> Session:
    return Session(cfg=cfg, client=build_client(cfg),
                   audit=AuditLog(cfg.log_file, cfg.secrets(), dry_run=not cfg.live_trading),
                   limiter=AccountRateLimiter())


class RefError(Exception):
    pass


def _match(ref: str, ids: list[str], label: str) -> str:
    """Accept a full id or its last few characters (what the tables print)."""
    ref = ref.strip().lstrip("*")
    hits = [i for i in ids if i == ref or (len(ref) >= 4 and i.endswith(ref))]
    if len(hits) != 1:
        raise RefError(f"{label} {ref!r} matched {len(hits)} entries; run the list command and use a longer suffix")
    return hits[0]


def resolve_account(session, ref: str) -> str:
    return _match(ref, [a.id for a in read_portfolio.list_accounts(session)], "account")


def resolve_connection(session, ref: str) -> str:
    return _match(ref, [c.id for c in read_portfolio.list_connections(session)], "connection")


def resolve_order(session, account_id: str, ref: str) -> str:
    ids = [o.brokerage_order_id for o in read_portfolio.get_orders(session, account_id, "open") if o.brokerage_order_id]
    return _match(ref, ids, "open order")


def _order_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--account", required=True)
    p.add_argument("--side", required=True, help="BUY or SELL")
    p.add_argument("--symbol", required=True, help="e.g. XEQT or XEQT.TO")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--units", type=float, help="whole shares")
    g.add_argument("--notional", type=float, help="dollar amount (Market + Day only)")
    p.add_argument("--type", dest="order_type", required=True, help="Market | Limit | Stop | StopLimit")
    p.add_argument("--price", type=float)
    p.add_argument("--stop", type=float)
    p.add_argument("--tif", required=True, help="Day | GTC")


def _request(a) -> orders.OrderRequest:
    return orders.OrderRequest(account_id=a.account, side=a.side, symbol=a.symbol, order_type=a.order_type,
                               time_in_force=a.tif, units=a.units, notional=a.notional, price=a.price, stop=a.stop)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="snaptrade_watch", description="Watch-only / dry-run SnapTrade tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("register")
    p = sub.add_parser("link")
    p.add_argument("--trade-connection", action="store_true", help="request trade-if-available access")
    p.add_argument("--broker", help="e.g. WEALTHSIMPLETRADE or SANDBOX")
    p.add_argument("--reconnect", help="existing connection id to reconnect/upgrade")
    sub.add_parser("connections")
    sub.add_parser("accounts")
    p = sub.add_parser("portfolio")
    p.add_argument("--account")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("quote")
    p.add_argument("symbols")
    p.add_argument("--account", required=True)
    p = sub.add_parser("orders")
    p.add_argument("--account", required=True)
    p.add_argument("--state", default="all", choices=["all", "open", "executed"])
    p.add_argument("--days", type=int)
    _order_args(sub.add_parser("preview"))
    p = sub.add_parser("place")
    _order_args(p)
    p.add_argument("--live", action="store_true")
    p = sub.add_parser("cancel")
    p.add_argument("--account", required=True)
    p.add_argument("--order", required=True)
    p.add_argument("--live", action="store_true")
    return ap


def run(argv: Optional[list] = None, session: Optional[Session] = None, out=None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        cfg = session.cfg if session else load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2
    log = get_logger(cfg.secrets())
    session = session or make_session(cfg)
    say = lambda s="": out.write(redact(s, cfg.secrets()) + "\n")  # noqa: E731

    try:
        if args.cmd == "status":
            body = session.read(session.client.api_status.check, user_scoped=False)
            say(f"SnapTrade API: {'online' if (body or {}).get('online', True) else 'OFFLINE'}")
            say(f"Auth mode: {cfg.auth_mode}  |  Mode: {cfg.mode_label}  |  LIVE_TRADING env is "
                f"{'exactly true' if cfg.live_trading else 'not true (dry-run)'}")
            say(f"Order cap: {cfg.max_order_value_cad:,.2f} CAD  |  Audit log: {cfg.log_file}")
        elif args.cmd == "register":
            say(link_account.register(session))
        elif args.cmd == "link":
            ctype = "trade-if-available" if args.trade_connection else "read"
            reconnect = resolve_connection(session, args.reconnect) if args.reconnect else None
            url = link_account.portal_url(session, ctype, broker=args.broker, reconnect=reconnect)
            out.write(url + "\n")          # the portal URL itself must be shown in full
            say(link_account.PORTAL_TTL_NOTE)
            say("After you finish in the browser, run:  python -m snaptrade_watch.cli connections")
        elif args.cmd == "connections":
            conns, warnings = link_account.connections_report(session)
            say(read_portfolio.table([[mask_id(c.id), c.brokerage, c.name, c.type, "DISABLED" if c.disabled else "ok"]
                                      for c in conns], ["id", "brokerage", "name", "type", "state"]))
            for w in warnings:
                say("WARNING: " + w)
        elif args.cmd == "accounts":
            accts = read_portfolio.list_accounts(session)
            say(read_portfolio.table([[mask_id(a.id), a.name, a.number_masked, a.kind, a.raw_type, a.cash_or_margin]
                                      for a in accts],
                                     ["account (use with --account)", "name", "number", "kind", "type", "cash/margin"]))
            _, warnings = link_account.connections_report(session)
            for w in warnings:
                say("WARNING: " + w)
        elif args.cmd == "portfolio":
            accts = [a for a in read_portfolio.list_accounts(session) if a.kind == "investment"]
            if args.account:
                wanted = resolve_account(session, args.account)
                accts = [a for a in accts if a.id == wanted]
                if not accts:
                    say("That account is not an investment account. Run `accounts` to list them.")
                    return 1
            snaps = [read_portfolio.portfolio_snapshot(session, a) for a in accts]
            if args.json:
                say(read_portfolio.to_json(snaps))
            else:
                for s in snaps:
                    say(read_portfolio.render_snapshot(s))
        elif args.cmd == "quote":
            syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
            if len(syms) > 10:
                say("At most 10 symbols per quote call.")
                return 1
            quotes = session.read(session.client.trading.get_user_account_quotes,
                                  account_id=resolve_account(session, args.account),
                                  symbols=",".join(syms), use_ticker=True)
            rows = []
            for q in quotes or []:
                sym = (q.get("symbol") or {})
                rows.append([sym.get("symbol") if isinstance(sym, dict) else sym, q.get("bid_price"),
                             q.get("ask_price"), q.get("last_trade_price")])
            say(read_portfolio.table(rows, ["symbol", "bid", "ask", "last"]))
            say("Quotes may be delayed. Called on demand only.")
        elif args.cmd == "orders":
            rows = read_portfolio.get_orders(session, resolve_account(session, args.account), args.state, args.days)
            say(read_portfolio.table([["..." + (o.brokerage_order_id or "")[-6:], o.symbol, o.action,
                                       o.total_quantity, o.filled_quantity, o.order_type,
                                       o.limit_price, o.status, o.time_placed] for o in rows],
                                     ["order", "symbol", "action", "qty", "filled", "type", "limit", "status", "placed"]))
        elif args.cmd == "preview":
            orders.validate_order(_request(args))                # reject bad/option/crypto orders before any call
            args.account = resolve_account(session, args.account)
            p = orders.preview_order(session, _request(args))
            say("DRY-RUN PREVIEW (nothing was placed)\n")
            for line in p.summary_lines():
                say(line)
            notify.send(f"Dry-run preview: {p.request.side} {p.quantity_text()} {p.symbol.symbol} "
                        f"{p.request.order_type} est {p.estimated_value:,.2f} {p.symbol.currency}", cfg)
        elif args.cmd == "place":
            orders.require_live_trading_allowed(cfg, args.live)   # refuse before any network call
            orders.validate_order(_request(args))
            args.account = resolve_account(session, args.account)
            res = orders.place_live(session, _request(args), live_flag=args.live)
            say("Not confirmed. Nothing was placed." if res is None else
                "LIVE order sent. Result and the reconciled recent orders are in the audit log.")
        elif args.cmd == "cancel":
            orders.require_live_trading_allowed(cfg, args.live)
            account = resolve_account(session, args.account)
            res = orders.cancel_order(session, account, resolve_order(session, account, args.order), live_flag=args.live)
            say("Not confirmed. Nothing was cancelled." if res is None else "Cancel sent; see the audit log.")
        return 0
    except orders.LiveTradingDisabled as e:
        say(f"REFUSED (dry-run safety): {e}")
        session.audit.write("live_refused", reason=str(e))
        return 3
    except (RefError, orders.OrderError, link_account.LinkError, orders.PreviewExpired, orders.LiveOrderUncertain) as e:
        say(f"Error: {e}")
        session.audit.write("error", error=str(e), cmd=args.cmd)
        return 1
    except Exception as e:
        status = getattr(e, "status", None)
        body = getattr(e, "body", None)
        msg = f"{type(e).__name__}" + (f" (HTTP {status})" if status else "")
        log.error("%s %s", msg, redact(str(body)[:500], cfg.secrets()) if body else "")
        session.audit.write("api_error", status=status, body=str(body)[:500] if body else None, cmd=args.cmd)
        if status == 429:
            say("Rate limited by SnapTrade (429) after retries. Wait a minute and try again.")
        elif status is None:
            say("Could not reach api.snaptrade.com. Check your internet connection and try again.")
        notify.send(f"snaptrade_watch error in {args.cmd}: {msg}", cfg)
        say(f"Error: {msg}. Details (redacted) are in the audit log.")
        return 1


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
