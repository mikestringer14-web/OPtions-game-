"""Order validation, dry-run preview (order impact) and the guarded live path.

Safety model:
  * Dry-run is the default. In dry-run the only trading call made is get_order_impact,
    which does not place anything.
  * Live placement and cancels go through require_live_trading_allowed(), which needs
    LIVE_TRADING == "true" (checked in config AND in the live environment), the --live flag,
    and a real TTY. Then Mike must type the exact confirmation phrase.
  * _submit_live_order() is the ONLY function that calls a placing method, and it re-checks
    the guard. A live place call is never retried: Wealthsimple has no idempotent
    client_order_id, so a retry could duplicate the order.
  * No options, no crypto: stocks and ETFs only.
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TextIO

from .client import body_of
from .config import Config, mask_id

ALLOWED_SIDES = {"BUY", "SELL"}
OPTION_ACTIONS = {"BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_CLOSE"}
ALLOWED_TYPES = {"Market", "Limit", "Stop", "StopLimit"}
ALLOWED_TIF = {"Day", "GTC"}                      # Wealthsimple via SnapTrade: no FOK/IOC
# SnapTrade security type codes accepted as stock/ETF. Anything else is refused.
ALLOWED_SECURITY_TYPES = {"cs", "et"}
TRADE_ID_TTL_S = 300
EXPIRY_MARGIN_S = 20                              # treat the trade id as expired a bit early
OCC_OPTION = re.compile(r"^[A-Z.]{1,6}\s*\d{6}[CP]\d{8}$")
OPTION_HINT = re.compile(r"\d{6}[CP]\d", re.I)


class OrderError(ValueError):
    """The order request is invalid or not allowed by this tool."""


class LiveTradingDisabled(RuntimeError):
    """Live placement was requested but the three-part gate is not satisfied."""


class PreviewExpired(RuntimeError):
    pass


class LiveOrderUncertain(RuntimeError):
    """A live call failed ambiguously. It was NOT retried; check recent orders by hand."""


# ---------------------------------------------------------------- request + validation

@dataclass
class OrderRequest:
    account_id: str
    side: str
    symbol: str
    order_type: str
    time_in_force: str
    units: Optional[float] = None
    notional: Optional[float] = None
    price: Optional[float] = None
    stop: Optional[float] = None


def _canon(value: str, allowed: set[str], label: str) -> str:
    for a in allowed:
        if value.lower() == a.lower():
            return a
    raise OrderError(f"{label} must be one of {sorted(allowed)}, got {value!r}")


def looks_like_option(symbol: str) -> bool:
    s = symbol.strip().upper()
    return bool(OCC_OPTION.match(s) or OPTION_HINT.search(s.replace(" ", "")))


def looks_like_crypto(symbol: str) -> bool:
    return "/" in symbol


def validate_order(req: OrderRequest) -> OrderRequest:
    """Normalize case and enforce this tool's rules. Pure: no network."""
    side = req.side.strip().upper()
    if side in OPTION_ACTIONS:
        raise OrderError(f"{side} is an options action. Options trading is not supported by this tool.")
    if side not in ALLOWED_SIDES:
        raise OrderError(f"side must be BUY or SELL, got {req.side!r}")
    symbol = req.symbol.strip().upper()
    if not symbol:
        raise OrderError("symbol is required")
    if looks_like_option(symbol):
        raise OrderError(f"{symbol!r} looks like an option symbol. Options are not supported.")
    if looks_like_crypto(symbol):
        raise OrderError(f"{symbol!r} looks like a crypto pair. Crypto is not supported; stocks and ETFs only.")

    tif_raw = req.time_in_force.strip()
    if tif_raw.upper() in ("FOK", "IOC", "GTD"):
        raise OrderError(f"time in force {tif_raw.upper()} is not supported for Wealthsimple; use Day or GTC")
    order_type = _canon(req.order_type.strip(), ALLOWED_TYPES, "order type")
    tif = _canon(tif_raw, ALLOWED_TIF, "time in force")

    units, notional = req.units, req.notional
    if (units is None) == (notional is None):
        raise OrderError("give exactly one of --units or --notional")
    if units is not None:
        if float(units) <= 0 or not float(units).is_integer():
            raise OrderError("units must be a whole number above 0 (Wealthsimple: whole shares only)")
        units = int(units)
    if notional is not None:
        if float(notional) <= 0:
            raise OrderError("notional must be above 0")
        if order_type != "Market" or tif != "Day":
            raise OrderError("a dollar-amount (notional) order only works with type Market and TIF Day")
        notional = float(notional)

    price, stop = req.price, req.stop
    if order_type in ("Limit", "StopLimit"):
        if price is None or price <= 0:
            raise OrderError(f"{order_type} needs --price above 0")
    elif price is not None:
        raise OrderError(f"--price is not used for {order_type} orders")
    if order_type in ("Stop", "StopLimit"):
        if stop is None or stop <= 0:
            raise OrderError(f"{order_type} needs --stop above 0")
    elif stop is not None:
        raise OrderError(f"--stop is not used for {order_type} orders")

    return OrderRequest(req.account_id, side, symbol, order_type, tif, units, notional, price, stop)


def estimate_value(req: OrderRequest, ref_price: Optional[float] = None) -> Optional[float]:
    """Order value in the symbol's currency, from what we know before the brokerage preview."""
    if req.notional is not None:
        return req.notional
    px = req.price if req.order_type in ("Limit", "StopLimit") else req.stop if req.order_type == "Stop" else ref_price
    return None if px is None else req.units * px


def to_cad(value: float, currency: Optional[str], cfg: Config) -> float:
    """Conservative conversion for the cap check only. Unknown currency is treated as USD."""
    if currency and currency.upper() == "CAD":
        return value
    if not currency or currency.upper() == "USD":
        return value * cfg.usd_cad_cap_rate
    raise OrderError(f"cannot check the order cap for currency {currency}")


def check_cap(value: Optional[float], currency: Optional[str], cfg: Config) -> float:
    if value is None:
        raise OrderError("could not estimate the order value, so the MAX_ORDER_VALUE_CAD cap can't be checked; "
                         "use a Limit order or pass a price")
    cad = to_cad(value, currency, cfg)
    if cad > cfg.max_order_value_cad:
        raise OrderError(f"order value about {cad:,.2f} CAD is above MAX_ORDER_VALUE_CAD "
                         f"({cfg.max_order_value_cad:,.2f}). Refused, even in dry-run.")
    return cad


# ---------------------------------------------------------------- symbol resolution

@dataclass
class ResolvedSymbol:
    id: str
    symbol: str
    raw_symbol: str
    description: Optional[str]
    currency: Optional[str]
    exchange: Optional[str]
    type_code: Optional[str]


def _resolved(s: dict) -> ResolvedSymbol:
    cur, ex, ty = s.get("currency") or {}, s.get("exchange") or {}, s.get("type") or {}
    return ResolvedSymbol(
        id=s["id"], symbol=s.get("symbol", ""), raw_symbol=s.get("raw_symbol") or s.get("symbol", ""),
        description=s.get("description"),
        currency=cur.get("code") if isinstance(cur, dict) else cur,
        exchange=(ex.get("code") or ex.get("name")) if isinstance(ex, dict) else ex,
        type_code=(ty.get("code") if isinstance(ty, dict) else ty),
    )


def pick_symbol(results: list[dict], query: str) -> ResolvedSymbol:
    """Exact ticker match only. Refuse if none, or if several listings match."""
    q = query.upper()
    exact = [r for r in results if str(r.get("symbol", "")).upper() == q]
    if not exact:
        exact = [r for r in results if str(r.get("raw_symbol", "")).upper() == q]
    if not exact:
        raise OrderError(f"no exact match for {query!r} in this account's symbol search")
    if len(exact) > 1:
        options = ", ".join(f"{r.get('symbol')} ({_resolved(r).exchange}, {_resolved(r).currency})" for r in exact)
        raise OrderError(f"{query!r} is ambiguous: {options}. Pass the full symbol, e.g. XEQT.TO")
    sym = _resolved(exact[0])
    if (sym.type_code or "").lower() not in ALLOWED_SECURITY_TYPES:
        raise OrderError(f"{sym.symbol} has security type {sym.type_code!r}; only stocks and ETFs are allowed")
    return sym


def resolve_symbol(session, account_id: str, symbol: str) -> ResolvedSymbol:
    results = session.read(session.client.reference_data.symbol_search_user_account,
                           account_id=account_id, substring=symbol)
    return pick_symbol(results or [], symbol)


def last_price(session, account_id: str, symbol: str) -> Optional[float]:
    quotes = session.read(session.client.trading.get_user_account_quotes,
                          account_id=account_id, symbols=symbol, use_ticker=True)
    for q in quotes or []:
        for k in ("last_trade_price", "ask_price", "bid_price"):
            try:
                v = float(q.get(k))
                if v > 0:
                    return v
            except (TypeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------- dry-run preview

@dataclass
class Preview:
    request: OrderRequest
    symbol: ResolvedSymbol
    trade_id: str
    created_at: float
    estimated_value: float
    estimated_value_cad: float
    impacts: list = field(default_factory=list)
    remaining_cash: Optional[dict] = None
    trade_price: Optional[float] = None
    source: str = "Brokerage preview"

    @property
    def expires_at(self) -> float:
        return self.created_at + TRADE_ID_TTL_S - EXPIRY_MARGIN_S

    def expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) >= self.expires_at

    def quantity_text(self) -> str:
        r = self.request
        return str(r.units) if r.units is not None else f"${r.notional:,.2f}"

    def confirmation_phrase(self) -> str:
        return f"PLACE {self.request.side} {self.quantity_text()} {self.symbol.raw_symbol}"

    def summary_lines(self, now: Optional[float] = None) -> list[str]:
        r, s = self.request, self.symbol
        lines = [
            f"Account:        {mask_id(r.account_id)}",
            f"Symbol:         {s.symbol} ({s.description or ''}) exchange {s.exchange}, currency {s.currency}",
            f"Action:         {r.side}",
            f"Quantity:       {self.quantity_text()}",
            f"Order type:     {r.order_type}"
            + (f"  limit {r.price}" if r.price else "")
            + (f"  stop {r.stop}" if r.stop else ""),
            f"Time in force:  {r.time_in_force}",
            f"Est. value:     {self.estimated_value:,.2f} {s.currency} (about {self.estimated_value_cad:,.2f} CAD for the cap)",
        ]
        for imp in self.impacts:
            lines.append(f"Impact ({imp.get('currency')}): remaining cash {imp.get('remaining_cash')}, "
                         f"est. commission {imp.get('estimated_commission')}, FX fees {imp.get('forex_fees')}")
        left = max(0, int(self.expires_at - (now or time.time())))
        lines.append(f"Impact source:  {self.source}  (estimates only; the brokerage sets final price and fees)")
        lines.append(f"Preview valid:  about {left}s more")
        return lines


def _impact_kwargs(req: OrderRequest, sym: ResolvedSymbol) -> dict:
    kw = {"account_id": req.account_id, "action": req.side, "universal_symbol_id": sym.id,
          "order_type": req.order_type, "time_in_force": req.time_in_force}
    # the SDK schema wants floats (an int for units fails its validation)
    for k, v in (("price", req.price), ("stop", req.stop), ("units", req.units), ("notional_value", req.notional)):
        if v is not None:
            kw[k] = float(v)
    return kw


def preview_order(session, req: OrderRequest, clock: Callable[[], float] = time.time) -> Preview:
    """DRY-RUN: validates, resolves the symbol and calls get_order_impact. Places nothing."""
    req = validate_order(req)
    sym = resolve_symbol(session, req.account_id, req.symbol)
    ref = last_price(session, req.account_id, sym.symbol) if estimate_value(req) is None else None
    value = estimate_value(req, ref)
    cad = check_cap(value, sym.currency, session.cfg)

    body = session.read(session.client.trading.get_order_impact, **_impact_kwargs(req, sym))
    trade = (body or {}).get("trade") or {}
    trade_id = trade.get("id")
    if not trade_id:
        raise OrderError("the brokerage preview did not return a trade id; nothing can be placed from it")
    trade_price = None
    try:
        trade_price = float(trade.get("price")) if trade.get("price") is not None else None
    except (TypeError, ValueError):
        pass
    if trade_price and req.units is not None:      # re-check the cap with the brokerage's own price
        value = max(value or 0.0, req.units * trade_price)
        cad = check_cap(value, sym.currency, session.cfg)

    p = Preview(request=req, symbol=sym, trade_id=trade_id, created_at=clock(), estimated_value=value,
                estimated_value_cad=cad, impacts=(body or {}).get("trade_impacts") or [],
                remaining_cash=(body or {}).get("combined_remaining_balance"), trade_price=trade_price)
    session.audit.write("preview", account_id=req.account_id, symbol=sym.symbol, side=req.side,
                        qty=p.quantity_text(), order_type=req.order_type, tif=req.time_in_force,
                        price=req.price, stop=req.stop, est_value=value, est_value_cad=cad,
                        impact=p.impacts, result="ok")
    return p


# ---------------------------------------------------------------- live guard

def require_live_trading_allowed(cfg: Config, live_flag: bool, stdin: Optional[TextIO] = None) -> None:
    """Raise LiveTradingDisabled unless ALL three conditions hold."""
    if not (cfg.live_trading and os.environ.get("LIVE_TRADING") == "true"):
        raise LiveTradingDisabled("LIVE_TRADING is not exactly 'true'. The tool is in dry-run mode.")
    if not live_flag:
        raise LiveTradingDisabled("the --live flag was not given")
    stdin = stdin if stdin is not None else sys.stdin
    if not (hasattr(stdin, "isatty") and stdin.isatty()):
        raise LiveTradingDisabled("stdin is not an interactive terminal; piped or scripted confirmations are refused")


def confirm_interactively(phrase: str, lines: list[str], stdin: Optional[TextIO] = None,
                          stdout: Optional[TextIO] = None) -> bool:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    if not (hasattr(stdin, "isatty") and stdin.isatty()):
        raise LiveTradingDisabled("confirmation needs an interactive terminal")
    for line in lines:
        stdout.write(line + "\n")
    stdout.write(f"\nTo send this LIVE order, type exactly:  {phrase}\n> ")
    stdout.flush()
    answer = stdin.readline()
    return answer.strip() == phrase


def _submit_live_order(session, preview: Preview, live_flag: bool, stdin: Optional[TextIO] = None,
                       clock: Callable[[], float] = time.time) -> Any:
    """The ONLY place a live order is sent. Single attempt, never retried."""
    require_live_trading_allowed(session.cfg, live_flag, stdin)
    if preview.expired(clock()):
        raise PreviewExpired("the preview's trade id has expired; run a new preview")
    session.audit.write("live_place_attempt", account_id=preview.request.account_id,
                        symbol=preview.symbol.symbol, side=preview.request.side, qty=preview.quantity_text(),
                        order_type=preview.request.order_type, result="sending")
    try:
        resp = session.client.trading.place_order(trade_id=preview.trade_id, **session.user_kwargs())
    except Exception as e:
        recent = _recent_orders_safely(session, preview.request.account_id)
        session.audit.write("live_place_uncertain", account_id=preview.request.account_id,
                            symbol=preview.symbol.symbol, error=f"{type(e).__name__}: {getattr(e, 'status', '')}",
                            recent_orders=recent, result="unknown")
        raise LiveOrderUncertain(
            "The place call failed or timed out. It was NOT retried, because Wealthsimple has no "
            "idempotent orders and a retry could duplicate it. Recent orders are in the audit log; "
            "check Wealthsimple before doing anything else.") from None
    return body_of(resp)


def _recent_orders_safely(session, account_id: str) -> list:
    from .read_portfolio import get_recent_orders

    try:
        return [o.__dict__ for o in get_recent_orders(session, account_id, only_executed=False)]
    except Exception as e:  # reconciliation must never raise over the original problem
        return [{"error": f"could not read recent orders: {type(e).__name__}"}]


def place_live(session, req: OrderRequest, live_flag: bool, stdin: Optional[TextIO] = None,
               stdout: Optional[TextIO] = None, clock: Callable[[], float] = time.time,
               max_rounds: int = 3) -> Optional[dict]:
    """Guard, fresh preview, typed confirmation, single submit, reconcile."""
    require_live_trading_allowed(session.cfg, live_flag, stdin)
    for _ in range(max_rounds):
        preview = preview_order(session, req, clock=clock)
        if not confirm_interactively(preview.confirmation_phrase(), preview.summary_lines(clock()), stdin, stdout):
            session.audit.write("live_declined", account_id=req.account_id, symbol=preview.symbol.symbol,
                                side=preview.request.side, qty=preview.quantity_text(), result="not confirmed")
            return None
        if preview.expired(clock()):
            (stdout or sys.stdout).write("Preview expired before confirmation. Getting a fresh one...\n")
            continue
        result = _submit_live_order(session, preview, live_flag, stdin, clock)
        recent = _recent_orders_safely(session, req.account_id)
        session.audit.write("live_placed", account_id=req.account_id, symbol=preview.symbol.symbol,
                            side=preview.request.side, qty=preview.quantity_text(),
                            order_type=preview.request.order_type, result=result, reconciled_recent_orders=recent)
        return {"result": result, "recent_orders": recent}
    raise PreviewExpired("preview kept expiring before confirmation; nothing was placed")


def cancel_order(session, account_id: str, brokerage_order_id: str, live_flag: bool,
                 stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> Optional[dict]:
    """Guarded exactly like a live order. Single attempt, never retried."""
    require_live_trading_allowed(session.cfg, live_flag, stdin)
    phrase = f"CANCEL {brokerage_order_id[-6:]}"
    lines = [f"Account: {mask_id(account_id)}", f"Cancel brokerage order ending ...{brokerage_order_id[-6:]}"]
    if not confirm_interactively(phrase, lines, stdin, stdout):
        session.audit.write("cancel_declined", account_id=account_id, order_id=brokerage_order_id, result="not confirmed")
        return None
    require_live_trading_allowed(session.cfg, live_flag, stdin)
    try:
        resp = session.client.trading.cancel_order(account_id=account_id, brokerage_order_id=brokerage_order_id,
                                                   **session.user_kwargs())
    except Exception as e:
        recent = _recent_orders_safely(session, account_id)
        session.audit.write("cancel_uncertain", account_id=account_id, order_id=brokerage_order_id,
                            error=type(e).__name__, recent_orders=recent, result="unknown")
        raise LiveOrderUncertain("cancel failed or timed out; it was not retried. Check Wealthsimple.") from None
    recent = _recent_orders_safely(session, account_id)
    session.audit.write("cancel_sent", account_id=account_id, order_id=brokerage_order_id,
                        result=body_of(resp), reconciled_recent_orders=recent)
    return {"result": body_of(resp), "recent_orders": recent}
