"""Execute approved actions. Every send is policy-checked twice: when proposed and right before sending."""
from __future__ import annotations

import json

import httpx

from . import db, policy
from .config import settings


def _send_sms(to: str, body: str) -> str:
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
        return "SIMULATED (Twilio not configured): nothing was actually sent"
    r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
                   auth=(settings.twilio_account_sid, settings.twilio_auth_token), timeout=15,
                   data={"From": settings.twilio_from_number, "To": to, "Body": body[:1500]})
    r.raise_for_status()
    db.ex("INSERT INTO spend(ts,service,usd,note) VALUES(?,?,?,?)", (db.now_iso(), "twilio_sms", 0.0083, to[-4:]))
    return f"sent sid={r.json().get('sid', '?')}"


EXECUTORS = {
    "send_sms": lambda p: _send_sms(p["to"], p["body"]),
    "send_holding_reply": lambda p: _send_sms(p["to"], p["body"]),
    "ack_message": lambda p: "acknowledged",
    # send_email / create_event run through google_api.py once Google OAuth is configured.
}


def execute(action_id: int, actor: str) -> dict:
    a = db.one("SELECT * FROM actions WHERE id=?", (action_id,))
    if policy.kill_switch_on() or policy.get_mode() == "observer":
        db.ex("UPDATE actions SET status='blocked', result=? WHERE id=?", ("blocked at send time", action_id))
        return {"status": "blocked", "message": "Blocked: kill switch on or observer mode."}
    fn = EXECUTORS.get(a["action_type"])
    if not fn:
        db.ex("UPDATE actions SET status='failed', result=? WHERE id=?", ("no executor for this action type yet", action_id))
        return {"status": "failed", "message": f"No executor for {a['action_type']} yet."}
    try:
        result = fn(json.loads(a["payload"]))
        db.ex("UPDATE actions SET status='executed', result=? WHERE id=?", (result, action_id))
        db.audit(actor, "action_executed", {"id": action_id, "result": result})
        return {"status": "executed", "message": f"Action {action_id}: {result}"}
    except Exception as e:  # noqa: BLE001
        db.ex("UPDATE actions SET status='failed', result=? WHERE id=?", (str(e)[:300], action_id))
        db.audit(actor, "action_failed", {"id": action_id, "error": str(e)[:300]})
        return {"status": "failed", "message": f"Action {action_id} failed: {e}"}


def decide_action(action_id: int, approve: bool, actor: str) -> dict:
    a = db.one("SELECT * FROM actions WHERE id=?", (action_id,))
    if not a or a["status"] != "pending":
        return {"status": "noop", "message": "Not pending."}
    db.ex("UPDATE actions SET status=?, decided_at=? WHERE id=?", ("approved" if approve else "rejected", db.now_iso(), action_id))
    db.audit(actor, "action_approved" if approve else "action_rejected", {"id": action_id})
    if not approve:
        return {"status": "rejected", "message": f"Action {action_id} rejected."}
    return execute(action_id, actor)


def propose_and_maybe_run(action_type: str, payload: dict, actor: str = "system") -> dict:
    p = policy.propose(action_type, payload, actor)
    if p["status"] == "approved":
        p["execution"] = execute(p["id"], actor)
    return p
