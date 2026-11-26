# Setup, step by step

Do these in order. Each step says what it costs and what you need. Nothing here changes your
phone service until step 7, and step 7 is reversible with one code.

## 0. Fix the Twilio billing first (5 min, important)
If Twilio's auto-recharge is failing, your numbers stop working when the balance hits zero.
Go to Twilio Console, Billing, confirm the card works, and add a backup payment method.

## 1. Server (20 min, about $5-7/month)
Recommended: a Hetzner CX22 or a DigitalOcean $6 droplet, Ubuntu 24.04, Toronto/US-East region.
```bash
ssh root@SERVER
apt update && apt install -y docker.io docker-compose-v2 git
git clone <your-repo-url> /srv/repo
ln -s /srv/repo/exec-assistant /srv/exec-assistant && cd /srv/exec-assistant
cp .env.example .env && chmod 600 .env && nano .env
```
Fill in at least `EA_ADMIN_TOKEN` (generate with `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`),
`EA_PUBLIC_BASE_URL`, `EA_OWNER_PHONE`, `EA_OWNER_PIN`.

## 2. Domain + HTTPS (10 min, free)
Make a free name at duckdns.org pointing at the server IP. Put it in `deploy/Caddyfile` and in
`EA_PUBLIC_BASE_URL` as `https://yourname.duckdns.org`.

## 3. Start it
```bash
cd deploy
age-keygen -o ~/age-key.txt            # KEEP ~/age-key.txt OFF the server (password manager)
grep 'public key' ~/age-key.txt | awk '{print $4}' > age-recipient.txt
docker compose up -d --build
curl https://yourname.duckdns.org/health
```
Open the URL on your iPhone, sign in with the admin token, Share, Add to Home Screen.

## 4. Push alerts to your iPhone (5 min, free)
Install **ntfy** from the App Store. Subscribe to a long random topic (e.g. `mike-ea-7f3k9q2x`).
Put the same topic in `NTFY_TOPIC`. In iPhone Settings, Notifications, ntfy, allow Time Sensitive /
Critical if you want critical alerts to break through Focus. Restart: `docker compose restart assistant`.

## 5. Connect Arthur (10 min)
In ElevenLabs: Agents, your secretary agent, Workflows/Webhooks, add a **post-call webhook** to
`https://yourname.duckdns.org/webhooks/elevenlabs/post-call`. Copy the generated secret into
`ELEVENLABS_WEBHOOK_SECRET`. Restart.

Two changes I recommend to Arthur's first message (I have NOT made them; you approve):
- Add "This call is recorded and transcribed so I can pass your message on."
- Remove "or try to connect you" unless you set up a transfer target that can't loop (see TELECOM_CANADA.md).

Make sure the agent is assigned to your Twilio number in ElevenLabs, Phone Numbers.

Test: call that Twilio number from another phone, leave a message, watch the dashboard.

## 6. Gmail + Calendar (30 min, free)
1. console.cloud.google.com, new project, enable Gmail API and Google Calendar API.
2. OAuth consent screen: External, add yourself as a test user.
3. Credentials, OAuth client ID, Desktop app. Copy client ID and secret into `.env`.
4. Get a refresh token with scopes `gmail.modify` and `calendar.events` (OAuth Playground with
   "use your own credentials", or `google-auth-oauthlib` on your laptop). Put it in `GOOGLE_REFRESH_TOKEN`.
5. Note: in "Testing" status Google refresh tokens expire after 7 days. Publish the app (no review
   needed for personal use with under 100 users, you'll see an "unverified app" warning) to stop that.
6. Install `deploy/crontab.example` to poll every 10 minutes and push the 6:00 and 22:30 briefings.

## 7. Forward missed calls from your real number (2 min, reversible)
See TELECOM_CANADA.md. Short version, on the iPhone keypad: `*61*1TWILIONUMBER#` (no answer),
`*67*1TWILIONUMBER#` (busy), `*62*1TWILIONUMBER#` (unreachable). Undo with `##61#`, `##67#`, `##62#`.

## 8. Text commands to the assistant
Text your Twilio number from your own cell, starting with your PIN (4821 below is only an example, pick your own): `4821 status`, `4821 briefing`,
`4821 mode observer`, `4821 kill`, `4821 resume`, `4821 approve 7`. In Twilio, set the number's
"A message comes in" webhook to `https://yourname.duckdns.org/webhooks/twilio/sms`.

## 9. Optional: smarter summaries
Set `EA_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`. Daily spend cap: `EA_DAILY_SPEND_LIMIT_USD`.
