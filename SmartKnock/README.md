# Smart Knock

A native iPhone app for door-to-door reps in roofing, siding, gutters, windows, doors and other exterior work. Start a session and walk. Smart Knock notices when you stop at a door, suggests the address, and asks you to log the outcome with one tap after you walk away. You end the day with a record of every door, tied to its address, that you can export.

Everything is stored on the phone. The app has no sign-up and no server, and it doesn't need Knockio.

---

## 1. What you need

| Item | Notes |
|---|---|
| A Mac | Xcode only runs on macOS. A used Mac mini (M1 or newer) is enough. |
| Xcode 26 or newer | Free from the Mac App Store. |
| An iPhone on iOS 17 or newer | iOS 26 recommended. Precise Location must be on. |
| USB cable or same Wi-Fi | Needed for the first install. |
| Apple ID | A free one works for testing. See section 4 for the limits. |
| Homebrew + XcodeGen | Builds the Xcode project file from `project.yml`. |

---

## 2. Build and install on your iPhone (step by step)

1. **Install the tools** (Terminal on the Mac):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   brew install xcodegen
   ```
2. **Get the code:**
   ```bash
   git clone https://github.com/mikestringer14-web/OPtions-game-.git
   cd OPtions-game-
   git checkout claude/smart-knock-canvassing-app-b6h12b
   cd SmartKnock
   ```
3. **Find your Team ID.** In Xcode, go to Settings, then Accounts, then **+**, then Apple ID, and sign in. Select your team and copy the 10-character Team ID. (On a free account it's listed as "Personal Team".)
4. **Edit `project.yml`.** Change the two lines marked `EDIT`:
   ```yaml
   DEVELOPMENT_TEAM: "AB12CD34EF"              # your Team ID
   BASE_BUNDLE_ID: com.mikestringer.smartknock # anything unique to you
   ```
5. **Generate the project and open it:**
   ```bash
   xcodegen generate
   open SmartKnock.xcodeproj
   ```
6. **Turn on Developer Mode on the iPhone:** go to Settings, then Privacy & Security, then Developer Mode, turn it on, and restart. Connect the phone to the Mac and tap **Trust**.
7. In Xcode's top bar, choose the **SmartKnock** scheme and your iPhone, then press **Run** (⌘R).
8. With a free Apple ID, the first launch fails with "Untrusted Developer". On the phone, go to Settings, then General, then VPN & Device Management, tap your Apple ID, and tap **Trust**. Then run again.
9. On first launch, tap **Allow & Continue** and accept Location ("While Using"), Notifications and Motion. When iOS asks later, choose **Change to Always Allow**. That lets the app recover if iOS closes it partway through a session.
10. **Add the widgets:** long-press the Home Screen, tap **Edit**, then **Add Widget**, then Smart Knock. Add "Quick Log", Large size, for all nine buttons. For the Lock Screen, long-press it, tap **Customize**, and add "Door Logger".
11. **Optional:**
    - **Action Button** (iPhone 15 Pro and later): go to Settings, then Action Button, then Shortcut, then Smart Knock, then "No Answer".
    - **Control Center** (iOS 18 and later): add "Log No Answer".

If the build fails with an **App Groups** error on a free account, see section 4.

---

## 3. Testing before you hit the street

- **Unit tests** for the detection, address, lead summary and export logic. Run these in Terminal:
  ```bash
  cd Packages/SmartKnockCore && swift test
  ```
- **Simulator walk test.** Run the app on an iPhone Simulator. Open the **Debug** menu, then **Location**, then **City Walk**. Start a session. The simulator never really stops, so door detection won't trigger much there. Use **Mark a door here** to test the logging flow.
- **Real test (recommended).** Walk your own street for 10 minutes. Stand at each door for about 25 seconds, then walk to the next one. Check the History tab afterwards. If doors are missed or you get extra prompts, adjust the settings under **Settings, then Door detection**.

---

## 4. Apple account limits (important)

| | Free Apple ID | Apple Developer Program ($129 CAD/year) |
|---|---|---|
| Install on your own iPhone | Yes | Yes |
| App keeps working | **7 days**, then you reconnect and press Run again (your data stays) | 1 year |
| App Groups (widgets share data with the app) | May be refused on some accounts | Yes |
| TestFlight / give to other reps | No | Yes |

**If App Groups is refused on a free account**, the app still works. Widget buttons then open the app instead of logging in place. To do that, delete the `entitlements:` blocks from both targets in `project.yml` and run `xcodegen generate` again.

---

## 5. How it works

```
GPS (Core Location) ─┐
                     ├─► StopDetector ─► stop started ─► address lookup (3 reverse geocodes,
Motion (Core Motion) ┘     (state        along the direction you walked) ─► ranked suggestions
                           machine)      + confidence (High / Likely / Low / Pending)
                               │
                               └─► you walk away ─► prompt (notification / Live Activity / widget)
                                                     │
                              one tap ◄──────────────┘
                                 │
                       SwiftData (encrypted on device) ─► History · Map · Dashboard · CSV/JSON/Daily summary
```

- **Stop detection.** You count as "at a door" when you stay within about 8 m for about 20 s. You've "left" once you walk more than 10 m away at walking pace, or move more than 14 m away regardless of speed. Speeds above 14 km/h, or Core Motion reporting "driving", pause detection. Stops longer than 20 minutes are treated as breaks. All of these values can be changed in Settings.
- **Duplicates.** If you leave a door and come back within 10 minutes, and the new stop is within 8 m of the first, it's merged into one visit. Tapping a second outcome for the same door corrects it. It never creates a second record.
- **Addresses are never assumed.** Phone GPS is usually accurate to 5 to 15 m, which is about one lot width. Each visit shows a confidence badge. The two houses on either side come up as one-tap alternatives. You can fix an address by tapping a suggestion, nudging the number ±2, typing it, searching, or tapping the roof on a satellite map.
- **Offline.** Visits are saved immediately with GPS coordinates. Address lookups that fail without signal are retried automatically when the phone is back online.

### Outcome buttons
No Answer (biggest button), Booking, Call Back, Future, Referral, Previous Customer, Renter, No Soliciting, Other.
- **Booking** opens the lead form.
- **Call Back** and **Future** ask for a follow-up date and schedule a reminder.
- After every log, a 6-second **Undo / Change** bar appears.

### Lead form and voice notes
Tap **Dictate**, then summarize the conversation after you leave the door. Recognition runs on the phone when the iPhone supports it, and no audio is ever saved. Then tap **Fill blank fields from notes**:
- Name, phone, email, services and appointment date are pulled only if you actually said them. Every value is checked against your words.
- On iPhones with Apple Intelligence (iOS 26), Apple's on-device model helps extract details. Nothing leaves the phone.
- The summary is always written as three paragraphs: **Contact Information / Appointment Information / Detailed Job Information**. Missing required details say **"Not provided"**.

---

## 6. What iOS does not allow (and what Smart Knock does instead)

| You asked for | iOS reality | What Smart Knock does |
|---|---|---|
| All nine buttons on the lock screen | Notifications show only a few action buttons. Lock Screen widgets are tiny. | The notification has No Answer / Call Back / Future plus "Booking / More…" (opens the app on the 9-button pad). The **Live Activity** on the Lock Screen has 3 one-tap buttons plus "All". The **Large Home Screen widget** has all 9 buttons. |
| Logging Booking without opening the app | A booking needs the lead form. | Booking always opens the app straight to the form. |
| Exact house from GPS | Not possible to guarantee with phone GPS | Confidence badges, neighbour suggestions and fast correction. "High" is only shown when GPS is accurate to 10 m or better and several lookups agree. |
| Running forever in the background | iOS can end background apps | Uses background location with the blue indicator and a background session. With "Always" permission, iOS relaunches the app and the session resumes. |
| Unlimited address lookups | Apple throttles reverse geocoding (about 50 per minute) | 1, 3 or 5 lookups per stop (setting), a cache, and automatic retry |
| Recording conversations | Consent laws, battery, privacy | Push-to-talk dictation only, with a consent notice. No audio files are kept. |
| Knockio sync | No public Knockio API is confirmed for third-party apps, and rep accounts usually lack API rights | A ready-made sync interface plus a Knockio adapter. It **sends nothing** until Knockio or your admin confirms an authorized API and field list. Until then, use the CSV/JSON export, or Copy the lead summary and paste it into Knockio. |

---

## 7. Knockio integration (Phase 3)

The code is in `SmartKnock/Services/Sync/CRMSync.swift`:
- `CRMSyncProvider` is the interface any CRM adapter implements.
- `KnockioSyncProvider` stores an API key in the Keychain and reports "Awaiting verified access". Its `push()` deliberately rejects every record until a documented API exists.
- `CRMFieldMapping` maps Smart Knock fields and outcome values to Knockio's.
- `SyncQueue` tracks each record as Unsent, Exported, Synced or Failed. Editing a record after export resets it to Unsent.

**Questions to send your Knockio admin / support:**
1. Is there an official API or bulk import for door-knock outcomes and leads?
2. Which record types, fields and status values does it accept?
3. Can a sales-rep account be given an API key, or must an admin push the data?
4. Is a CSV import available? If so, what column template does it need? (Smart Knock's CSV columns can be renamed to match it.)

Once those answers come back, only `push()` and `verifyAccess()` need to be written. The rest of the app stays the same.

---

## 8. Project layout

```
SmartKnock/
├─ project.yml                 XcodeGen definition (edit Team ID + bundle ID)
├─ Packages/SmartKnockCore/    Pure Swift logic + unit tests (no iOS frameworks)
│   ├─ StopDetector.swift      movement → door visits
│   ├─ Address.swift           address ranking, confidence, neighbour numbers
│   ├─ LeadSummary.swift       transcript facts + 3-paragraph summary
│   ├─ ExportRecords.swift     VisitRecord, CSV, backup format
│   └─ Stats.swift             dashboard numbers + daily report text
├─ Shared/                     Compiled into app AND widgets
│   ├─ Models.swift            SwiftData Visit / CanvassSession
│   ├─ Persistence.swift       encrypted store in the App Group
│   ├─ VisitLogger.swift       the single place outcomes are written
│   ├─ Intents.swift           App Intents (widgets, Live Activity, Siri, Action Button)
│   └─ SharedState.swift       settings + widget snapshot
├─ SmartKnock/                 The app
│   ├─ Services/               CanvassEngine, Location, Motion, AddressResolver,
│   │                          Notifications, LiveActivity, Dictation, Export, Sync
│   └─ Views/                  Canvass, Map, History, Dashboard, Settings, Lead form
└─ SmartKnockWidgets/          Home/Lock Screen widgets, Live Activity, Controls
```

## 9. Battery tips
- On a break, tap **Break**. GPS switches to low-power mode.
- Tap **Stop** at the end of the day. A forgotten session closes itself after 4 hours with no movement data.
- A full day of canvassing with GPS uses a lot of battery. Carry a battery pack.
