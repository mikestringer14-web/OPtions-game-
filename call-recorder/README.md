# Voice Notes — quick call recorder & transcriber

A home-screen web app for recording calls (via speakerphone) and getting
transcripts, built because iOS gives no app access to the live audio of a
cellular call — the only thing any app on iPhone can legally/technically
capture is room audio through the microphone, which means the call has to
be on speaker while it records.

## How it works

- Big red button, nothing else on screen. Tap to start, tap to stop.
- Recordings are saved **only on your phone**, in the browser's local
  storage (IndexedDB) — nothing is uploaded anywhere automatically.
- Tap "Transcribe" on a recording to send it to OpenAI's Whisper API using
  your own API key (set in Settings). That's the only network request the
  app ever makes, and only when you trigger it.
- Optional passcode lock on the app itself (Settings → App passcode).
- Export any recording or transcript to Files/Messages/etc. via the share
  sheet.

## One-time setup (10 minutes)

### 1. Host it (needed for microphone access + installability)
Safari only allows microphone access to pages served over HTTPS, so it
needs to be hosted somewhere — easiest free option is GitHub Pages:

1. On this repo on GitHub: **Settings → Pages**
2. Under "Build and deployment", choose **Deploy from a branch**
3. Branch: `claude/phone-call-recorder-transcripts-0e4ym1` (or `main` after
   merging), folder: `/call-recorder` if offered, otherwise `/ (root)` and
   move this folder to the repo root
4. Save — GitHub gives you a URL like
   `https://<username>.github.io/OPtions-game-/call-recorder/`

(Netlify Drop or Vercel work too if you'd rather not use Pages — just drag
the `call-recorder` folder onto their upload page.)

### 2. Add it to your Home Screen
Open the hosted URL in **Safari** on your iPhone → Share button → **Add to
Home Screen**. It now opens full-screen, no browser bar, like a real app.
Name/icon shown is "Voice Notes" with a plain blue dot — rename it to
anything you like from the same Add to Home Screen dialog.

### 3. (Optional) Get an OpenAI API key for transcripts
Create one at platform.openai.com/api-keys, paste it into the app's
Settings tab. Cost is about $0.006/minute of audio — a 5 minute call costs
about 3 cents.

### 4. Make it launch instantly from anywhere (Shortcuts)
1. Open the **Shortcuts** app → **+** → Add Action → **Open URLs**
2. Set the URL to your hosted address with `?record=1` appended, e.g.
   `https://<username>.github.io/OPtions-game-/call-recorder/?record=1`
3. Name the shortcut, tap the **(i)** info button → **Add to Home Screen**
   for a one-tap icon, and/or assign it to the **Action Button** (iPhone 15
   Pro+) or a **Back Tap** gesture (Settings → Accessibility → Touch → Back
   Tap) for the fastest possible trigger.
4. With `?record=1`, the app skips straight to recording on open — one tap
   (or one back-tap) and it's already capturing audio.

If you set an app passcode, the shortcut will stop at the lock screen
first — that's the security/speed trade-off; leave the passcode off if you
want the absolute fastest launch.

## During a call

Answer normally, tap **Speaker**, then launch Voice Notes (or your
Shortcut) and tap record. Talk normally — the phone mic will pick up both
sides through the speaker.

## What this can't hide, because Apple doesn't allow it

- iOS shows a small microphone/orange-dot indicator in the status bar and
  Control Center any time an app (including this one, running as a web
  app) is using the mic. There's no way for any app to suppress this — it's
  an OS-level privacy indicator.
- The call itself is visibly on speakerphone.

## Legal note

Ontario/Canada is a one-party consent jurisdiction (Criminal Code s.
184(2)(a)) — you can lawfully record a call you are personally a
participant in without telling the other party. This only covers calls
you're actually on; it doesn't extend to recording conversations you
aren't a party to, and doesn't override any separate wiretap/consent rules
that may apply if you're calling into a jurisdiction with two-party
consent requirements. This is general information, not legal advice.

## Data & backups

Everything lives in this browser's local storage on this device only.
Clearing Safari's site data, running low on storage, or deleting the app
from Home Screen (in some cases) can wipe recordings — use the Export
button on anything you want to keep permanently, and save it to Files or
another app.
