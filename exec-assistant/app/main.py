"""FastAPI app: owner API + dashboard + provider webhooks."""
from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import commands, db, memory, outbound, policy, priority
from .briefing import build_briefing
from .config import settings
from .ingest import Event, ingest
from .signatures import verify_elevenlabs, verify_twilio

@asynccontextmanager
async def lifespan(_app):
    db.connect()
    yield


app = FastAPI(title="Executive Assistant", version="0.1.0", lifespan=lifespan)
DASHBOARD = Path(__file__).parent / "static" / "dashboard.html"


# ---------------- auth ----------------
def require_owner(authorization: str = Header(default="")) -> str:
    tok = settings.admin_token
    if not tok or tok == "change-me" or len(tok) < 16:
        raise HTTPException(503, "Set EA_ADMIN_TOKEN (16+ chars) before using the API.")
    given = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given, tok):
        db.audit("unknown", "auth_failed", {})
        raise HTTPException(401, "bad token")
    return "owner"


def twiml(msg: str | None = None) -> Response:
    inner = f"<Message>{escape(msg)}</Message>" if msg else ""
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>', media_type="application/xml")


# ---------------- public ----------------
@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD.read_text()


@app.get("/health")
def health() -> dict:
    db.one("SELECT 1 AS ok")
    return {"ok": True, "mode": policy.get_mode(), "kill_switch": policy.kill_switch_on()}


# ---------------- owner API ----------------
@app.get("/api/state")
def state(_: str = Depends(require_owner)) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return {
        "mode": policy.get_mode(), "kill_switch": policy.kill_switch_on(),
        "integrations": settings.integration_status(),
        "counts": {
            "pending_approvals": db.one("SELECT COUNT(*) n FROM actions WHERE status='pending'")["n"],
            "open_alerts": db.one("SELECT COUNT(*) n FROM alerts WHERE status IN ('sent','new','queued_for_briefing')")["n"],
            "open_tasks": db.one("SELECT COUNT(*) n FROM tasks WHERE status='open'")["n"],
            "interactions_24h": db.one("SELECT COUNT(*) n FROM interactions WHERE created_at>=?", (since,))["n"],
        },
        "spend_usd": {
            "today": round(db.one("SELECT COALESCE(SUM(usd),0) s FROM spend WHERE ts>=?", (since,))["s"], 4),
            "month": round(db.one("SELECT COALESCE(SUM(usd),0) s FROM spend WHERE ts LIKE ?", (month + "%",))["s"], 4),
            "daily_limit": settings.daily_spend_limit_usd},
    }


@app.get("/api/inbox")
def inbox(limit: int = 50, channel: str | None = None, _: str = Depends(require_owner)) -> list[dict]:
    sql = """SELECT i.id,i.channel,i.direction,i.from_addr,i.subject,i.summary,i.priority,i.priority_why,
             i.injection_flag,i.occurred_at,c.name contact FROM interactions i LEFT JOIN contacts c ON c.id=i.contact_id"""
    if channel:
        return db.q(sql + " WHERE i.channel=? ORDER BY i.occurred_at DESC LIMIT ?", (channel, limit))
    return db.q(sql + " ORDER BY i.occurred_at DESC LIMIT ?", (limit,))


@app.get("/api/interactions/{iid}")
def interaction(iid: int, _: str = Depends(require_owner)) -> dict:
    row = db.one("SELECT * FROM interactions WHERE id=?", (iid,))
    if not row:
        raise HTTPException(404)
    row["tasks"] = db.q("SELECT * FROM tasks WHERE source_id=?", (iid,))
    return row


@app.get("/api/alerts")
def alerts(limit: int = 50, _: str = Depends(require_owner)) -> list[dict]:
    return db.q("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))


@app.post("/api/alerts/{aid}/ack")
def ack_alert(aid: int, who: str = Depends(require_owner)) -> dict:
    db.ex("UPDATE alerts SET status='acknowledged' WHERE id=?", (aid,))
    db.audit(who, "alert_ack", {"id": aid})
    return {"ok": True}


@app.get("/api/tasks")
def tasks(status: str = "open", _: str = Depends(require_owner)) -> list[dict]:
    return db.q("""SELECT t.*, c.name contact FROM tasks t LEFT JOIN contacts c ON c.id=t.contact_id
                   WHERE t.status=? ORDER BY COALESCE(t.due_at,'9999'), t.id""", (status,))


@app.post("/api/tasks")
async def add_task(req: Request, who: str = Depends(require_owner)) -> dict:
    b = await req.json()
    tid = memory.add_task(b["title"], b.get("kind", "task"), b.get("details", ""), due_at=b.get("due_at"))
    db.audit(who, "task_added", {"id": tid})
    return {"id": tid}


@app.post("/api/tasks/{tid}/done")
def task_done(tid: int, who: str = Depends(require_owner)) -> dict:
    db.ex("UPDATE tasks SET status='done', updated_at=? WHERE id=?", (db.now_iso(), tid))
    db.audit(who, "task_done", {"id": tid})
    return {"ok": True}


@app.get("/api/actions")
def actions(status: str = "pending", _: str = Depends(require_owner)) -> list[dict]:
    return db.q("SELECT * FROM actions WHERE status=? ORDER BY id DESC", (status,))


@app.post("/api/actions")
async def propose_action(req: Request, who: str = Depends(require_owner)) -> dict:
    b = await req.json()
    return outbound.propose_and_maybe_run(b["action_type"], b["payload"], who)


@app.post("/api/actions/{aid}/{verb}")
def decide(aid: int, verb: str, who: str = Depends(require_owner)) -> dict:
    if verb not in ("approve", "reject"):
        raise HTTPException(400)
    return outbound.decide_action(aid, verb == "approve", who)


@app.get("/api/memories")
def memories(subject: str | None = None, status: str | None = None, _: str = Depends(require_owner)) -> list[dict]:
    if subject:
        return memory.facts_about(subject)
    if status:
        return db.q("SELECT * FROM memories WHERE status=? ORDER BY id DESC LIMIT 200", (status,))
    return db.q("SELECT * FROM memories WHERE status IN ('active','disputed') ORDER BY id DESC LIMIT 200")


@app.post("/api/memories")
async def add_memory(req: Request, _: str = Depends(require_owner)) -> dict:
    b = await req.json()
    return memory.remember(b.get("subject", "owner"), b["attribute"], b["value"], "owner", verified=True)


@app.patch("/api/memories/{mid}")
async def patch_memory(mid: int, req: Request, who: str = Depends(require_owner)) -> dict | None:
    b = await req.json()
    db.audit(who, "memory_edited", {"id": mid, **b})
    return memory.edit_memory(mid, b.get("value"), b.get("verified"), b.get("status"))


@app.delete("/api/memories/{mid}")
def delete_memory(mid: int, who: str = Depends(require_owner)) -> dict:
    memory.forget(mid)
    db.audit(who, "memory_deleted", {"id": mid})
    return {"ok": True}


@app.get("/api/search")
def search(q: str, _: str = Depends(require_owner)) -> dict:
    return memory.search(q)


@app.get("/api/contacts")
def contacts(_: str = Depends(require_owner)) -> list[dict]:
    return db.q("SELECT * FROM contacts ORDER BY tier='vip' DESC, name")


@app.post("/api/contacts")
async def upsert_contact(req: Request, who: str = Depends(require_owner)) -> dict:
    b = await req.json()
    c = memory.upsert_contact(b.get("name", ""), b.get("phone"), b.get("email"), b.get("relationship"), b.get("tier"), b.get("notes"))
    if b.get("name") and c["name"] != b["name"]:  # owner may rename
        db.ex("UPDATE contacts SET name=? WHERE id=?", (b["name"], c["id"]))
    db.audit(who, "contact_saved", {"id": c["id"]})
    return db.one("SELECT * FROM contacts WHERE id=?", (c["id"],))


@app.post("/api/mode")
async def set_mode(req: Request, who: str = Depends(require_owner)) -> dict:
    policy.set_mode((await req.json())["mode"], who)
    return {"mode": policy.get_mode()}


@app.post("/api/kill")
async def kill(req: Request, who: str = Depends(require_owner)) -> dict:
    policy.set_kill_switch(bool((await req.json())["on"]), who)
    return {"kill_switch": policy.kill_switch_on()}


@app.get("/api/briefing")
def briefing(hours: int = 24, _: str = Depends(require_owner)) -> dict:
    return build_briefing(hours)


@app.post("/api/chat")
async def chat(req: Request, _: str = Depends(require_owner)) -> dict:
    msg = (await req.json()).get("message", "").strip()
    first = msg.split(" ", 1)[0].lower() if msg else ""
    if first in ("status", "briefing", "mode", "kill", "resume", "approve", "reject", "remember", "done", "help"):
        return {"reply": commands.run(msg, "dashboard")}
    hits = memory.search(msg)
    lines = [f"[{i['channel']} {i['occurred_at'][:10]}] {i['contact'] or ''}: {i['summary']}" for i in hits["interactions"][:5]]
    lines += [f"(memory #{m['id']}{' verified' if m['verified'] else ''}) {m['subject']} {m['attribute']}: {m['value']}" for m in hits["memories"][:5]]
    return {"reply": "\n".join(lines) or "I have nothing stored about that yet.", "hits": hits}


@app.get("/api/audit")
def audit(limit: int = 100, _: str = Depends(require_owner)) -> list[dict]:
    return db.q("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))


@app.get("/api/rules")
def get_rules(_: str = Depends(require_owner)) -> list[dict]:
    return priority.get_rules()


@app.put("/api/rules")
async def put_rules(req: Request, who: str = Depends(require_owner)) -> dict:
    priority.set_rules(await req.json())
    db.audit(who, "rules_updated", {})
    return {"ok": True}


@app.post("/api/google/poll")
def google_poll(_: str = Depends(require_owner)) -> dict:
    from .google_api import poll_gmail
    return poll_gmail()


@app.post("/api/simulate/call")
async def simulate_call(req: Request, who: str = Depends(require_owner)) -> dict:
    """SIMULATION ONLY: feeds a fake ElevenLabs post-call payload through the real pipeline."""
    b = await req.json()
    payload = sample_elevenlabs_payload(**b)
    out = process_elevenlabs(payload, actor=f"{who}:simulation")
    out["simulated"] = True
    return out


# ---------------- provider webhooks ----------------
def sample_elevenlabs_payload(caller_number: str = "+19055550142", caller_name: str = "Dana Lee",  # fictional test caller
                              reason: str = "Calling from the legal clinic about the HRTO application. The filing deadline is Friday at 4pm, please call me back.",
                              urgency: str = "high", callback_time: str = "weekdays after 3pm",
                              conversation_id: str | None = None) -> dict:
    import uuid
    return {"type": "post_call_transcription", "event_timestamp": int(datetime.now().timestamp()),
            "data": {
                "agent_id": "agent_SIMULATED", "conversation_id": conversation_id or f"sim_{uuid.uuid4().hex[:12]}",
                "status": "done",
                "transcript": [
                    {"role": "agent", "message": f"Hello, you've reached {settings.owner_name}'s phone. I'm their AI assistant. This call is recorded and transcribed so I can pass on your message. How can I help?"},
                    {"role": "user", "message": f"Hi, it's {caller_name}. {reason}"},
                    {"role": "agent", "message": "Thanks. What's the best number and time to reach you?"},
                    {"role": "user", "message": f"{caller_number}, {callback_time}."},
                    {"role": "agent", "message": "Got it. I'll pass this on right away."}],
                "metadata": {"start_time_unix_secs": int(datetime.now().timestamp()) - 120, "call_duration_secs": 95,
                             "phone_call": {"external_number": caller_number, "agent_number": "+15555550100", "type": "twilio"}},
                "analysis": {"call_successful": "success", "transcript_summary": None,
                             "data_collection_results": {
                                 "caller_name": {"value": caller_name}, "callback_number": {"value": caller_number},
                                 "reason_for_call": {"value": reason}, "urgency_level": {"value": urgency},
                                 "best_callback_time": {"value": callback_time}}}}}


def process_elevenlabs(payload: dict, actor: str) -> dict:
    if payload.get("type") != "post_call_transcription":
        return {"ignored": payload.get("type")}
    d = payload.get("data", {})
    turns = d.get("transcript") or []
    transcript = "\n".join(f"{t.get('role', '?')}: {t.get('message') or ''}" for t in turns)
    caller_said = "\n".join(t.get("message") or "" for t in turns if t.get("role") == "user")
    dc = (d.get("analysis") or {}).get("data_collection_results") or {}
    fields = {k: (v or {}).get("value") for k, v in dc.items() if (v or {}).get("value")}
    pc = (d.get("metadata") or {}).get("phone_call") or {}
    start = (d.get("metadata") or {}).get("start_time_unix_secs")
    ev = Event(channel="call", external_id=d.get("conversation_id"), from_addr=pc.get("external_number") or fields.get("callback_number"),
               to_addr=pc.get("agent_number"), name_hint=fields.get("caller_name"), body=transcript,
               subject=fields.get("reason_for_call", "")[:120], fields=fields,
               provider_summary=(d.get("analysis") or {}).get("transcript_summary"),
               stated_urgency=fields.get("urgency_level"),
               occurred_at=datetime.fromtimestamp(start, timezone.utc).isoformat() if start else None)
    # Priority, injection scan and follow-up extraction use only what the CALLER said.
    ev.scan_text = caller_said
    return ingest(ev, actor=actor)


@app.post("/webhooks/elevenlabs/post-call")
async def elevenlabs_post_call(req: Request) -> JSONResponse:
    body = await req.body()
    if not verify_elevenlabs(settings.elevenlabs_webhook_secret, body, req.headers.get("elevenlabs-signature")):
        db.audit("webhook:elevenlabs", "signature_rejected", {})
        raise HTTPException(401, "bad signature")
    out = process_elevenlabs(json.loads(body), "webhook:elevenlabs")
    return JSONResponse({"ok": True, "interaction_id": out.get("interaction_id")})


async def _twilio_params(req: Request) -> dict[str, str]:
    form = await req.form()
    params = {k: str(v) for k, v in form.items()}
    url = settings.public_base_url + req.url.path
    if not verify_twilio(settings.twilio_auth_token, url, params, req.headers.get("x-twilio-signature")):
        db.audit("webhook:twilio", "signature_rejected", {"path": req.url.path})
        raise HTTPException(403, "bad signature")
    return params


@app.post("/webhooks/twilio/sms")
async def twilio_sms(req: Request) -> Response:
    p = await _twilio_params(req)
    frm, body = p.get("From"), p.get("Body", "")
    if commands.is_owner_sms(frm, body):
        return twiml(commands.run(commands.strip_pin(body), "sms"))
    ingest(Event(channel="sms", external_id=p.get("MessageSid"), from_addr=frm, to_addr=p.get("To"), body=body), "webhook:twilio")
    return twiml(None)  # never auto-reply to strangers from the webhook itself


@app.post("/webhooks/twilio/voice-fallback")
async def twilio_voice_fallback(req: Request) -> Response:
    """Backup if the ElevenLabs agent is down: plain voicemail with disclosure."""
    await _twilio_params(req)
    cb = escape(settings.public_base_url + "/webhooks/twilio/voicemail")
    xml = ('<?xml version="1.0" encoding="UTF-8"?><Response>'
           f"<Say>You've reached {escape(settings.owner_name)}'s automated assistant. This message will be recorded and transcribed. "
           "Please leave your name, number and the reason for your call after the tone.</Say>"
           f'<Record maxLength="120" playBeep="true" transcribe="true" transcribeCallback="{cb}"/></Response>')
    return Response(xml, media_type="application/xml")


@app.post("/webhooks/twilio/voicemail")
async def twilio_voicemail(req: Request) -> Response:
    p = await _twilio_params(req)
    ingest(Event(channel="call", external_id=p.get("CallSid"), from_addr=p.get("From"), to_addr=p.get("To"),
                 body=p.get("TranscriptionText", "(no transcription)"), subject="Voicemail"), "webhook:twilio")
    return twiml(None)


@app.post("/webhooks/ios/sms")
async def ios_sms_bridge(req: Request, authorization: str = Header(default="")) -> dict:
    """iPhone Shortcuts 'When I get a message' automation posts here: {from, name, body}."""
    tok = settings.ios_bridge_token
    if not tok or not hmac.compare_digest(authorization.removeprefix("Bearer ").strip(), tok):
        raise HTTPException(401)
    b = await req.json()
    out = ingest(Event(channel="sms", from_addr=b.get("from"), name_hint=b.get("name"), body=b.get("body", "")), "bridge:ios")
    return {"ok": True, "priority": out.get("priority")}
