# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Dashboard says "Set EA_ADMIN_TOKEN" | Token missing, default, or under 16 chars | Set it in `.env`, restart |
| 401 on dashboard | Wrong token saved in browser | Clear site data or re-enter token |
| ElevenLabs webhook shows 401 | Secret mismatch or server clock off by >30 min | Re-copy secret; `timedatectl` to check clock |
| Twilio SMS webhook 403 | `EA_PUBLIC_BASE_URL` doesn't match the URL Twilio calls exactly (https, no trailing slash) | Fix the URL, restart |
| Alert says `ntfy:not-configured` | `NTFY_TOPIC` empty | Step 4 of SETUP |
| Alert says `sms:not-configured` | Twilio SID/token/from number or `EA_OWNER_PHONE` missing | Fill them in |
| `sms:401` / `sms:20003` | Wrong Twilio credentials | Re-copy from Twilio console |
| Twilio calls fail / "account suspended" | Balance at zero (recharge failed in Oct) | Update card in Twilio Billing |
| Missed calls still go to carrier voicemail | Carrier voicemail overrides conditional forwarding (Rogers), or codes not supported (some Telus VoLTE) | Ask carrier to disable voicemail / set forwarding for you |
| Calls loop between Arthur and your cell | Arthur transfers to your cell, cell forwards back | Remove transfer to your own cell (TELECOM_CANADA.md) |
| Text command ignored | Not from `EA_OWNER_PHONE`, or PIN not first word | Text `PIN status` |
| Gmail poll `blocked` | Google OAuth not configured | SETUP step 6 |
| Gmail worked for a week then stopped | Refresh token expired (app in Testing) | Publish the OAuth app, get a new token |
| A message was marked "possible scam" wrongly | Rule too broad | Edit rules via `PUT /api/rules`, or mark the contact VIP |
| Something is going wrong right now | | Dashboard Kill switch, or text `PIN kill`. Then check Audit log. |

Logs: `docker compose logs -f assistant`. Health: `curl https://yourname.duckdns.org/health`.
Run tests after any change: `python -m pytest -q`.
