"""Summaries and extraction. Works fully offline with rules; an LLM key only improves wording.

LLM output is advisory. It never triggers actions directly: everything still goes through policy.py.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from . import db
from .config import settings
from .guard import wrap_untrusted

DATE_WORDS = r"(today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|" \
             r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)"


def rule_summary(text: str, fields: dict | None = None, max_len: int = 300) -> str:
    fields = fields or {}
    if fields.get("caller_name") or fields.get("reason_for_call"):
        out = f"{fields.get('caller_name') or 'Caller'} called."
        if fields.get("reason_for_call"):
            out += f" Reason: {fields['reason_for_call'].strip().rstrip('.')}."
        cb = " ".join(x for x in (fields.get("best_callback_time"), fields.get("callback_number") and f"at {fields['callback_number']}") if x)
        if cb:
            out += f" Best callback: {cb}."
        return out[:max_len]
    clean = re.sub(r"\s+", " ", text or "").strip()
    first = re.split(r"(?<=[.!?])\s", clean)[:2]
    return " ".join(first)[:max_len]


def extract_followups(text: str) -> list[dict]:
    """Find promises and deadlines in plain text. Conservative: better to miss than invent."""
    out = []
    for m in re.finditer(r"([^.!?\n]*\b(deadline|due|by|before|no later than|appointment|interview|hearing)\b[^.!?\n]*)", text or "", re.I):
        sentence = m.group(1).strip()
        if re.search(DATE_WORDS + r"|\d{1,2}(:\d{2})?\s?(am|pm)|\d{4}-\d{2}-\d{2}", sentence, re.I):
            out.append({"kind": "deadline", "title": sentence[:160]})
    for m in re.finditer(r"([^.!?\n]*\b(please call|call me back|get back to me|send me|can you)\b[^.!?\n]*)", text or "", re.I):
        out.append({"kind": "follow_up", "title": m.group(1).strip()[:160]})
    seen, uniq = set(), []
    for o in out:
        if o["title"].lower() not in seen:
            seen.add(o["title"].lower())
            uniq.append(o)
    return uniq[:5]


def _spent_today() -> float:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    row = db.one("SELECT COALESCE(SUM(usd),0) AS s FROM spend WHERE ts>=?", (since,))
    return float(row["s"]) if row else 0.0


def llm_summary(text: str, source: str) -> str | None:
    """Optional LLM pass. Returns None when not configured, over budget, or on any error."""
    if settings.llm_provider == "none":
        return None
    if _spent_today() >= settings.daily_spend_limit_usd:
        db.audit("system", "llm_skipped_budget", {"limit": settings.daily_spend_limit_usd})
        return None
    prompt = (f"Summarise this communication for {settings.owner_name} in 2 short sentences: who, what they want, any deadline. "
              "Plain language, no em dashes.\n\n" + wrap_untrusted(text[:8000], source))
    try:
        if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=30, headers={
                "x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"},
                json={"model": settings.anthropic_model, "max_tokens": 200,
                      "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            data = r.json()
            db.ex("INSERT INTO spend(ts,service,usd,note) VALUES(?,?,?,?)", (db.now_iso(), "anthropic", 0.002, "summary"))
            return "".join(b.get("text", "") for b in data.get("content", [])).strip() or None
        if settings.llm_provider == "openai" and settings.openai_api_key:
            r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=30,
                           headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                           json={"model": settings.openai_model, "max_tokens": 200,
                                 "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            db.ex("INSERT INTO spend(ts,service,usd,note) VALUES(?,?,?,?)", (db.now_iso(), "openai", 0.001, "summary"))
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa: BLE001 - never let the LLM break ingestion
        db.audit("system", "llm_error", {"provider": settings.llm_provider, "error": str(e)[:300]})
    return None


def summarize(text: str, source: str, fields: dict | None = None, provider_summary: str | None = None) -> str:
    return llm_summary(text, source) or provider_summary or rule_summary(text, fields)


def to_json(x) -> str:
    return json.dumps(x, default=str)
