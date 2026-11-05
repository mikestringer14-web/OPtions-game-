# Lead Intake Assistant

A single page (`index.html`, no install, no server) for filling out the lead sheet by voice or by typing,
classifying the lead, and producing a 3 paragraph write-up for the project consultant.

## Use it
Open `lead-intake/index.html` in Chrome, Edge or Safari. Voice needs mic permission. Over `file://` some browsers
block the mic, so if it won't listen, host the page (GitHub Pages) or run `python3 -m http.server` in this folder and open `http://localhost:8000`.

- **Ask me the questions**: reads each question out loud, listens, fills the field, moves on. Say "skip", "back", "repeat" or "stop". You can type answers in the box instead.
- **Dictate freely**: say the field name then the value, e.g. "first name John phone 905 555 1234 cell city Burlington attic access yes notes ...". Say "notes" last.
- **Classification**: Booking, Future or Referral. It suggests one from the answers (booked date = Booking, lead source referral = Referral, call back or timeline = Future) and you can lock in your own.
- **Write-up tab**: paragraph 1 name, address, phone (cell/home), email. Paragraph 2 job type, lead source, booked date or call back. Paragraph 3 all job details plus anything that affects quoting. Lists anything still missing.
- **Fill from a filled out form**: paste "Field: value" text from a form you already did and it fills everything and rebuilds the write-up.
- **Saved**: leads are stored in this browser only. Export / import JSON to back up or move devices.
