"""Notification router: priority -> channels, quiet hours, duplicate suppression.

critical : push (ntfy priority 5, bypasses iPhone Focus if you allow it) + SMS to owner + dashboard
high     : push now (outside quiet hours), else held for the morning briefing
normal   : next scheduled briefing
low      : archived
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from . import db
from .config import settings
from .policy import get_mode, kill_switch_on

DEDUPE_WINDOW_MIN = 30


def in_quiet_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now(ZoneInfo(settings.timezone))
    t = now.time()
    s, e = settings.quiet_start, settings.quiet_end
    return (t >= s or t < e) if s > e else (s <= t < e)


def _dedupe_key(title: str, interaction_id: int | None) -> str:
    return hashlib.sha256(f"{title}|{interaction_id}".encode()).hexdigest()[:24]


def send_ntfy(title: str, body: str, level: str) -> str:
    if not settings.ntfy_topic:
        return "ntfy:not-configured"
    prio = {"critical": "5", "high": "4", "normal": "3", "low": "2"}[level]
    try:
        r = httpx.post(f"{settings.ntfy_server}/{settings.ntfy_topic}", content=body.encode(),
                       headers={"Title": title[:200], "Priority": prio, "Tags": "rotating_light" if level == "critical" else "bell"},
                       timeout=10)
        return f"ntfy:{r.status_code}"
    except Exception as e:  # noqa: BLE001
        return f"ntfy:error:{e.__class__.__name__}"


def send_owner_sms(body: str) -> str:
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number and settings.owner_phone):
        return "sms:not-configured"
    try:
        r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
                       auth=(settings.twilio_account_sid, settings.twilio_auth_token), timeout=15,
                       data={"From": settings.twilio_from_number, "To": settings.owner_phone, "Body": body[:1500]})
        if r.status_code < 300:
            db.ex("INSERT INTO spend(ts,service,usd,note) VALUES(?,?,?,?)", (db.now_iso(), "twilio_sms", 0.0083, "owner alert"))
        return f"sms:{r.status_code}"
    except Exception as e:  # noqa: BLE001
        return f"sms:error:{e.__class__.__name__}"


def raise_alert(level: str, title: str, body: str, interaction_id: int | None = None,
                now: datetime | None = None) -> dict:
    if get_mode() == "emergency" and level == "high":
        level = "critical"
    key = _dedupe_key(title, interaction_id)
    since = (datetime.now(timezone.utc) - timedelta(minutes=DEDUPE_WINDOW_MIN)).isoformat()
    if db.one("SELECT id FROM alerts WHERE dedupe_key=? AND created_at>=?", (key, since)):
        return {"status": "duplicate_suppressed"}

    log, channels = [], ["dashboard"]
    if level == "low":
        status = "archived"
    elif level == "normal":
        status = "queued_for_briefing"
    elif level == "high" and in_quiet_hours(now):
        status = "queued_for_briefing"
        log.append("held: quiet hours")
    else:
        status = "sent"
        if kill_switch_on():
            log.append("kill switch on: dashboard only")
        else:
            channels.append("push")
            log.append(send_ntfy(title, body, level))
            if level == "critical":
                channels.append("sms")
                log.append(send_owner_sms(f"[CRITICAL] {title}\n{body}"))

    aid = db.ex("""INSERT INTO alerts(priority,title,body,interaction_id,dedupe_key,status,channels,delivery_log,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (level, title, body, interaction_id, key, status, ",".join(channels), "; ".join(log), db.now_iso()))
    db.audit("system", "alert", {"id": aid, "level": level, "status": status, "log": log})
    return {"id": aid, "level": level, "status": status, "channels": channels, "delivery_log": log}
