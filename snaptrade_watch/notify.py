"""Optional Telegram notifier. A no-op unless TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from .config import Config, redact

log = logging.getLogger("snaptrade_watch.notify")
API = "https://api.telegram.org/bot{token}/sendMessage"


def send(text: str, cfg: Optional[Config], post: Optional[Callable] = None) -> bool:
    token = cfg.telegram_bot_token if cfg else None
    chat = cfg.telegram_chat_id if cfg else None
    if not token or not chat:
        log.info("telegram disabled")
        return False
    if post is None:
        import requests

        post = requests.post
    safe = redact(text, cfg.secrets())[:4000]
    try:
        r = post(API.format(token=token), json={"chat_id": chat, "text": safe}, timeout=10)
        ok = getattr(r, "status_code", 0) == 200
        if not ok:
            log.warning("telegram send failed: HTTP %s", getattr(r, "status_code", "?"))
        return ok
    except Exception as e:  # the exception text can contain the URL, which contains the token
        log.warning("telegram send failed: %s", redact(f"{type(e).__name__}: {e}", cfg.secrets()))
        return False
