import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TOKEN = "test-admin-token-1234567890"


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    env = {"EA_ADMIN_TOKEN": TOKEN, "EA_DB_PATH": str(tmp_path / "t.db"), "EA_MODE": "approval",
           "ELEVENLABS_WEBHOOK_SECRET": "el-secret", "TWILIO_AUTH_TOKEN": "tw-token",
           "EA_PUBLIC_BASE_URL": "https://assistant.test", "EA_OWNER_PHONE": "+19055550100",
           "EA_OWNER_PIN": "4821", "EA_IOS_BRIDGE_TOKEN": "ios-token", "EA_LLM_PROVIDER": "none",
           "NTFY_TOPIC": "", "TWILIO_ACCOUNT_SID": "", "TWILIO_FROM_NUMBER": ""}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app import config
    s = config.reload_settings()
    # every module imported `settings` by name; point them all at the fresh object
    import app.briefing, app.commands, app.db, app.google_api, app.llm, app.main, app.notify, app.outbound, app.policy  # noqa
    for mod in (app.commands, app.db, app.google_api, app.llm, app.main, app.notify, app.outbound, app.policy):
        monkeypatch.setattr(mod, "settings", s, raising=False)
    app.db.reset(str(tmp_path / "t.db"))
    # never let tests hit the network for alerts
    monkeypatch.setattr(app.notify, "in_quiet_hours", lambda now=None: False)
    from fastapi.testclient import TestClient
    c = TestClient(app.main.app)
    c.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return c
