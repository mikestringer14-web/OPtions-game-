# Canvassing Tracker

Tracks canvassing employees' movement during a shift, prompts a 2-tap
outcome log the moment they leave a house, draws the neighborhood as
house-by-house outlines colored by outcome, and emails management a
PDF/report at the end of the day. Includes a privacy auto-shutoff that
stops GPS tracking the instant a device is detected leaving the
neighborhood at driving speed.

This lives in its own `canvassing-app/` folder inside this repo and is
unrelated to the options-trading simulator at the repo root - the two
don't share code.

## What's real vs. what needs setup

Every feature described below is implemented in code and has been
typechecked and smoke-tested (backend fully, including a live clock-in →
visit-log → PDF-generation run). What's **not** done for you, because it
needs accounts/credentials only you can provide:

- A Google Maps API key (free tier covers this easily)
- Real SMTP credentials for the auto-email (a Gmail app password works)
- An Apple Developer account ($99/yr) to get the app permanently onto an
  iPhone or into the App Store - see "Getting this onto your iPhone" below
  for how to test it *before* paying for that
- Real building-footprint data for your specific neighborhood (falls back
  to auto-generated squares until you add it - see "House outlines" below)

## Architecture

```
canvassing-app/
  server/   Node + Express + Prisma (SQLite) backend
  mobile/   Expo (React Native + TypeScript) iOS/Android app
```

**Why Expo instead of native Swift:** you don't have a Mac, and Xcode
only runs on macOS - there's no way to compile or test a native Swift app
without one. Expo is a TypeScript/React Native framework that:
1. You can test immediately on your own iPhone via the free **Expo Go**
   app or a custom dev build, no Mac needed.
2. Can be compiled into a real installable `.ipa` / App Store build using
   Expo's cloud build service (**EAS Build**), which runs on Expo's
   servers, not your machine.

The tradeoff: background location on iOS is more restricted for
Expo-managed apps than for a from-scratch native app, and full custom
native UI is a bit more limited. For this app's actual needs (background
GPS, geofencing, maps, push-style prompts), Expo's `expo-location` +
`expo-task-manager` cover everything used here.

## Outcome options on the quick-action prompt

Your 4, plus 4 more I added because they come up constantly in real
canvassing and matter for legal/compliance and crew safety:

| Outcome | Why it's there |
|---|---|
| Not Home / Left Door Hanger | your original list |
| Home - Booked Quote | your original list |
| Home - Not Qualified/Interested | your original list |
| Tenant - No Owner Present | your original list |
| **Do Not Contact** | If someone says "don't come back" / has a no-soliciting sign and you knock anyway, that's a real legal exposure (municipal solicitation bylaws, harassment complaints). This flags the house so it's permanently excluded from future routes. |
| **Callback Requested** | Distinct from "booked" - they want to talk but not right now. Without this bucket these get miscoded as "not qualified" and you lose real leads. |
| **Vacant / Under Construction** | So these don't keep getting re-knocked every canvass, and so management can tell "no answer" apart from "nobody lives there." |
| **Skipped - Unsafe** | Dog, hostile response, etc. Distinct from "not interested" so a pattern of unsafe addresses is visible to management, not buried. |

The first 4 show on the main sheet (matches your original 2-tap ask); the
other 4 are one more tap away under "More options" so the default flow
stays exactly 2 taps. Reorder which 4 are primary in
`mobile/src/types.ts` (`PRIMARY_OUTCOMES` / `SECONDARY_OUTCOMES`).

## How the privacy auto-shutoff actually decides "left in a car"

You asked for detection "by the speed and [location] relevant to the
houses being canvassed." Implemented as: GPS speed reported by the phone
(`CLLocation.speed` under the hood) has to be **above ~25 km/h AND the
device has to be outside the neighborhood's drawn boundary polygon**, for
3 consecutive samples in a row (~24 seconds), before tracking stops. Both
conditions together, confirmed repeatedly, avoids two failure modes:
walking fast down a long driveway won't trip it (no speed), and a single
bad GPS fix reporting a speed spike won't trip it either (needs 3 in a
row). See `mobile/src/services/autoPause.ts` and the constants in
`mobile/src/config.ts` if you want to tune the thresholds.

There is deliberately **no license plate reading** - that would need a
camera pointed at the road and raises its own privacy/legal questions,
and speed + boundary-exit already answers "did they leave the
neighborhood in a vehicle" reliably without it.

## House outlines (the 2D building shapes on the map)

`House.footprintGeoJson` holds a polygon. Two ways to populate it with
real building shapes instead of the auto-generated fallback square:

1. **OpenStreetMap building footprints (free)** - query the [Overpass
   API](https://overpass-turbo.eu/) for `way["building"]` within your
   neighborhood's bounding box, which returns real building outlines for
   most residential areas already. Feed the resulting polygons into
   `POST /api/houses/import`.
2. **Google Maps Building Insights (paid, more coverage/detail)** -
   https://developers.google.com/maps/documentation/building-insights

Until you do either, houses render as a ~9m generated square centered on
the address's geocoded lat/lng (`server/src/services/geofence.ts`) - good
enough to test the whole flow, not a real building shape.

## Setup

### 1. Backend

```bash
cd canvassing-app/server
npm install
cp .env.example .env      # fill in a real API_KEY, SMTP creds, Google Maps key
npx prisma migrate dev --name init
npm run seed               # creates one test area + 3 houses + 2 employees (PINs 1234 / 9999)
npm run dev                 # http://localhost:4000
```

Generate a real `API_KEY` with:
```bash
node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"
```

For the auto-email: a Gmail address with an **App Password** (not your
normal password - generate one at
https://myaccount.google.com/apppasswords, requires 2FA enabled) works
as `SMTP_USER`/`SMTP_PASS`. Any other SMTP provider (Outlook, SendGrid,
etc.) works the same way.

Deploy the backend somewhere reachable from your phone - Railway,
Render, or Fly.io all have free tiers that work fine for this; for
production, also switch `prisma/schema.prisma`'s datasource from SQLite
to Postgres (one-line change, all your free-tier hosts above offer a
Postgres addon).

### 2. Mobile app - getting this onto your iPhone without a Mac

```bash
cd canvassing-app/mobile
npm install
cp .env.example .env       # point EXPO_PUBLIC_API_URL at your deployed backend
```

**To test right now, free, no Apple account needed:**
1. Install **Expo Go** from the App Store on your iPhone.
2. `npx expo start` on your computer, scan the QR code with your iPhone
   camera. The app loads live.
3. Caveat: Expo Go can't run true background location (iOS restricts
   that to apps built with a dev client). Foreground tracking, the map,
   outcome logging, and clock-in/out all work fully in Expo Go - only the
   "keeps tracking while the screen is off or app is backgrounded" part
   needs step 2 below.

**To test full background tracking (still free, still no Mac):**
1. Sign up for a free Expo account at https://expo.dev.
2. `npx eas build --profile development --platform ios` - this builds a
   custom dev client on Expo's cloud servers. First iOS build without an
   Apple Developer account uses Expo's "ad hoc" signing, which is enough
   to install on your own phone for testing (install link/QR shows in the
   terminal when the build finishes).

**To actually publish to the App Store** (so it's a normal app icon, no
dev tooling needed to open it, and you can hand phones to a whole crew):
you need a $99/yr Apple Developer account. Then `eas build --platform ios
--profile production` and `eas submit`. This is the only step in the
whole project that costs money and requires an Apple account - everything
else above is free.

### Apple's review of "Always" location access

Apple requires an in-app explanation before requesting background
location (already written into `app.json`'s `infoPlist` /
`NSLocationAlwaysAndWhenInUseUsageDescription`), and App Store review
specifically checks that background location is justified by the app's
actual function. "Tracks employee location and auto-stops when they
leave the work site" is a well-established, approvable justification
(same category as delivery/field-service apps) - just make sure your
App Store listing description says plainly what it tracks and why,
since Apple checks that the listing matches the permission's stated use.

## Employee-tracking disclosure

You're building something that tracks people's real-time location during
work hours. Before rolling this out to a crew: tell them clearly, in
writing, that it's happening, what's tracked (location + house-visit
outcomes, only while clocked in), what's NOT tracked (auto-pauses the
moment they leave the work site), and who sees the data. Depending on
your province/state, written notice or even written consent may be a
legal requirement for workplace location tracking, not just a courtesy -
worth a quick check with whoever handles HR/compliance before this goes
live with real employees.

## API reference (backend)

All routes except `/health` require header `x-api-key: <your API_KEY>`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/sessions/clock-in` | `{employeeId, pinCode, areaId}` → starts a WorkSession |
| POST | `/api/sessions/:id/clock-out` | Manual end of shift |
| POST | `/api/sessions/:id/auto-pause` | Called by the app when the privacy auto-shutoff fires |
| POST | `/api/sessions/:id/track-points` | Batched GPS point upload |
| GET | `/api/houses?areaId=` | All houses + current status for the map |
| POST | `/api/houses/import` | Bulk-load houses/addresses for an area |
| GET | `/api/areas/:id` | Area name + boundary polygon + manager emails |
| POST | `/api/visits` | Logs one house outcome (what the quick-action sheet calls) |
| GET | `/api/visits?areaId=&date=` | Raw visit list |
| POST | `/api/reports/daily/:areaId/:date/send` | Generates the PDF and emails the area's manager list |
| GET | `/api/reports/daily/:areaId/:date` | Downloads the PDF directly |

## Automatic end-of-day email

`POST /api/reports/daily/:areaId/:date/send` does the generate-and-email
in one call. Nothing in this repo currently calls it automatically on a
schedule - wire it to whichever trigger fits how your crew actually
works, for example:
- A cron job (e.g. `node-cron` in `server/src/index.ts`) firing at a
  fixed end-of-shift time.
- Calling it from `sessionsRouter`'s clock-out handler once you confirm
  every employee clocked into that area+date is either clocked out or
  auto-paused.

Left as a manual trigger for now rather than guessing your crew's actual
schedule - a wrong automatic trigger (firing while someone's still
working) is worse than a manager tapping a "send report" button.
