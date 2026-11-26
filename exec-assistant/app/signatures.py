"""Webhook signature verification. Unsigned or badly signed requests are rejected."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time


def twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio: base64(HMAC-SHA1(auth_token, url + concat(sorted key+value)))."""
    data = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def verify_twilio(auth_token: str, url: str, params: dict[str, str], header_sig: str | None) -> bool:
    if not auth_token or not header_sig:
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), header_sig)


def elevenlabs_signature(secret: str, body: bytes, ts: int) -> str:
    """ElevenLabs post-call webhook: header 'ElevenLabs-Signature: t=<ts>,v0=<hex sha256 hmac of '<ts>.<body>'>'"""
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v0={mac}"


def verify_elevenlabs(secret: str, body: bytes, header: str | None, tolerance_s: int = 30 * 60) -> bool:
    if not secret or not header:
        return False
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
        sig = parts["v0"]
    except (ValueError, KeyError):
        return False
    if abs(time.time() - ts) > tolerance_s:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
