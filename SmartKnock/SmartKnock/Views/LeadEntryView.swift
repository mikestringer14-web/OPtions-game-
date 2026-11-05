import SwiftUI
import SwiftData
import SmartKnockCore

/// Fast booking form. Dictate a summary, let the app fill blanks from it,
/// review, and save the three-paragraph lead summary.
struct LeadEntryView: View {
    let visitID: UUID
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var context
    @Query private var visits: [Visit]
    @StateObject private var dictation = SpeechDictationService()
    @State private var input = LeadInput()
    @State private var hasDate = false
    @State private var suggestionNote: String?
    @State private var showConsent = false
    @State private var loaded = false
    @State private var copied = false

    private let formatter = LeadSummaryFormatter()

    init(visitID: UUID) {
        self.visitID = visitID
        _visits = Query(filter: #Predicate<Visit> { $0.id == visitID })
    }

    private var visit: Visit? { visits.first }

    var body: some View {
        NavigationStack {
            Form {
                dictationSection
                Section("Contact") {
                    TextField("Homeowner name", text: $input.homeownerName)
                        .textContentType(.name).textInputAutocapitalization(.words)
                    TextField("Phone number", text: $input.phone)
                        .keyboardType(.phonePad).textContentType(.telephoneNumber)
                    TextField("Email (optional)", text: $input.email)
                        .keyboardType(.emailAddress).textInputAutocapitalization(.never)
                    TextField("Full property address", text: $input.address, axis: .vertical)
                }
                Section("Appointment") {
                    Toggle("Appointment date set", isOn: $hasDate)
                    if hasDate {
                        DatePicker("Date", selection: dateBinding, displayedComponents: .date)
                        Toggle("Specific time", isOn: $input.hasAppointmentTime)
                        if input.hasAppointmentTime {
                            DatePicker("Time", selection: dateBinding, displayedComponents: .hourAndMinute)
                        }
                    }
                }
                Section("Services requested") {
                    ServiceGrid(selected: $input.services)
                    if input.services.contains(.other) {
                        TextField("Describe other service", text: $input.otherServiceDescription)
                    }
                }
                Section("Details") {
                    TextField("Project details", text: $input.projectDetails, axis: .vertical).lineLimit(2...6)
                    TextField("Additional notes", text: $input.notes, axis: .vertical).lineLimit(1...4)
                    TextField("Referral source", text: $input.referralSource)
                    TextField("Follow-up requirements", text: $input.followUp, axis: .vertical)
                }
                summarySection
            }
            .scrollContentBackground(.hidden)
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Booking")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Later") { save(); dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { save(); dismiss() }.bold() }
            }
            .onAppear(perform: load)
            .alert("Voice notes", isPresented: $showConsent) {
                Button("I understand") {
                    var s = SharedState.settings
                    s.dictationConsentGiven = true
                    SharedState.settings = s
                    Task { await dictation.start(appendingTo: input.transcript) }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Dictation only listens while you hold it on, and no audio is saved. Use it to summarize the conversation after you leave the door. Do not record a homeowner without their permission.")
            }
            .onChange(of: dictation.transcript) { _, t in
                if dictation.isRecording || !t.isEmpty { input.transcript = t }
            }
        }
    }

    private var dateBinding: Binding<Date> {
        Binding(get: { input.appointmentDate ?? defaultAppointment() },
                set: { input.appointmentDate = $0 })
    }

    private func defaultAppointment() -> Date {
        let tomorrow = Calendar.current.date(byAdding: .day, value: 1, to: Date())!
        return Calendar.current.date(bySettingHour: 18, minute: 0, second: 0, of: tomorrow) ?? tomorrow
    }

    private var dictationSection: some View {
        Section {
            Button {
                if dictation.isRecording {
                    dictation.stop()
                } else if SharedState.settings.dictationConsentGiven {
                    Task { await dictation.start(appendingTo: input.transcript) }
                } else {
                    showConsent = true
                }
            } label: {
                Label(dictation.isRecording ? "Stop dictation" : "Dictate conversation summary",
                      systemImage: dictation.isRecording ? "stop.circle.fill" : "mic.circle.fill")
                    .font(.headline)
                    .foregroundStyle(dictation.isRecording ? Theme.danger : Theme.accent)
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            if dictation.isRecording {
                Label(dictation.isOnDevice ? "Listening (on-device)" : "Listening", systemImage: "waveform")
                    .foregroundStyle(Theme.danger)
            }
            TextField("Transcript (editable)", text: $input.transcript, axis: .vertical)
                .lineLimit(3...10)
            if !input.transcript.isEmpty && !dictation.isRecording {
                Button {
                    Task { await applySuggestions() }
                } label: {
                    Label("Fill blank fields from notes", systemImage: "wand.and.stars")
                }
            }
            if let note = suggestionNote {
                Text(note).font(.caption).foregroundStyle(Theme.warning)
            }
            if let err = dictation.errorMessage {
                Text(err).font(.caption).foregroundStyle(Theme.danger)
            }
        } header: {
            Text("Voice notes")
        } footer: {
            Text("Only facts that appear in your notes are used. Anything missing is marked \"Not provided\".")
        }
    }

    private var summarySection: some View {
        let missing = formatter.missingMandatoryFields(input)
        let summary = formatter.summary(for: input, bookedAt: visit?.loggedAt ?? Date())
        return Section {
            if !missing.isEmpty {
                Label("Missing: " + missing.joined(separator: ", "), systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.warning)
            }
            Text(summary)
                .font(.callout)
                .textSelection(.enabled)
            HStack {
                Button {
                    ExportService.copyToClipboard(summary)
                    copied = true
                } label: { Label(copied ? "Copied" : "Copy", systemImage: "doc.on.doc") }
                .buttonStyle(.bordered)
                Spacer()
                ShareLink(item: summary) { Label("Share", systemImage: "square.and.arrow.up") }
                    .buttonStyle(.bordered)
            }
        } header: {
            Text("Lead summary")
        }
    }

    private func load() {
        guard !loaded, let v = visit else { return }
        loaded = true
        if let existing = v.lead {
            input = existing.input
        } else {
            input.address = v.address.isEmpty ? "" : v.address.singleLine
            input.notes = v.notes
        }
        hasDate = input.appointmentDate != nil
    }

    private func applySuggestions() async {
        let s = await LeadStructurer.suggest(from: input.transcript)
        var filled: [String] = []
        if input.homeownerName.isEmpty, let n = s.name { input.homeownerName = n; filled.append("name") }
        if input.phone.isEmpty, let p = s.phone { input.phone = p; filled.append("phone") }
        if input.email.isEmpty, let e = s.email { input.email = e; filled.append("email") }
        if input.services.isEmpty, !s.services.isEmpty { input.services = s.services; filled.append("services") }
        if input.appointmentDate == nil, let d = s.appointmentDate {
            input.appointmentDate = d
            input.hasAppointmentTime = s.hasTime
            hasDate = true
            filled.append("appointment")
        }
        suggestionNote = filled.isEmpty
            ? "Nothing new found in the notes."
            : "Filled \(filled.joined(separator: ", "))\(s.usedOnDeviceModel ? " (Apple on-device model)" : ""). Please check them."
    }

    private func save() {
        guard let v = visit else { return }
        if dictation.isRecording { dictation.stop() }
        if !hasDate { input.appointmentDate = nil; input.hasAppointmentTime = false }
        let summary = formatter.summary(for: input, bookedAt: v.loggedAt ?? Date())
        v.lead = LeadRecord(input: input, summary: summary, createdAt: v.lead?.createdAt ?? Date())
        try? context.save()
        VisitLogger.refreshSnapshot(lastLogged: v)
    }
}

struct ServiceGrid: View {
    @Binding var selected: [ServiceType]
    private let columns = [GridItem(.adaptive(minimum: 104), spacing: 8)]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 8) {
            ForEach(ServiceType.allCases) { s in
                let on = selected.contains(s)
                Button {
                    if on { selected.removeAll { $0 == s } } else { selected.append(s) }
                } label: {
                    Text(s.title)
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 38)
                        .foregroundStyle(on ? .white : Theme.textSecondary)
                        .background(RoundedRectangle(cornerRadius: 10).fill(on ? Theme.accent : Theme.surfaceRaised))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.vertical, 4)
    }
}

/// Quick "when should I follow up?" picker after Call Back / Future.
struct FollowUpSheet: View {
    let visitID: UUID
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var context
    @Environment(CanvassEngine.self) private var engine
    @Query private var visits: [Visit]
    @State private var date = Date()
    @State private var note = ""

    init(visitID: UUID) {
        self.visitID = visitID
        _visits = Query(filter: #Predicate<Visit> { $0.id == visitID })
    }

    var body: some View {
        NavigationStack {
            Form {
                if let v = visits.first {
                    Section {
                        HStack {
                            OutcomeChip(outcome: v.outcome)
                            Text(v.displayAddress)
                        }
                    }
                    Section("Follow up") {
                        HStack {
                            quick("Tomorrow", days: 1)
                            quick("3 days", days: 3)
                            quick("1 week", days: 7)
                            quick(v.outcome == .future ? "3 months" : "2 weeks", days: v.outcome == .future ? 90 : 14)
                        }
                        DatePicker("Date & time", selection: $date)
                        TextField("Note (best time, who to ask for)", text: $note, axis: .vertical)
                    }
                }
            }
            .navigationTitle("Follow-up")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Skip") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { save() }.bold() }
            }
            .onAppear {
                if let v = visits.first {
                    date = v.followUpDate ?? Calendar.current.date(byAdding: .day, value: v.outcome == .future ? 30 : 2, to: Date())!
                }
            }
        }
    }

    private func quick(_ title: String, days: Int) -> some View {
        Button(title) {
            let d = Calendar.current.date(byAdding: .day, value: days, to: Date())!
            date = Calendar.current.date(bySettingHour: 17, minute: 30, second: 0, of: d) ?? d
        }
        .buttonStyle(.bordered)
        .font(.caption)
    }

    private func save() {
        guard let v = visits.first else { dismiss(); return }
        v.followUpDate = date
        if !note.isEmpty { v.notes = v.notes.isEmpty ? note : v.notes + "\n" + note }
        v.touch()
        try? context.save()
        engine.scheduleFollowUpIfNeeded(v)
        dismiss()
    }
}
