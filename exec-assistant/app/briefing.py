"""Executive briefing: what happened, why it matters, what was done, what is open, what needs a decision."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import db


def build_briefing(hours: int = 24) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    inter = db.q("""SELECT i.id, i.channel, i.summary, i.priority, i.priority_why, i.occurred_at, c.name contact
                    FROM interactions i LEFT JOIN contacts c ON c.id=i.contact_id
                    WHERE i.created_at>=? ORDER BY CASE i.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2 ELSE 3 END, i.occurred_at DESC""", (since,))
    executed = db.q("SELECT id, action_type, result FROM actions WHERE status='executed' AND created_at>=?", (since,))
    pending = db.q("SELECT id, action_type, sensitivity, reason, payload FROM actions WHERE status='pending' ORDER BY id")
    tasks = db.q("SELECT id, kind, title, due_at FROM tasks WHERE status='open' ORDER BY COALESCE(due_at,'9999'), id LIMIT 25")
    disputed = db.q("SELECT id, subject, attribute, value FROM memories WHERE status='disputed'")

    L = [f"Briefing, last {hours}h"]
    if not inter:
        L.append("Nothing new came in.")
    for level in ("critical", "high", "normal"):
        items = [i for i in inter if i["priority"] == level]
        if items:
            L.append(f"\n{level.upper()} ({len(items)})")
            L += [f"- [{i['channel']}] {i['contact'] or 'unknown'}: {i['summary']}  (why: {i['priority_why']})" for i in items]
    low = sum(1 for i in inter if i["priority"] == "low")
    if low:
        L.append(f"\nArchived {low} low-priority item(s).")
    L.append("\nDONE BY ASSISTANT: " + ("; ".join(f"#{a['id']} {a['action_type']}: {a['result']}" for a in executed) or "nothing sent"))
    L.append("\nNEEDS YOUR DECISION:" if pending else "\nNEEDS YOUR DECISION: none")
    L += [f"- #{p['id']} {p['action_type']} ({p['sensitivity']}): {p['reason']}" for p in pending]
    L.append("\nOPEN TASKS:" if tasks else "\nOPEN TASKS: none")
    L += [f"- #{t['id']} {t['title']}" + (f" (due {t['due_at']})" if t["due_at"] else "") for t in tasks]
    if disputed:
        L.append("\nCONFLICTING INFO TO CONFIRM:")
        L += [f"- memory #{d['id']} {d['subject']} {d['attribute']} = {d['value']}" for d in disputed]
    db.audit("system", "briefing_built", {"items": len(inter)})
    return {"text": "\n".join(L), "interactions": inter, "pending": pending, "tasks": tasks, "disputed": disputed}
