# Executive Assistant (MVP)

A 24/7 personal assistant backend: one memory for calls, texts and email, a four-level urgency
engine, an approval queue for anything it sends, and a phone-friendly dashboard.

It plugs into what you already have:

| You already have | Role in this system |
|---|---|
| An ElevenLabs voice agent with data-collection fields caller_name, callback_number, reason_for_call, urgency_level, best_callback_time | Answers the phone. Sends each finished call to this server by signed webhook. |
| A Twilio account and Canadian number linked in ElevenLabs | Phone line the agent answers; also sends your alert texts. |
| Gmail with labels | Polled for new mail once Google OAuth is set up. |
| Hermes agent on a laptop (Tailscale) | Stays a laptop power tool. Not the 24/7 core, because it stops when the laptop is off. It can call this server's API. |

## What works today vs what is blocked

| Component | Status | Proof |
|---|---|---|
| Central memory (contacts, interactions, facts with confidence + source, tasks, full-text search) | **Working** | tests/test_core.py, tests/test_e2e_simulated_call.py |
| Contradiction detection, edit/delete memories, owner-verified facts win | **Working** | test_contradiction_detection, test_memory_edit_and_delete |
| Priority engine (critical/high/normal/low), editable rules, VIP contacts, quiet hours, dedupe | **Working** | test_priority_levels, test_quiet_hours..., test_duplicate... |
| Prompt-injection + scam flagging; outside messages can never run commands | **Working** | test_injected_sms_is_never_a_command |
| Modes (observer / approval / autonomous / emergency), hard limits, kill switch, approval queue | **Working** | test_policy_modes, test_approval_flow_simulated_send |
| Owner commands by text with phone number + PIN | **Working** (signed Twilio request simulated in tests) | test_owner_sms_command_requires_pin |
| Webhook signature checks (Twilio HMAC-SHA1, ElevenLabs HMAC-SHA256) | **Working** | test_twilio_signature_roundtrip, test_elevenlabs_signature |
| Dashboard (iPhone + Windows browser) | **Working** locally, screenshotted | `uvicorn app.main:app` then open / |
| End-to-end simulated call: remembered, summarised, prioritised, alert produced | **Working (SIMULATED call)** | `python scripts/demo_simulated_call.py` |
| Push notifications to iPhone (ntfy) | **Code done, not live**: needs you to install ntfy and pick a topic | |
| Alert texts and approved outbound SMS via Twilio | **Code done, not live**: needs Twilio keys in .env. Until then sends are marked SIMULATED. | |
| Arthur's real calls arriving here | **Blocked on you**: server must be deployed, then the webhook added in ElevenLabs | docs/SETUP.md step 5 |
| Gmail poll + Calendar conflicts | **Code written, not live-tested**: needs your own Google OAuth client | docs/SETUP.md step 6 |
| Reading your iPhone's own texts | **Partial by design**: iOS Shortcuts bridge endpoint is built; Apple doesn't allow full SMS access | docs/TELECOM_CANADA.md |
| LLM-written summaries | **Optional**: rules-based summaries work with no key; add an Anthropic or OpenAI key to improve wording | |
| Room speaker (Phase 6) | **Design only** | docs/HARDWARE.md |
| Vector (semantic) search | **Not built yet**: SQLite full-text search for now; pgvector is the upgrade path | docs/ARCHITECTURE.md |

## Quick start (local)

```bash
cd exec-assistant
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                                   # 17 tests
python scripts/demo_simulated_call.py                 # the end-to-end demo
cp .env.example .env                                  # then set EA_ADMIN_TOKEN at minimum
set -a && source .env && set +a
uvicorn app.main:app --port 8000                      # open http://127.0.0.1:8000
```

## Docs
- [Architecture + diagram](docs/ARCHITECTURE.md)
- [Setup, step by step](docs/SETUP.md)
- [Canadian phone + SMS options](docs/TELECOM_CANADA.md)
- [Security, permissions, privacy law](docs/SECURITY.md)
- [Monthly costs](docs/COSTS.md)
- [Room speaker hardware](docs/HARDWARE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
