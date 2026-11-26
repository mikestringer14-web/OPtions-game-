# Monthly operating cost (estimates, verify before budgeting)

Prices checked Nov 2026 from public pricing pages. Twilio's own Canada pages showed conflicting
per-minute numbers, so confirm in your Twilio console. All USD unless noted.

| Item | Light use (30 missed calls x 2 min, 50 texts) | Notes |
|---|---|---|
| VPS (Hetzner CX22 / DO droplet) | $5-7 | Always on, so works when laptop and phone are off |
| Domain (DuckDNS) | $0 | |
| Twilio local CA number | $1.15 each | Per number. |
| Twilio inbound voice | about $0.25-0.50 | $0.004-0.0085/min, conflicting listings |
| Twilio SMS (alerts + replies) | about $0.50-1.00 | Check current CA SMS rate in console |
| ElevenLabs agent minutes | about $5 (60 min x $0.08) | Plus your existing ElevenLabs plan. LLM charges on top may apply. |
| ntfy push | $0 | |
| LLM summaries (optional) | under $1 | Capped by EA_DAILY_SPEND_LIMIT_USD |
| Carrier forwarding | usually $0 | Ask if forwarded minutes count as airtime |
| **Total** | **about $15-20 USD/month (about $21-28 CAD)** plus your ElevenLabs plan | |

Ways to cut it:
- Run fallback voicemail (Twilio `<Record>` + transcription, `/webhooks/twilio/voice-fallback`) instead of Arthur for low-value hours: no ElevenLabs minutes.
- Oracle Cloud free tier VM instead of a paid VPS ($0, more setup).
- Release any Twilio number you no longer use.
