"""Settings loaded from environment variables. Nothing secret is hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _hhmm(value: str, default: str) -> time:
    h, m = (value or default).split(":")
    return time(int(h), int(m))


@dataclass
class Settings:
    admin_token: str = field(default_factory=lambda: _env("EA_ADMIN_TOKEN"))
    db_path: str = field(default_factory=lambda: _env("EA_DB_PATH", "./data/assistant.db"))
    timezone: str = field(default_factory=lambda: _env("EA_TIMEZONE", "America/Toronto"))
    public_base_url: str = field(default_factory=lambda: _env("EA_PUBLIC_BASE_URL").rstrip("/"))
    default_mode: str = field(default_factory=lambda: _env("EA_MODE", "approval"))
    quiet_start: time = field(default_factory=lambda: _hhmm(_env("EA_QUIET_START"), "23:00"))
    quiet_end: time = field(default_factory=lambda: _hhmm(_env("EA_QUIET_END"), "05:30"))
    daily_spend_limit_usd: float = field(default_factory=lambda: float(_env("EA_DAILY_SPEND_LIMIT_USD", "3.00")))

    owner_name: str = field(default_factory=lambda: _env("EA_OWNER_NAME", "the owner"))
    owner_phone: str = field(default_factory=lambda: _env("EA_OWNER_PHONE"))
    owner_pin: str = field(default_factory=lambda: _env("EA_OWNER_PIN"))

    llm_provider: str = field(default_factory=lambda: _env("EA_LLM_PROVIDER", "none"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("EA_ANTHROPIC_MODEL", "claude-haiku-5-5"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("EA_OPENAI_MODEL", "gpt-4o-mini"))

    ntfy_topic: str = field(default_factory=lambda: _env("NTFY_TOPIC"))
    ntfy_server: str = field(default_factory=lambda: _env("NTFY_SERVER", "https://ntfy.sh"))

    twilio_account_sid: str = field(default_factory=lambda: _env("TWILIO_ACCOUNT_SID"))
    twilio_auth_token: str = field(default_factory=lambda: _env("TWILIO_AUTH_TOKEN"))
    twilio_from_number: str = field(default_factory=lambda: _env("TWILIO_FROM_NUMBER"))

    elevenlabs_webhook_secret: str = field(default_factory=lambda: _env("ELEVENLABS_WEBHOOK_SECRET"))
    ios_bridge_token: str = field(default_factory=lambda: _env("EA_IOS_BRIDGE_TOKEN"))

    google_client_id: str = field(default_factory=lambda: _env("GOOGLE_CLIENT_ID"))
    google_client_secret: str = field(default_factory=lambda: _env("GOOGLE_CLIENT_SECRET"))
    google_refresh_token: str = field(default_factory=lambda: _env("GOOGLE_REFRESH_TOKEN"))

    def integration_status(self) -> dict[str, str]:
        """What is configured. 'configured' means credentials exist, not that a live call succeeded."""
        def s(ok: bool) -> str:
            return "configured" if ok else "not configured"
        return {
            "llm": self.llm_provider if self.llm_provider != "none" else "rules-only (no LLM key)",
            "push_ntfy": s(bool(self.ntfy_topic)),
            "twilio_sms_out": s(bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)),
            "elevenlabs_webhook": s(bool(self.elevenlabs_webhook_secret)),
            "ios_sms_bridge": s(bool(self.ios_bridge_token)),
            "google": s(bool(self.google_client_id and self.google_refresh_token)),
            "owner_sms_commands": s(bool(self.owner_phone and self.owner_pin)),
        }


settings = Settings()


def reload_settings() -> Settings:
    global settings
    settings = Settings()
    return settings
