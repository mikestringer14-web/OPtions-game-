"""End-to-end demo: a SIMULATED missed call goes through the real pipeline.

Usage
  python scripts/demo_simulated_call.py                      # self-contained, temp database
  python scripts/demo_simulated_call.py --url http://127.0.0.1:8000   # against a running server
    (needs ELEVENLABS_WEBHOOK_SECRET and EA_ADMIN_TOKEN in the environment, same as the server)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    args = ap.parse_args()

    if args.url:
        import httpx
        client = httpx.Client(base_url=args.url, timeout=20)
        secret, token = os.environ["ELEVENLABS_WEBHOOK_SECRET"], os.environ["EA_ADMIN_TOKEN"]
    else:
        tmp = tempfile.mkdtemp()
        secret, token = "demo-secret", "demo-admin-token-0123456789"
        os.environ.update({"EA_DB_PATH": f"{tmp}/demo.db", "EA_ADMIN_TOKEN": token,
                           "ELEVENLABS_WEBHOOK_SECRET": secret, "EA_LLM_PROVIDER": "none"})
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

    from app.main import sample_elevenlabs_payload
    from app.signatures import elevenlabs_signature
    auth = {"Authorization": f"Bearer {token}"}

    print("STEP 1  A caller reaches Arthur (the ElevenLabs agent). SIMULATED post-call webhook is sent.\n")
    payload = sample_elevenlabs_payload()
    for t in payload["data"]["transcript"]:
        print(f"   {t['role']:>5}: {t['message']}")
    body = json.dumps(payload).encode()
    r = client.post("/webhooks/elevenlabs/post-call", content=body,
                    headers={"ElevenLabs-Signature": elevenlabs_signature(secret, body, int(time.time())),
                             "content-type": "application/json"})
    print(f"\n   webhook -> HTTP {r.status_code} {r.json()}")
    iid = r.json()["interaction_id"]

    item = client.get(f"/api/interactions/{iid}", headers=auth).json()
    print("\nSTEP 2  Remembered")
    for c in client.get("/api/contacts", headers=auth).json():
        print(f"   contact #{c['id']}: {c['name']} {c['phone']} (tier {c['tier']})")
    for m in client.get("/api/memories", headers=auth).json():
        print(f"   fact #{m['id']}: {m['subject']} {m['attribute']} = {m['value']}  [{'verified' if m['verified'] else 'unverified'}, conf {m['confidence']}]")
    print(f"\nSTEP 3  Summarised\n   {item['summary']}")
    print(f"\nSTEP 4  Prioritised\n   {item['priority'].upper()}  because {item['priority_why']}")
    print("\nSTEP 5  Follow-ups created")
    for t in client.get("/api/tasks", headers=auth).json():
        print(f"   task #{t['id']} [{t['kind']}] {t['title']}")
    a = client.get("/api/alerts", headers=auth).json()[0]
    print(f"\nSTEP 6  Communicated to the owner\n   alert #{a['id']} {a['priority']} -> {a['status']} via {a['channels']}")
    print(f"   delivery: {a['delivery_log'] or '(dashboard only)'}")
    print("   " + a["body"].replace("\n", "\n   "))
    print("\nSTEP 7  Briefing\n")
    print("   " + client.get("/api/briefing", headers=auth).json()["text"].replace("\n", "\n   "))
    print("\nNOTE: the call, caller and number are SIMULATED. Push/SMS delivery only happens once NTFY_TOPIC / Twilio are set.")


if __name__ == "__main__":
    main()
