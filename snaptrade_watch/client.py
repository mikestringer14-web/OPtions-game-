"""SnapTrade client construction, user kwargs, response conversion and 429 backoff."""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional

from .config import Config
from .secrets_store import read_user_secret

MAX_TRIES = 5
ACCOUNT_MIN_INTERVAL_S = 6.0   # 10 requests/min per account on Personal keys


def build_client(cfg: Config):
    from snaptrade_client import SnapTrade, SnapTradeAuth

    if cfg.auth_mode == "personal":
        auth = SnapTradeAuth.personal_api_key(client_id=cfg.client_id, consumer_key=cfg.consumer_key)
    else:
        auth = SnapTradeAuth.commercial_api_key(client_id=cfg.client_id, consumer_key=cfg.consumer_key)
    return SnapTrade(auth=auth)


def user_kwargs(cfg: Config, reader: Callable = read_user_secret) -> dict:
    """{} for Personal keys; {user_id, user_secret} for Commercial keys."""
    if cfg.auth_mode == "personal":
        return {}
    return {"user_id": cfg.user_id, "user_secret": reader(cfg.user_secret_file)}


def plain(obj: Any) -> Any:
    """Convert SDK schema objects (frozendict/Decimal/str/Bool subclasses) to plain Python."""
    try:
        from snaptrade_client.schemas import BoolClass, NoneClass
    except ImportError:  # pragma: no cover
        BoolClass = NoneClass = ()  # type: ignore
    if obj is None or (NoneClass and isinstance(obj, NoneClass)):
        return None
    if BoolClass and isinstance(obj, BoolClass):
        return bool(obj)
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, Mapping):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, str):
        return str(obj)
    if isinstance(obj, (int, float)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def body_of(response: Any) -> Any:
    return plain(getattr(response, "body", response))


class AccountRateLimiter:
    """Keeps calls for one account at least `interval` seconds apart."""

    def __init__(self, interval: float = ACCOUNT_MIN_INTERVAL_S, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: Optional[str]) -> None:
        if not key:
            return
        with self._lock:
            now = self.clock()
            last = self._last.get(key)
            delay = 0.0 if last is None else max(0.0, last + self.interval - now)
            self._last[key] = now + delay
        if delay > 0:
            self.sleep(delay)


def _header(headers: Any, name: str) -> Optional[str]:
    if not headers:
        return None
    try:
        items = headers.items()
    except AttributeError:
        return None
    for k, v in items:
        if str(k).lower() == name.lower():
            return str(v)
    return None


def retry_delay(headers: Any, attempt: int, rand: Callable[[float, float], float] = random.uniform) -> float:
    """Reset headers first, then Retry-After, then exponential backoff with jitter."""
    for name in ("X-RateLimit-Account-Reset", "X-RateLimit-Reset", "Retry-After"):
        raw = _header(headers, name)
        if raw:
            try:
                return max(0.0, float(raw)) + rand(0, 0.5)
            except ValueError:
                pass
    return min(60.0, 2.0 ** attempt) + rand(0, 1.0)


def call_with_backoff(fn: Callable, *args: Any, rate_key: Optional[str] = None,
                      limiter: Optional[AccountRateLimiter] = None, max_tries: int = MAX_TRIES,
                      sleep: Callable[[float], None] = time.sleep, **kwargs: Any) -> Any:
    """Retry READ calls on 429. Never use this for live order placement."""
    from snaptrade_client import ApiException

    key = rate_key or kwargs.get("account_id")
    for attempt in range(max_tries):
        if limiter:
            limiter.wait(key)
        try:
            return fn(*args, **kwargs)
        except ApiException as e:
            if getattr(e, "status", None) != 429 or attempt == max_tries - 1:
                raise
            sleep(retry_delay(getattr(e, "headers", None), attempt))
    raise RuntimeError("unreachable")  # pragma: no cover


@dataclass
class Session:
    """Everything a command needs: config, SDK client, rate limiter, audit log."""

    cfg: Config
    client: Any
    audit: Any
    limiter: AccountRateLimiter = field(default_factory=AccountRateLimiter)
    secret_reader: Callable = read_user_secret
    _ukw: Optional[dict] = field(default=None, repr=False)

    def user_kwargs(self) -> dict:
        if self._ukw is None:
            self._ukw = user_kwargs(self.cfg, self.secret_reader)
        return dict(self._ukw)

    def read(self, fn: Callable, user_scoped: bool = True, **kwargs: Any) -> Any:
        """Call a read endpoint with user kwargs, rate limiting and 429 backoff; return plain data."""
        extra = self.user_kwargs() if user_scoped else {}
        return body_of(call_with_backoff(fn, limiter=self.limiter, **kwargs, **extra))
