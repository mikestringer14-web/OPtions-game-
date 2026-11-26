"""Permanent memory: contacts, interactions, facts (with contradiction detection), tasks, search."""
from __future__ import annotations

import re
from typing import Any

from . import db


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits if digits else None


# ---------- contacts ----------
def find_contact(phone: str | None = None, email: str | None = None) -> dict | None:
    phone = normalize_phone(phone)
    if phone:
        c = db.one("SELECT * FROM contacts WHERE phone=?", (phone,))
        if c:
            return c
    if email:
        return db.one("SELECT * FROM contacts WHERE lower(email)=lower(?)", (email,))
    return None


def upsert_contact(name: str, phone: str | None = None, email: str | None = None,
                   relationship: str | None = None, tier: str | None = None, notes: str | None = None) -> dict:
    phone = normalize_phone(phone)
    existing = find_contact(phone, email)
    now = db.now_iso()
    if existing:
        db.ex("""UPDATE contacts SET name=COALESCE(?,name), phone=COALESCE(?,phone), email=COALESCE(?,email),
                 relationship=COALESCE(?,relationship), tier=COALESCE(?,tier), notes=COALESCE(?,notes), updated_at=?
                 WHERE id=?""",
              # Only replace a placeholder name; never let a caller rename a known contact.
              (name if name and existing["name"].startswith("Unknown") else None,
               phone, email, relationship, tier, notes, now, existing["id"]))
        return db.one("SELECT * FROM contacts WHERE id=?", (existing["id"],))
    cid = db.ex("""INSERT INTO contacts(name,phone,email,relationship,tier,notes,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (name or f"Unknown {phone or email}", phone, email, relationship or "unknown",
                 tier or "normal", notes or "", now, now))
    return db.one("SELECT * FROM contacts WHERE id=?", (cid,))


def contact_history(contact_id: int, limit: int = 5) -> list[dict]:
    return db.q("""SELECT id, channel, direction, summary, priority, occurred_at FROM interactions
                   WHERE contact_id=? ORDER BY occurred_at DESC LIMIT ?""", (contact_id, limit))


# ---------- interactions ----------
def add_interaction(**kw: Any) -> tuple[int, bool]:
    """Returns (id, created). Duplicate provider ids (webhook retries) are not stored twice."""
    if kw.get("external_id"):
        dup = db.one("SELECT id FROM interactions WHERE channel=? AND external_id=?", (kw["channel"], kw["external_id"]))
        if dup:
            return dup["id"], False
    cols = ["channel", "direction", "external_id", "contact_id", "from_addr", "to_addr", "subject", "body",
            "summary", "priority", "priority_why", "injection_flag", "occurred_at"]
    vals = [kw.get(c, "" if c in ("subject", "body", "summary", "priority_why") else None) for c in cols]
    vals[cols.index("priority")] = kw.get("priority", "normal")
    vals[cols.index("injection_flag")] = int(bool(kw.get("injection_flag")))
    vals[cols.index("occurred_at")] = kw.get("occurred_at") or db.now_iso()
    iid = db.ex(f"INSERT INTO interactions({','.join(cols)},created_at) VALUES({','.join('?' * len(cols))},?)",
                vals + [db.now_iso()])
    return iid, True


# ---------- facts ----------
def remember(subject: str, attribute: str, value: str, source_type: str, source_id: int | None = None,
             verified: bool = False, confidence: float = 0.6) -> dict:
    """Store a fact. If the slot already holds a different active value, flag a contradiction
    instead of silently overwriting. Owner-verified facts supersede unverified ones."""
    value = str(value).strip()
    now = db.now_iso()
    current = db.q("SELECT * FROM memories WHERE subject=? AND attribute=? AND status IN ('active','disputed')",
                   (subject, attribute))
    for c in current:
        if c["value"].strip().lower() == value.lower():
            if verified:  # owner confirmed this value: it wins, the rest are superseded
                db.ex("UPDATE memories SET verified=1, confidence=1.0, status='active', updated_at=? WHERE id=?", (now, c["id"]))
                for o in current:
                    if o["id"] != c["id"]:
                        db.ex("UPDATE memories SET status='superseded', superseded_by=?, updated_at=? WHERE id=?", (c["id"], now, o["id"]))
                return {"id": c["id"], "result": "confirmed"}
            db.ex("UPDATE memories SET confidence=MIN(1.0, confidence+0.1), updated_at=? WHERE id=?", (now, c["id"]))
            return {"id": c["id"], "result": "reinforced"}

    mid = db.ex("""INSERT INTO memories(subject,attribute,value,status,verified,confidence,source_type,source_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (subject, attribute, value, "active", int(verified), 1.0 if verified else confidence,
                 source_type, source_id, now, now))
    if not current:
        return {"id": mid, "result": "new"}
    if verified:
        for c in current:
            db.ex("UPDATE memories SET status='superseded', superseded_by=?, updated_at=? WHERE id=?", (mid, now, c["id"]))
        return {"id": mid, "result": "superseded_old", "old": [c["value"] for c in current]}
    if any(c["verified"] for c in current):
        db.ex("UPDATE memories SET status='disputed', updated_at=? WHERE id=?", (now, mid))
    else:
        for c in current:
            db.ex("UPDATE memories SET status='disputed', updated_at=? WHERE id=?", (now, c["id"]))
        db.ex("UPDATE memories SET status='disputed', updated_at=? WHERE id=?", (now, mid))
    return {"id": mid, "result": "contradiction", "old": [c["value"] for c in current]}


def edit_memory(mid: int, value: str | None = None, verified: bool | None = None, status: str | None = None) -> dict | None:
    db.ex("UPDATE memories SET value=COALESCE(?,value), verified=COALESCE(?,verified), status=COALESCE(?,status), updated_at=? WHERE id=?",
          (value, None if verified is None else int(verified), status, db.now_iso(), mid))
    return db.one("SELECT * FROM memories WHERE id=?", (mid,))


def forget(mid: int) -> None:
    """Hard delete (owner right to erase)."""
    db.ex("DELETE FROM memories WHERE id=?", (mid,))


def facts_about(subject: str) -> list[dict]:
    return db.q("SELECT * FROM memories WHERE subject=? AND status IN ('active','disputed') ORDER BY attribute", (subject,))


# ---------- tasks ----------
def add_task(title: str, kind: str = "task", details: str = "", owed_by: str = "owner",
             contact_id: int | None = None, due_at: str | None = None, source_id: int | None = None) -> int:
    dup = db.one("SELECT id FROM tasks WHERE title=? AND status='open' AND IFNULL(source_id,0)=IFNULL(?,0)", (title, source_id))
    if dup:
        return dup["id"]
    now = db.now_iso()
    return db.ex("""INSERT INTO tasks(kind,title,details,owed_by,contact_id,due_at,status,source_id,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,'open',?,?,?)""", (kind, title, details, owed_by, contact_id, due_at, source_id, now, now))


# ---------- search ----------
def _fts_query(text: str) -> str:
    words = re.findall(r"\w+", text)
    return " OR ".join(f'"{w}"' for w in words) or '""'


def search(text: str, limit: int = 20) -> dict:
    fq = _fts_query(text)
    inter = db.q("""SELECT i.id, i.channel, i.summary, i.priority, i.occurred_at, c.name AS contact
                    FROM interactions_fts f JOIN interactions i ON i.id=f.rowid LEFT JOIN contacts c ON c.id=i.contact_id
                    WHERE interactions_fts MATCH ? ORDER BY bm25(interactions_fts) LIMIT ?""", (fq, limit))
    mems = db.q("""SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid
                   WHERE memories_fts MATCH ? AND m.status!='deleted' ORDER BY bm25(memories_fts) LIMIT ?""", (fq, limit))
    contacts = db.q("SELECT * FROM contacts WHERE name LIKE ? OR phone LIKE ? OR email LIKE ? LIMIT ?",
                    (f"%{text}%", f"%{text}%", f"%{text}%", limit))
    return {"interactions": inter, "memories": mems, "contacts": contacts}
