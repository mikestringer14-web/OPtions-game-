"""Deliverable 14: a simulated incoming call is remembered, summarised, prioritised and sent to Mike."""
import json
import time

from app.main import sample_elevenlabs_payload
from app.signatures import elevenlabs_signature


def post_call(client, payload):
    body = json.dumps(payload).encode()
    return client.post("/webhooks/elevenlabs/post-call", content=body,
                       headers={"ElevenLabs-Signature": elevenlabs_signature("el-secret", body, int(time.time())),
                                "content-type": "application/json"})


def test_simulated_call_end_to_end(app_client):
    r = post_call(app_client, sample_elevenlabs_payload())
    assert r.status_code == 200
    iid = r.json()["interaction_id"]

    # remembered
    item = app_client.get(f"/api/interactions/{iid}").json()
    assert "HRTO" in item["body"] and item["channel"] == "call"
    contacts = app_client.get("/api/contacts").json()
    assert contacts[0]["name"] == "Dana Lee" and contacts[0]["phone"] == "+19055550142"
    facts = app_client.get("/api/memories", params={"subject": f"contact:{contacts[0]['id']}"}).json()
    assert {f["attribute"] for f in facts} == {"callback_number", "best_callback_time"}
    assert all(f["verified"] == 0 for f in facts)  # caller-provided = unverified

    # summarised + prioritised
    assert item["summary"].startswith("Dana Lee called. Reason:")
    assert "rule:medical" not in item["priority_why"]
    assert item["priority"] == "high" and "rule:legal" in item["priority_why"]

    # follow-ups created
    titles = [t["title"] for t in app_client.get("/api/tasks").json()]
    assert "Call back Dana Lee" in titles
    assert any("Friday" in t for t in titles)

    # communicated
    alert = app_client.get("/api/alerts").json()[0]
    assert alert["priority"] == "high" and alert["status"] == "sent" and "push" in alert["channels"]
    assert "ntfy:not-configured" in alert["delivery_log"]   # honest: no push provider in tests

    # searchable + in the briefing
    assert app_client.get("/api/search", params={"q": "legal clinic"}).json()["interactions"]
    assert "Dana Lee" in app_client.get("/api/briefing").json()["text"]

    # second call from same number: recognised, history retrieved, contradiction caught
    r2 = post_call(app_client, sample_elevenlabs_payload(reason="Following up on my earlier message.",
                                                         urgency="normal", callback_time="mornings only"))
    alert2 = app_client.get("/api/alerts").json()[0]
    assert "Last contact" in alert2["body"]
    assert "best_callback_time differs" in alert2["body"]
    assert len(app_client.get("/api/contacts").json()) == 1
