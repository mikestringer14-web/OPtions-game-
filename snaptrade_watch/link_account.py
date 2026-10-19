"""Register (commercial only), generate the Connection Portal link, and review connections."""
from __future__ import annotations

from typing import Optional

from .config import mask_id
from .read_portfolio import Connection, disabled_connection_warnings, list_connections
from .secrets_store import write_user_secret

PORTAL_TTL_NOTE = "This link expires in 5 minutes. Open it now; if it times out (error 1006), run link again."
CONNECTION_TYPES = {"read", "trade", "trade-if-available"}


class LinkError(Exception):
    pass


def register(session) -> str:
    """Commercial mode only. Idempotent: does nothing if the secret file already exists."""
    cfg = session.cfg
    if cfg.auth_mode != "commercial":
        raise LinkError("register is only for commercial mode. Personal API keys do not register users.")
    if cfg.user_secret_file.exists():
        return f"Already registered: a userSecret file exists at {cfg.user_secret_file}. Skipping."
    resp = session.client.authentication.register_snap_trade_user(user_id=cfg.user_id)
    from .client import body_of

    body = body_of(resp) or {}
    secret = body.get("userSecret")
    if not secret:
        raise LinkError("SnapTrade did not return a userSecret")
    write_user_secret(cfg.user_secret_file, secret)
    session.audit.write("register", user_id=cfg.user_id, result="secret stored (0600)")
    return f"Registered user {mask_id(cfg.user_id)}. userSecret saved to {cfg.user_secret_file} (0600). It was not printed."


def known_broker_slugs(session) -> set[str]:
    body = session.read(session.client.reference_data.list_all_brokerages, user_scoped=False)
    return {str(b.get("slug")) for b in (body or []) if b.get("slug")}


def portal_url(session, connection_type: str = "read", broker: Optional[str] = None,
               reconnect: Optional[str] = None, verify_broker: bool = True) -> str:
    if connection_type not in CONNECTION_TYPES:
        raise LinkError(f"connection_type must be one of {sorted(CONNECTION_TYPES)}")
    if broker and verify_broker and broker != "SANDBOX":
        slugs = known_broker_slugs(session)
        if broker not in slugs:
            close = sorted(s for s in slugs if broker[:6].lower() in s.lower())
            raise LinkError(f"broker slug {broker!r} not found in SnapTrade's brokerage list. Close matches: {close}")
    kw = {"connection_type": connection_type}
    if broker:
        kw["broker"] = broker
    if reconnect:
        kw["reconnect"] = reconnect
    body = session.read(session.client.authentication.login_snap_trade_user, **kw)
    url = (body or {}).get("redirectURI")
    if not url:
        raise LinkError("SnapTrade did not return a redirectURI")
    session.audit.write("portal_link", connection_type=connection_type, broker=broker,
                        reconnect=bool(reconnect), result="link generated")
    return url


def connections_report(session) -> tuple[list[Connection], list[str]]:
    conns = list_connections(session)
    return conns, disabled_connection_warnings(conns)
