"""Owner commands by text (or dashboard chat). Identity check: message must come from the
owner's phone number AND start with the PIN. Caller ID can be spoofed, which is why the PIN
is mandatory, and why commands by text can never approve forbidden actions."""
from __future__ import annotations

import hmac

from . import db, policy
from .briefing import build_briefing
from .config import settings
from .memory import normalize_phone

HELP = ("Commands: status | briefing | mode observer|approval|autonomous|emergency | kill | resume | "
        "approve <id> | reject <id> | remember <thing> | done <task id>")


def is_owner_sms(from_number: str | None, body: str) -> bool:
    if not (settings.owner_phone and settings.owner_pin and from_number):
        return False
    if normalize_phone(from_number) != normalize_phone(settings.owner_phone):
        return False
    first = (body or "").strip().split(" ", 1)[0]
    return hmac.compare_digest(first, settings.owner_pin)


def strip_pin(body: str) -> str:
    parts = body.strip().split(" ", 1)
    return parts[1] if len(parts) > 1 else ""


def run(cmd: str, channel: str) -> str:
    from . import outbound  # local import avoids a cycle
    from .memory import remember
    words = cmd.strip().split()
    if not words:
        return HELP
    verb, rest = words[0].lower(), words[1:]
    db.audit(f"owner:{channel}", "command", cmd[:200])

    if verb == "status":
        pend = db.one("SELECT COUNT(*) n FROM actions WHERE status='pending'")["n"]
        crit = db.one("SELECT COUNT(*) n FROM alerts WHERE priority IN ('critical','high') AND status!='acknowledged'")["n"]
        return f"Mode {policy.get_mode()}, kill switch {'ON' if policy.kill_switch_on() else 'off'}, {pend} pending approvals, {crit} open high/critical alerts."
    if verb == "briefing":
        return build_briefing()["text"]
    if verb == "mode" and rest:
        policy.set_mode(rest[0].lower(), f"owner:{channel}")
        return f"Mode set to {rest[0].lower()}."
    if verb == "kill":
        policy.set_kill_switch(True, f"owner:{channel}")
        return "Kill switch ON. Nothing will be sent until you text resume."
    if verb == "resume":
        policy.set_kill_switch(False, f"owner:{channel}")
        return "Kill switch off."
    if verb in ("approve", "reject") and rest and rest[0].isdigit():
        a = db.one("SELECT * FROM actions WHERE id=?", (int(rest[0]),))
        if not a:
            return "No such action."
        if verb == "approve" and a["sensitivity"] == "forbidden" and channel == "sms":
            return "That one is financial/legal. Approve it in the dashboard, not by text."
        return outbound.decide_action(int(rest[0]), verb == "approve", f"owner:{channel}")["message"]
    if verb == "remember" and rest:
        remember("owner", "note", " ".join(rest), "owner", verified=True)
        return "Saved."
    if verb == "done" and rest and rest[0].isdigit():
        db.ex("UPDATE tasks SET status='done', updated_at=? WHERE id=?", (db.now_iso(), int(rest[0])))
        return f"Task {rest[0]} marked done."
    return HELP
