# Room assistant (Phase 6): hardware and design

Goal: hear critical alerts and reminders out loud, talk to the assistant by voice, with no
always-on cloud microphone.

## Recommended build (about $150-220 CAD)
| Part | Why | Approx. |
|---|---|---|
| Raspberry Pi 5 (4 GB) + power + case + 64 GB card | Runs Home Assistant OS + local wake word + local speech-to-text | $120-150 |
| Home Assistant Voice Preview Edition (ESP32-S3 satellite) **or** ReSpeaker 2-mic HAT | Mic array with a **physical mute switch** and LED ring | $40-80 |
| Any speaker (3.5 mm or Bluetooth) | Announcements | existing |

Software: Home Assistant OS, openWakeWord (on-device), Whisper/faster-whisper (local STT),
Piper (local TTS). Audio never leaves your room until a wake word is detected, and even then only
the text goes to the assistant server, over Tailscale.

## How it connects
- Pi joins your Tailscale network. The assistant server joins too. No ports opened at home.
- Server -> room: notifier calls Home Assistant's REST API (`/api/services/tts/speak`) for critical alerts and reminders. Respect sleep mode: only critical speaks at night.
- Room -> server: Home Assistant conversation agent forwards your spoken command text to `POST /api/chat` with the admin token stored in HA secrets.
- Presence: phone on home Wi-Fi (HA companion app) decides room speaker vs push.

## Privacy controls
- Hardware mute switch cuts the mic; LED shows listening state.
- Wake word on-device only. No continuous streaming.
- "Do not disturb" helper in HA that the notifier checks before speaking.

Not built yet. Start after phases 1-5 are stable.
