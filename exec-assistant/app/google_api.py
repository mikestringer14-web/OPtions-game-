"""Gmail + Google Calendar over REST with an OAuth refresh token.

STATUS: written against the public Gmail v1 / Calendar v3 REST APIs but NOT live-tested,
because it needs your own Google Cloud OAuth client (see docs/SETUP.md step 4).
Scopes requested: gmail.modify (read, label, draft; sending still goes through approvals)
and calendar.events.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from . import db
from .config import settings
from .ingest import Event, ingest

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3"
SCOPES = "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/calendar.events"


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret and settings.google_refresh_token)


def access_token() -> str:
    r = httpx.post(TOKEN_URL, timeout=15, data={
        "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "refresh_token": settings.google_refresh_token, "grant_type": "refresh_token"})
    r.raise_for_status()
    return r.json()["access_token"]


def poll_gmail(query: str = "is:unread newer_than:1d -category:promotions -category:social", max_results: int = 25) -> dict:
    if not configured():
        return {"status": "blocked", "reason": "Google OAuth not configured"}
    h = {"Authorization": f"Bearer {access_token()}"}
    ids = httpx.get(f"{GMAIL}/messages", headers=h, params={"q": query, "maxResults": max_results}, timeout=20).json()
    done = 0
    for m in ids.get("messages", []):
        msg = httpx.get(f"{GMAIL}/messages/{m['id']}", headers=h, timeout=20,
                        params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]}).json()
        hdr = {x["name"].lower(): x["value"] for x in msg.get("payload", {}).get("headers", [])}
        sender = hdr.get("from", "")
        addr = sender.split("<")[-1].rstrip(">").strip() if "<" in sender else sender
        name = sender.split("<")[0].strip().strip('"') if "<" in sender else ""
        ingest(Event(channel="email", external_id=m["id"], from_addr=addr, name_hint=name,
                     subject=hdr.get("subject", ""), body=msg.get("snippet", "")), actor="poll:gmail")
        done += 1
    db.audit("poll:gmail", "polled", {"count": done})
    return {"status": "ok", "ingested": done}


def upcoming_events(hours: int = 48) -> list[dict]:
    if not configured():
        return []
    h = {"Authorization": f"Bearer {access_token()}"}
    now = datetime.now(timezone.utc)
    r = httpx.get(f"{CAL}/calendars/primary/events", headers=h, timeout=20, params={
        "timeMin": now.isoformat(), "timeMax": (now + timedelta(hours=hours)).isoformat(),
        "singleEvents": "true", "orderBy": "startTime"})
    r.raise_for_status()
    return r.json().get("items", [])


def find_conflicts(events: list[dict], start: datetime, end: datetime, buffer_min: int = 30) -> list[dict]:
    """Pure function (tested). Treats travel/prep buffer as busy time."""
    out = []
    b = timedelta(minutes=buffer_min)
    for e in events:
        s = e.get("start", {}).get("dateTime")
        f = e.get("end", {}).get("dateTime")
        if not s or not f:
            continue
        es, ef = datetime.fromisoformat(s), datetime.fromisoformat(f)
        if es - b < end and start < ef + b:
            out.append({"summary": e.get("summary", "(busy)"), "start": s, "end": f})
    return out
