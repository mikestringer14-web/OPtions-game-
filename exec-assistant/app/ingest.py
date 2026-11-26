"""One pipeline for every channel: call, SMS, email, room speaker.

  receive -> scan for injection/scam -> identify contact -> retrieve history -> prioritise
  -> summarise -> store -> extract facts and follow-ups -> alert -> audit
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import db, memory
from .guard import scan
from .llm import extract_followups, summarize
from .notify import raise_alert
from .priority import classify


@dataclass
class Event:
    channel: str                    # call | sms | email | voice_room
    body: str
    direction: str = "inbound"
    external_id: str | None = None
    from_addr: str | None = None    # phone or email
    to_addr: str | None = None
    name_hint: str | None = None    # name the caller gave
    subject: str = ""
    fields: dict = field(default_factory=dict)   # structured data from the voice agent
    provider_summary: str | None = None
    stated_urgency: str | None = None
    occurred_at: str | None = None
    scan_text: str | None = None    # third-party text only (e.g. caller turns); defaults to body


def ingest(ev: Event, actor: str = "webhook") -> dict:
    third_party = ev.scan_text if ev.scan_text is not None else ev.body
    flags = scan(f"{ev.subject}\n{third_party}")

    is_email = bool(ev.from_addr and "@" in ev.from_addr)
    phone = None if is_email else ev.from_addr
    email = ev.from_addr if is_email else None
    contact = memory.find_contact(phone, email)
    if not contact and ev.from_addr:
        contact = memory.upsert_contact(ev.name_hint or "", phone=phone, email=email)
    elif contact and ev.name_hint and contact["name"].startswith("Unknown"):
        contact = memory.upsert_contact(ev.name_hint, phone=phone, email=email)
    history = memory.contact_history(contact["id"], 3) if contact else []

    verdict = classify(f"{ev.subject}\n{third_party}\n{ev.fields.get('reason_for_call', '')}",
                       contact, ev.stated_urgency or ev.fields.get("urgency_level"), flags["scam"])
    summary = summarize(ev.body, f"{ev.channel}:{ev.from_addr}", ev.fields, ev.provider_summary)

    iid, created = memory.add_interaction(
        channel=ev.channel, direction=ev.direction, external_id=ev.external_id,
        contact_id=contact["id"] if contact else None, from_addr=ev.from_addr, to_addr=ev.to_addr,
        subject=ev.subject, body=ev.body, summary=summary, priority=verdict.level,
        priority_why="; ".join(verdict.reasons), injection_flag=flags["injection"] or flags["scam"],
        occurred_at=ev.occurred_at)
    if not created:
        db.audit(actor, "duplicate_event_ignored", {"interaction_id": iid, "external_id": ev.external_id})
        return {"interaction_id": iid, "duplicate": True}

    # Facts. Extracted from third parties = unverified, moderate confidence.
    fact_notes = []
    if contact:
        subj = f"contact:{contact['id']}"
        for attr in ("callback_number", "best_callback_time"):
            if ev.fields.get(attr):
                r = memory.remember(subj, attr, ev.fields[attr], ev.channel, iid, confidence=0.6)
                if r["result"] == "contradiction":
                    fact_notes.append(f"Note: {attr} differs from what we had ({', '.join(r['old'])}).")

    tasks = []
    who = contact["name"] if contact else (ev.from_addr or "unknown")
    if ev.channel == "call" and verdict.level != "low":
        tasks.append(memory.add_task(f"Call back {who}", "follow_up",
                                     ev.fields.get("reason_for_call", summary), "owner",
                                     contact["id"] if contact else None, None, iid))
    if verdict.level != "low" and not flags["scam"]:
        for f in extract_followups(third_party):
            tasks.append(memory.add_task(f["title"], f["kind"], "", "owner",
                                         contact["id"] if contact else None, None, iid))

    title = f"{ev.channel.upper()} from {who}"
    lines = [summary]
    if flags["injection"]:
        lines.append("Warning: this message tried to give the assistant instructions. Nothing was done.")
    if flags["scam"]:
        lines.append("Warning: looks like a scam or phishing attempt. Do not reply with personal info.")
    lines += fact_notes
    if history:
        lines.append(f"Last contact: {history[0]['occurred_at'][:10]} ({history[0]['channel']}) {history[0]['summary'][:80]}")
    lines.append(f"Priority {verdict.level}: {', '.join(verdict.reasons)}")
    alert = raise_alert(verdict.level, title, "\n".join(lines), iid)

    db.audit(actor, "ingested", {"interaction_id": iid, "channel": ev.channel, "priority": verdict.level})
    return {"interaction_id": iid, "contact": contact, "priority": verdict.level, "reasons": verdict.reasons,
            "summary": summary, "tasks": tasks, "alert": alert, "flags": flags, "history_used": history}
