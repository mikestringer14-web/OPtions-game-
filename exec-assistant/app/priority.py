"""Four-level urgency engine. Rules are plain data so the owner can edit them from the dashboard."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import db

LEVELS = ["low", "normal", "high", "critical"]

DEFAULT_RULES = [
    # (name, level, regex) -- first match at the highest level wins
    {"name": "emergency", "level": "critical",
     "pattern": r"\b(emergency|hospital|ambulance|911|accident|passed away|died|police|fire)\b"},
    {"name": "family_urgent", "level": "critical", "requires_tier": "vip",
     "pattern": r"\b(urgent|asap|right away|call me back now|immediately)\b"},
    {"name": "legal", "level": "high",
     "pattern": r"\b(hrto|tribunal|lawyer|legal clinic|paralegal|hearing|summons|subpoena|statement of claim|"
                r"limitation period|filing deadline|privacy commission(er)?|ipc|human rights)\b"},
    {"name": "job", "level": "high",
     "pattern": r"\b(job offer|offer letter|interview|apprenticeship|hiring manager|start date|we'?d like to offer)\b"},
    {"name": "employer_hr", "level": "high",
     "pattern": r"\b(hr|human resources|disciplinary|termination|accommodation|return to work|benefits)\b"},
    {"name": "financial", "level": "high",
     "pattern": r"\b(overdue|past due|final notice|collections?|nsf|payment failed|couldn'?t be recharged|odsp)\b"},
    {"name": "medical", "level": "high",
     "pattern": r"\b(doctor|medical clinic|walk-in clinic|pharmacy|prescription|appointment (reminder|confirmation)|test results)\b"},
    {"name": "housing", "level": "normal",
     "pattern": r"\b(apartment|viewing|landlord|lease|rental application|rent)\b"},
    {"name": "callback", "level": "normal", "pattern": r"\b(call (me )?back|callback|give me a call)\b"},
    {"name": "marketing", "level": "low",
     "pattern": r"\b(unsubscribe|newsletter|% off|sale ends|promo code|limited time)\b"},
]


@dataclass
class Verdict:
    level: str
    reasons: list[str]


def get_rules() -> list[dict]:
    raw = db.get_setting("priority_rules")
    return json.loads(raw) if raw else DEFAULT_RULES


def set_rules(rules: list[dict]) -> None:
    for r in rules:
        re.compile(r["pattern"])
        assert r["level"] in LEVELS
    db.set_setting("priority_rules", json.dumps(rules))


def classify(text: str, contact: dict | None = None, stated_urgency: str | None = None,
             scam: bool = False) -> Verdict:
    text = text or ""
    tier = (contact or {}).get("tier", "normal")
    reasons: list[str] = []

    if tier == "blocked":
        return Verdict("low", ["contact is blocked"])
    if scam:
        return Verdict("low", ["looks like a scam or phishing attempt (not actioned)"])

    matched: list[str] = []
    for rule in get_rules():
        if rule.get("requires_tier") and rule["requires_tier"] != tier:
            continue
        if re.search(rule["pattern"], text, re.I):
            reasons.append(f"rule:{rule['name']}")
            matched.append(rule["level"])
    # Only marketing-type rules matched -> low. Otherwise the highest matched level (default normal).
    if matched and all(m == "low" for m in matched):
        best = "low"
    else:
        best = max([m for m in matched if m != "low"] + ["normal"], key=LEVELS.index)

    # Caller's own stated urgency (from the voice agent's data collection) can raise, never lower past rules.
    su = (stated_urgency or "").lower()
    if su in ("critical", "emergency"):
        su_level = "high" if tier != "vip" else "critical"
    elif su in ("high", "urgent"):
        su_level = "high"
    else:
        su_level = None
    if su_level and LEVELS.index(su_level) > LEVELS.index(best):
        best = su_level
        reasons.append(f"caller said urgency={su}")

    if tier == "vip" and best in ("low", "normal"):
        best = "high"
        reasons.append("VIP contact")

    if not reasons:
        reasons.append("no rule matched")
    return Verdict(best, reasons)
