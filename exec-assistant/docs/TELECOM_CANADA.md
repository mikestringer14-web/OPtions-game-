# Phone and SMS in Canada: keeping your number

## Calls: conditional call forwarding (recommended)
Keep your cell number and carrier exactly as they are. Only **missed** calls go to Arthur.

GSM codes (Rogers documents these; Telus business documents the same pattern; Bell uses the GSM standard):

| Condition | Turn on | Turn off | Check |
|---|---|---|---|
| No answer | `*61*1TWILIONUMBER#` (optional delay: `*61*1NUMBER**20#` = 20 s) | `##61#` | `*#61#` |
| Busy / declined | `*67*1TWILIONUMBER#` | `##67#` | `*#67#` |
| Phone off / no signal | `*62*1TWILIONUMBER#` | `##62#` | `*#62#` |
| "Assistant mode" (everything) | `*21*1TWILIONUMBER#` | `##21#` | `*#21#` |

Verify before relying on it:
- **Rogers** says conditional forwarding does not work while carrier voicemail is active. You may need them to turn voicemail off.
- **Telus**: a community thread reports conditional codes stopping on some VoLTE accounts while `*21` still worked. If codes fail, call support and ask them to set "call forward no answer / busy / unreachable" for you.
- Some plans bill forwarded minutes as airtime. With unlimited Canada-wide minutes this is usually free. Ask your carrier.
- Make one test call for each condition.

**Forwarding loops.** If Arthur "transfers" an urgent caller to your cell and you don't answer, your
cell forwards back to Arthur. Avoid this in v1: Arthur does not transfer to your cell. Critical calls
trigger an instant push + text so you call back within a minute. Later option: transfer to a second
line (e.g. a cheap Twilio number that rings your laptop/app) which has no forwarding.

**Do not port your cell number to Twilio.** Porting moves the number off your SIM: no more normal
cellular calls on it, iMessage/FaceTime would re-register, and bank 2FA texts could break.

## Texts: what is actually possible on iPhone
Apple gives no app or server access to your Messages. Voice forwarding does **not** forward texts.
Options, best first:
1. **Assistant number for texting.** People who should reach the assistant text your Twilio number. Full two-way, approval-based replies. Works today once Twilio keys are set.
2. **iOS Shortcuts bridge (partial).** Shortcuts, Automation, "Message" trigger, choose the senders (and/or words) to watch, action "Get Contents of URL": POST to `https://yourname.duckdns.org/webhooks/ios/sms` with header `Authorization: Bearer <EA_IOS_BRIDGE_TOKEN>` and JSON `{"from": Sender, "name": Sender, "body": Message}`. Turn off "Ask Before Running". Apple lists Message among automations that can run without asking on recent iOS; test on your phone. It only sees the senders/keywords you pick, and only while the phone is on.
3. **You stay the sender.** The assistant drafts a reply on the dashboard; you tap copy and send it yourself in Messages. Nothing about iMessage changes.

Bank and 2FA codes stay on your phone. The guard flags any message asking the assistant for codes.

## Recording and disclosure
- Criminal Code s.184: recording is lawful when one party to the call consents. The assistant is your agent and a party.
- PIPEDA generally does not cover information you collect for purely personal purposes, but disclose anyway: it's honest, it is good practice, and it keeps recordings usable if you ever rely on them.
- Arthur must say it is an AI assistant and that the call is recorded and transcribed. Add the recording line to his first message (see SETUP.md step 5).
- Never use this system to place automated outbound calls to people who didn't ask for them (CRTC Unsolicited Telecommunications Rules).
