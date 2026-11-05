import SwiftUI
import SwiftData
import UniformTypeIdentifiers
import UserNotifications
import SmartKnockCore

struct SettingsView: View {
    @Environment(\.modelContext) private var context
    @Environment(CanvassEngine.self) private var engine
    @State private var settings = SharedState.settings
    @State private var shareURL: URL?
    @State private var importing = false
    @State private var message: String?
    @State private var confirmDeleteAll = false
    @State private var notificationStatus: UNAuthorizationStatus = .notDetermined

    var body: some View {
        NavigationStack {
            Form {
                permissionsSection
                detectionSection
                addressSection
                promptsSection
                exportSection
                dataSection
                Section("Integrations") {
                    NavigationLink("Knockio") { KnockioSettingsView() }
                }
                Section {
                    Text("Smart Knock stores everything on this iPhone. Nothing is sent to any server unless you share or export it yourself.")
                        .font(.footnote).foregroundStyle(Theme.textSecondary)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Settings")
            .onChange(of: settings) { _, new in
                SharedState.settings = new
                engine.applySettings()
            }
            .task { notificationStatus = await NotificationService.shared.authorizationStatus() }
            .sheet(item: Binding(get: { shareURL.map(ShareableURL.init) }, set: { shareURL = $0?.url })) { item in
                ShareSheet(items: [item.url])
            }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.json]) { result in
                switch result {
                case .success(let url):
                    do {
                        let (added, updated) = try BackupService.restore(from: url, context: context)
                        message = "Restored: \(added) added, \(updated) updated."
                    } catch {
                        message = "Could not read that backup: \(error.localizedDescription)"
                    }
                case .failure(let error):
                    message = error.localizedDescription
                }
            }
            .alert("Smart Knock", isPresented: Binding(get: { message != nil }, set: { if !$0 { message = nil } })) {
                Button("OK") { message = nil }
            } message: { Text(message ?? "") }
            .confirmationDialog("Delete ALL visits, leads and sessions from this iPhone? This cannot be undone.",
                                isPresented: $confirmDeleteAll, titleVisibility: .visible) {
                Button("Delete everything", role: .destructive) {
                    RetentionService.deleteAll(context: context)
                    VisitLogger.refreshSnapshot(lastLogged: nil)
                    message = "All data deleted."
                }
            }
        }
    }

    private var permissionsSection: some View {
        Section {
            LabeledContent("Location", value: locationText)
            if engine.authorization == .notDetermined {
                Button("Allow location") { engine.requestLocationPermission() }
            } else if engine.authorization == .authorizedWhenInUse {
                Button("Allow \"Always\" (recovers if iOS closes the app)") { engine.requestAlwaysPermission() }
            }
            LabeledContent("Precise location", value: engine.isPreciseLocation ? "On" : "Off")
            LabeledContent("Motion", value: MotionService.authorizationStatus == .authorized ? "On" : "Off / not asked")
            LabeledContent("Notifications", value: notificationStatus == .authorized ? "On" : "Off")
            if notificationStatus == .notDetermined {
                Button("Allow notifications") {
                    Task {
                        _ = await NotificationService.shared.requestAuthorization()
                        notificationStatus = await NotificationService.shared.authorizationStatus()
                    }
                }
            }
            Button("Open iPhone Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
            }
        } header: { Text("Permissions") }
    }

    private var locationText: String {
        switch engine.authorization {
        case .authorizedAlways: return "Always"
        case .authorizedWhenInUse: return "While Using"
        case .denied: return "Denied"
        case .restricted: return "Restricted"
        default: return "Not asked"
        }
    }

    private var detectionSection: some View {
        Section {
            slider("Stop radius", value: $settings.detection.dwellRadius, range: 5...20, step: 1, unit: "m")
            slider("Time at door before it counts", value: $settings.detection.minDwellSeconds, range: 8...60, step: 2, unit: "s")
            slider("Walk-away distance", value: $settings.detection.walkingDepartureDistance, range: 6...25, step: 1, unit: "m")
            slider("Max stop (longer = break)", value: Binding(get: { settings.detection.maxDwellSeconds / 60 },
                                                              set: { settings.detection.maxDwellSeconds = $0 * 60 }),
                   range: 5...45, step: 5, unit: "min")
            slider("Ignore GPS worse than", value: $settings.detection.maxAcceptableAccuracy, range: 15...60, step: 5, unit: "m")
            slider("Same-door merge radius", value: $settings.detection.duplicateRadius, range: 4...20, step: 1, unit: "m")
            Button("Reset to defaults") { settings.detection = DetectionConfig() }
        } header: {
            Text("Door detection")
        } footer: {
            Text("If doors are missed, lower \"Time at door\". If you get prompts at mailboxes or while talking to a neighbour, raise it.")
        }
    }

    private var addressSection: some View {
        Section {
            Picker("Lookups per stop", selection: $settings.addressLookupDepth) {
                Text("Fast (1)").tag(1)
                Text("Balanced (3)").tag(3)
                Text("Thorough (5)").tag(5)
            }
            Toggle("Suggest neighbouring numbers", isOn: $settings.suggestNeighborNumbers)
        } header: {
            Text("Address matching")
        } footer: {
            Text("More lookups find the neighbours on each side for faster correction but use more data. Apple limits how many lookups an app can make per minute.")
        }
    }

    private var promptsSection: some View {
        Section {
            Toggle("Prompt when I leave a door", isOn: $settings.promptOnDeparture)
            slider("Prompt cooldown", value: $settings.detection.notificationCooldownSeconds, range: 0...120, step: 5, unit: "s")
            Toggle("Ask for follow-up date", isOn: $settings.askFollowUpDate)
            Toggle("Follow-up reminders", isOn: $settings.followUpReminders)
            Stepper("Default call back: \(settings.defaultCallbackHours) h", value: $settings.defaultCallbackHours, in: 1...336, step: 1)
        } header: { Text("Prompts & reminders") }
    }

    private var exportSection: some View {
        Section {
            Button("Export all as CSV") { export(.csv) }
            Button("Export all as JSON") { export(.json) }
            Button("Today's daily summary") {
                shareURL = try? ExportService.makeFile(.text, visits: ExportService.visits(on: Date(), context: context),
                                                       day: Date(), context: context, markExported: false)
            }
            let counts = SyncQueue.counts(context: context)
            LabeledContent("Unsent", value: "\(counts[.unsent] ?? 0)")
            LabeledContent("Exported", value: "\(counts[.exported] ?? 0)")
            LabeledContent("Synced", value: "\(counts[.synchronized] ?? 0)")
            LabeledContent("Failed", value: "\(counts[.failed] ?? 0)")
        } header: { Text("Export") }
    }

    private var dataSection: some View {
        Section {
            Button("Back up now") { shareURL = try? BackupService.makeBackup(context: context) }
            Button("Restore from backup…") { importing = true }
            Picker("Keep records for", selection: $settings.retentionDays) {
                Text("Forever").tag(0)
                Text("30 days").tag(30)
                Text("90 days").tag(90)
                Text("1 year").tag(365)
            }
            Button("Delete all data", role: .destructive) { confirmDeleteAll = true }
        } header: {
            Text("Backup & privacy")
        } footer: {
            Text("Backups contain customer names and phone numbers. Save them somewhere private, such as your own iCloud Drive.")
        }
    }

    private func export(_ format: ExportService.Format) {
        shareURL = try? ExportService.makeFile(format, visits: ExportService.allVisits(context: context), day: nil, context: context)
    }

    private func slider(_ title: String, value: Binding<Double>, range: ClosedRange<Double>, step: Double, unit: String) -> some View {
        VStack(alignment: .leading) {
            HStack {
                Text(title)
                Spacer()
                Text("\(Int(value.wrappedValue)) \(unit)").foregroundStyle(Theme.textSecondary).monospacedDigit()
            }
            Slider(value: value, in: range, step: step)
        }
    }
}

struct KnockioSettingsView: View {
    @Environment(\.modelContext) private var context
    @State private var token = ""
    @State private var status = KnockioSyncProvider().currentStatus()
    @State private var result: String?

    var body: some View {
        Form {
            Section {
                LabeledContent("Status", value: status.title)
                if case let .awaitingVerification(why) = status {
                    Text(why).font(.footnote).foregroundStyle(Theme.textSecondary)
                }
            }
            Section {
                Text("""
                Smart Knock works fully without Knockio. Automatic sync needs an official, authorized Knockio API or import \
                method that lets your account create these records. Ask your Knockio administrator or Knockio support:
                • Is there a documented API or bulk import for door outcomes and leads?
                • Which fields and status values does it accept?
                • Can a sales-rep account be issued an API key?
                Until that is confirmed, use CSV/JSON export or copy the lead summary into Knockio.
                """)
                .font(.footnote)
            } header: { Text("How sync will work") }
            Section {
                SecureField("API key (only if Knockio issued one to you)", text: $token)
                    .textInputAutocapitalization(.never)
                Button("Save key securely") {
                    KnockioSyncProvider.saveToken(token)
                    token = ""
                    status = KnockioSyncProvider().currentStatus()
                }
                .disabled(token.isEmpty)
                Button("Remove key", role: .destructive) {
                    KnockioSyncProvider.clearToken()
                    status = KnockioSyncProvider().currentStatus()
                }
                Button("Try sync") {
                    Task { result = await SyncQueue.run(provider: KnockioSyncProvider(), mapping: CRMFieldMapping(), context: context) }
                }
                if let result { Text(result).font(.footnote) }
            } header: { Text("Credentials") } footer: {
                Text("Keys are stored in the iPhone Keychain. Smart Knock never logs into the Knockio website on your behalf or works around account permissions.")
            }
        }
        .scrollContentBackground(.hidden)
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("Knockio")
    }
}

struct OnboardingView: View {
    var onDone: () -> Void
    @Environment(CanvassEngine.self) private var engine
    @State private var step = 0

    var body: some View {
        VStack(spacing: 24) {
            Spacer()
            Image(systemName: "door.left.hand.open")
                .font(.system(size: 64, weight: .bold))
                .foregroundStyle(Theme.accent)
            Text("Smart Knock").font(.largeTitle.bold())
            VStack(alignment: .leading, spacing: 14) {
                point("location.fill", "Location", "Detects when you stop at a door and looks up the address. Works in the background while a session is running, with the blue location indicator showing.")
                point("figure.walk", "Motion", "Tells walking from driving so red lights do not count as doors.")
                point("bell.badge.fill", "Notifications", "A quick prompt to log each door after you walk away.")
                point("lock.shield.fill", "Private by default", "All data stays on this iPhone unless you export or share it.")
            }
            .padding(.horizontal)
            Spacer()
            Button {
                engine.requestLocationPermission()
                Task {
                    _ = await NotificationService.shared.requestAuthorization()
                    onDone()
                }
            } label: {
                Text("Allow & Continue").font(.headline).frame(maxWidth: .infinity, minHeight: 54)
            }
            .buttonStyle(.borderedProminent)
            .padding(.horizontal)
            Button("Not now") { onDone() }
                .padding(.bottom)
        }
        .background(Theme.background.ignoresSafeArea())
        .foregroundStyle(Theme.textPrimary)
    }

    private func point(_ symbol: String, _ title: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol).font(.title2).foregroundStyle(Theme.accent).frame(width: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(text).font(.subheadline).foregroundStyle(Theme.textSecondary)
            }
        }
    }
}
