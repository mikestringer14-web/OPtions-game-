"""Environment loading, mode parsing, limits and redaction helpers."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional

DEFAULT_SECRET_FILE = "~/.config/snaptrade-watch/user_secret"
DEFAULT_LOG_FILE = "./logs/snaptrade.jsonl"


class ConfigError(Exception):
    """Missing or invalid configuration."""


def parse_live_trading(value: Optional[str]) -> bool:
    """Only the exact string "true" enables live trading. Everything else is dry-run."""
    return value == "true"


@dataclass(frozen=True)
class Config:
    client_id: str
    consumer_key: str = field(repr=False)
    auth_mode: str = "personal"
    user_id: Optional[str] = None
    user_secret_file: Path = Path(DEFAULT_SECRET_FILE).expanduser()
    live_trading: bool = False
    max_order_value_cad: float = 500.0
    usd_cad_cap_rate: float = 1.5
    log_file: Path = Path(DEFAULT_LOG_FILE)
    telegram_bot_token: Optional[str] = field(default=None, repr=False)
    telegram_chat_id: Optional[str] = None

    @property
    def mode_label(self) -> str:
        return "LIVE-ENABLED" if self.live_trading else "DRY-RUN"

    def secrets(self) -> list[str]:
        """Values that must never appear in output or logs."""
        return [s for s in (self.consumer_key, self.telegram_bot_token) if s]


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw in (None, ""):
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


def load_config(env: Optional[Mapping[str, str]] = None, load_dotenv_file: bool = True) -> Config:
    if env is None:
        if load_dotenv_file:
            try:
                from dotenv import load_dotenv

                load_dotenv(override=False)
            except ImportError:  # pragma: no cover - dependency is declared
                pass
        env = os.environ

    client_id = env.get("SNAPTRADE_CLIENT_ID", "").strip()
    consumer_key = env.get("SNAPTRADE_CONSUMER_KEY", "").strip()
    if not client_id or not consumer_key:
        raise ConfigError("SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY must be set (see .env.example)")

    mode = (env.get("SNAPTRADE_AUTH_MODE") or "personal").strip().lower()
    if mode not in ("personal", "commercial"):
        raise ConfigError("SNAPTRADE_AUTH_MODE must be 'personal' or 'commercial'")

    user_id = (env.get("SNAPTRADE_USER_ID") or "").strip() or None
    if mode == "commercial":
        if not user_id:
            raise ConfigError("SNAPTRADE_USER_ID is required in commercial mode (a stable id, not an email)")
        if "@" in user_id:
            raise ConfigError("SNAPTRADE_USER_ID must not be an email address; use something like 'mike-local-1'")

    return Config(
        client_id=client_id,
        consumer_key=consumer_key,
        auth_mode=mode,
        user_id=user_id if mode == "commercial" else None,
        user_secret_file=Path(env.get("SNAPTRADE_USER_SECRET_FILE") or DEFAULT_SECRET_FILE).expanduser(),
        live_trading=parse_live_trading(env.get("LIVE_TRADING")),
        max_order_value_cad=_float(env, "MAX_ORDER_VALUE_CAD", 500.0),
        usd_cad_cap_rate=_float(env, "CAP_USD_CAD_RATE", 1.5),
        log_file=Path(env.get("LOG_FILE") or DEFAULT_LOG_FILE),
        telegram_bot_token=(env.get("TELEGRAM_BOT_TOKEN") or "").strip() or None,
        telegram_chat_id=(env.get("TELEGRAM_CHAT_ID") or "").strip() or None,
    )


# ---------------------------------------------------------------- redaction

_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_LONG_DIGITS = re.compile(r"(?<![\w.])\d{6,}(?![\w.])")
_TELEGRAM_TOKEN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")


def mask_id(value: Optional[str], keep: int = 4) -> str:
    """'a1b2c3d4-...-9f8e' -> '****9f8e'. Never returns more than `keep` real characters."""
    if not value:
        return ""
    s = str(value)
    return "****" + s[-keep:] if len(s) > keep else "****"


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove secrets, and mask UUIDs and long digit runs (account numbers) to the last 4 chars."""
    out = str(text)
    for s in sorted({s for s in secrets if s}, key=len, reverse=True):
        out = out.replace(s, "***")
    out = _TELEGRAM_TOKEN.sub("***", out)
    out = _UUID.sub(lambda m: mask_id(m.group(0)), out)
    out = _LONG_DIGITS.sub(lambda m: mask_id(m.group(0)), out)
    return out
