"""Authority and permission system.

Modes
  observer   : monitor, organise, notify. Never sends anything.
  approval   : drafts go to the approval queue. Owner taps approve.
  autonomous : routine, pre-authorised actions run; everything else queues.
  emergency  : like approval, plus every high alert escalates as critical.

Hard limits that NO mode can override (owner must do these personally or approve each one):
  financial transactions, contracts / legally binding agreements, sharing confidential info,
  employment or legal decisions. These are 'forbidden' for automation and always queue.
"""
from __future__ import annotations

import json
import os
import re

from . import db
from .config import settings

MODES = ("observer", "approval", "autonomous", "emergency")

FORBIDDEN_PATTERNS = [
    r"\b(pay|payment|e-?transfer|wire|send money|\$\d+|credit card|bank)\b",
    r"\b(sign|contract|agree to|accept the offer|settlement|waive|release form)\b",
    r"\b(sin|social insurance|password|passcode|health card|account number)\b",
    r"\b(resign|quit|accept the job|decline the job|plead|withdraw (the|my) (claim|complaint|application))\b",
]
SENSITIVE_PATTERNS = [
    r"\b(hrto|tribunal|lawyer|legal|hr|odsp|doctor|medical|landlord|lease|employer|manager)\b",
]
# Personal names/organisations that make a message sensitive. Kept out of the code on purpose:
# set EA_SENSITIVE_KEYWORDS="name one,name two,company" in your private .env.
_extra = [k.strip() for k in os.environ.get("EA_SENSITIVE_KEYWORDS", "").split(",") if k.strip()]
if _extra:
    SENSITIVE_PATTERNS.append(r"\b(" + "|".join(re.escape(k) for k in _extra) + r")\b")
# Actions that may run alone in autonomous mode, and only these.
ROUTINE_ACTIONS = {"ack_message", "send_holding_reply"}


def get_mode() -> str:
    return db.get_setting("mode", settings.default_mode)


def set_mode(mode: str, actor: str = "owner") -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    db.set_setting("mode", mode)
    db.audit(actor, "mode_changed", {"mode": mode})


def kill_switch_on() -> bool:
    return db.get_setting("kill_switch", "off") == "on"


def set_kill_switch(on: bool, actor: str = "owner") -> None:
    db.set_setting("kill_switch", "on" if on else "off")
    db.audit(actor, "kill_switch", {"on": on})


def sensitivity(action_type: str, payload: dict) -> str:
    text = json.dumps(payload).lower()
    if any(re.search(p, text, re.I) for p in FORBIDDEN_PATTERNS):
        return "forbidden"
    if any(re.search(p, text, re.I) for p in SENSITIVE_PATTERNS):
        return "sensitive"
    return "routine" if action_type in ROUTINE_ACTIONS else "sensitive"


def decide(action_type: str, payload: dict) -> dict:
    """Return {'decision': execute|queue|block, 'sensitivity':..., 'reason':...}."""
    sens = sensitivity(action_type, payload)
    mode = get_mode()
    if kill_switch_on():
        return {"decision": "block", "sensitivity": sens, "reason": "kill switch is ON"}
    if mode == "observer":
        return {"decision": "block", "sensitivity": sens, "reason": "observer mode never sends"}
    if sens == "forbidden":
        return {"decision": "queue", "sensitivity": sens, "reason": "financial/legal/contract/confidential: needs your explicit approval"}
    if mode == "autonomous" and sens == "routine":
        return {"decision": "execute", "sensitivity": sens, "reason": "routine action pre-authorised in autonomous mode"}
    return {"decision": "queue", "sensitivity": sens, "reason": f"{mode} mode: waiting for your approval"}


def propose(action_type: str, payload: dict, actor: str = "system") -> dict:
    d = decide(action_type, payload)
    status = {"execute": "approved", "queue": "pending", "block": "blocked"}[d["decision"]]
    aid = db.ex("""INSERT INTO actions(action_type,payload,sensitivity,status,reason,created_at)
                   VALUES(?,?,?,?,?,?)""", (action_type, json.dumps(payload), d["sensitivity"], status, d["reason"], db.now_iso()))
    db.audit(actor, "action_proposed", {"id": aid, "type": action_type, **d})
    return {"id": aid, "status": status, **d}
