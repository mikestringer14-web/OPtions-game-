# Security, permissions and privacy

## Who can give orders
| Source | Trusted? | What it can do |
|---|---|---|
| Dashboard with admin token | Yes | Everything, including approving financial/legal drafts |
| Text from your cell **and** starting with your PIN | Yes, limited | Status, briefing, mode, kill/resume, approve routine/sensitive items. **Cannot** approve financial/legal items (caller ID can be spoofed). |
| Callers, texters, emailers | **No, never** | Their words are stored as data. They cannot change settings, trigger sends, or get information. |

## Hard limits (no mode overrides them)
Financial transactions, contracts or anything legally binding, sharing confidential info (SIN, passwords,
health card, account numbers), and employment or legal decisions are classified **forbidden** and always
wait for you in the dashboard. Example: "I'll e-transfer you $200" is caught and queued.

## Modes
- **Observer**: watch, summarise, alert. Sends nothing.
- **Approval** (default): drafts go to the queue.
- **Autonomous**: only actions on the routine list (`ack_message`, `send_holding_reply`) run alone.
- **Emergency**: high alerts escalate as critical.
- **Kill switch**: blocks every outbound send instantly. Dashboard button, or text `PIN kill`.

## Controls in the code
- Webhook signatures: Twilio HMAC-SHA1 over URL + params; ElevenLabs HMAC-SHA256 with timestamp (30 min replay window). Unsigned requests get 401/403 and are logged.
- Prompt injection: external text is scanned, flagged, wrapped in `<untrusted>` before any LLM sees it, and LLM output can never trigger an action.
- Duplicate webhooks (provider retries) are stored once; duplicate alerts within 30 min are suppressed.
- Constant-time token comparison; dashboard refuses to run with a weak/default token.
- Append-only audit log of every command, mode change, alert, approval, send and failed login.
- Spend cap per day for LLM calls; every paid call is recorded in `spend`.
- Policy is checked twice: when an action is proposed and again right before it is sent.

## Data protection
- `.env` mode 600, never committed. Secrets only in environment variables.
- Nightly encrypted backups with `age` (public key on server, private key kept off the server). 30-day retention.
- Server disk: use the provider's encrypted volume option. Enable the firewall: `ufw allow 22,80,443/tcp`.
- Deletion: any memory can be hard-deleted from the dashboard. For a full wipe, stop the app and delete the volume.
- MFA: turn on 2FA for Twilio, ElevenLabs, Google, the VPS provider, and DuckDNS/GitHub.

## Things still to add (honest list)
- Rate limiting on the public webhook paths (Caddy `rate_limit` plugin or fail2ban).
- Per-device dashboard logins instead of one shared token.
- IP allowlisting for ElevenLabs webhooks (they publish ranges).

## Privacy law notes (Ontario/Canada, not legal advice)
- Recording calls you are part of: lawful with one-party consent (Criminal Code s.184). Disclose anyway.
- PIPEDA largely exempts purely personal use. If you ever run this for clients (e.g. a business line), PIPEDA applies: consent, purpose, retention limits, access requests.
- Third parties' information (coworkers, landlords, lawyers) sits in this database. Treat it as confidential; only share it with your lawyer.
- For any legal or employment dispute this log is useful: timestamped calls and messages with an audit trail. Keep the original exports too.
