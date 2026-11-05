import SwiftUI
import SwiftData
import SmartKnockCore

struct HistoryView: View {
    @Environment(\.modelContext) private var context
    @Environment(CanvassEngine.self) private var engine
    @Query(sort: \Visit.createdAt, order: .reverse) private var visits: [Visit]
    @State private var filter: Outcome?
    @State private var searchText = ""
    @State private var showUnloggedOnly = false
    @State private var exportURL: URL?

    private var filtered: [Visit] {
        visits.filter { v in
            if showUnloggedOnly && !v.isPending { return false }
            if let f = filter, v.outcome != f { return false }
            if !searchText.isEmpty {
                let hay = (v.address.singleLine + " " + v.notes + " " + (v.lead?.input.homeownerName ?? "")).lowercased()
                if !hay.contains(searchText.lowercased()) { return false }
            }
            return true
        }
    }

    private struct DayGroup: Identifiable {
        let day: Date
        let items: [Visit]
        var id: Date { day }
    }

    private var grouped: [DayGroup] {
        let dict = Dictionary(grouping: filtered) { Calendar.current.startOfDay(for: $0.createdAt) }
        return dict.keys.sorted(by: >).map { DayGroup(day: $0, items: dict[$0]!) }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack {
                            filterChip(nil, title: "All")
                            Button {
                                showUnloggedOnly.toggle()
                            } label: {
                                Text("Not logged").font(.caption.bold())
                                    .padding(.horizontal, 10).padding(.vertical, 6)
                                    .background(Capsule().fill(showUnloggedOnly ? Theme.accent : Theme.surfaceRaised))
                            }
                            ForEach(Outcome.padOrder) { o in filterChip(o, title: o.title) }
                        }
                    }
                    .listRowBackground(Color.clear)
                }
                ForEach(grouped) { group in
                    let day = group.day
                    let items = group.items
                    Section {
                        ForEach(items) { v in
                            NavigationLink(value: v.id) { VisitRow(visit: v) }
                                .swipeActions(edge: .trailing) {
                                    Button(role: .destructive) { engine.delete(v) } label: { Label("Delete", systemImage: "trash") }
                                }
                                .swipeActions(edge: .leading) {
                                    Button { engine.log(.noAnswer, visitID: v.id) } label: { Label("No Answer", systemImage: Outcome.noAnswer.symbol) }
                                        .tint(Outcome.noAnswer.color)
                                }
                        }
                    } header: {
                        HStack {
                            Text(day, format: .dateTime.weekday(.wide).month().day())
                            Spacer()
                            Text("\(items.filter { !$0.isPending }.count) doors")
                            Menu {
                                Button("Daily summary (text)") { exportDay(day, .text) }
                                Button("CSV") { exportDay(day, .csv) }
                                Button("JSON") { exportDay(day, .json) }
                                Button("Copy summary") {
                                    ExportService.copyToClipboard(ExportService.dailySummaryText(for: day, context: context))
                                }
                            } label: { Image(systemName: "square.and.arrow.up") }
                        }
                    }
                }
                if visits.isEmpty {
                    ContentUnavailableView("No doors yet", systemImage: "door.left.hand.open",
                                           description: Text("Start canvassing or tap an outcome to log your first door."))
                        .listRowBackground(Color.clear)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.background.ignoresSafeArea())
            .searchable(text: $searchText, prompt: "Address, name or note")
            .navigationTitle("History")
            .navigationDestination(for: UUID.self) { VisitDetailView(visitID: $0) }
            .sheet(item: Binding(get: { exportURL.map(ShareableURL.init) }, set: { exportURL = $0?.url })) { item in
                ShareSheet(items: [item.url])
            }
        }
    }

    private func filterChip(_ o: Outcome?, title: String) -> some View {
        Button {
            filter = o
        } label: {
            Text(title).font(.caption.bold())
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(Capsule().fill(filter == o ? (o?.color ?? Theme.accent) : Theme.surfaceRaised))
        }
        .buttonStyle(.plain)
    }

    private func exportDay(_ day: Date, _ format: ExportService.Format) {
        let items = ExportService.visits(on: day, context: context)
        exportURL = try? ExportService.makeFile(format, visits: items, day: day, context: context)
    }
}

struct VisitRow: View {
    let visit: Visit
    var body: some View {
        HStack(spacing: 10) {
            Circle().fill(visit.outcome?.color ?? Theme.textSecondary).frame(width: 12, height: 12)
            VStack(alignment: .leading, spacing: 2) {
                Text(visit.displayAddress).font(.body.weight(.semibold)).lineLimit(1)
                HStack(spacing: 6) {
                    Text(visit.outcome?.title ?? "Not logged").font(.caption).foregroundStyle(visit.outcome?.color ?? Theme.warning)
                    if visit.confidence.needsReview {
                        Text("· check address").font(.caption).foregroundStyle(Theme.warning)
                    }
                    if visit.lead != nil {
                        Image(systemName: "person.text.rectangle").font(.caption).foregroundStyle(Theme.accent)
                    }
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(visit.timestamp, style: .time).font(.caption).foregroundStyle(Theme.textSecondary)
                Text(visit.syncState.title).font(.caption2).foregroundStyle(Theme.textSecondary)
            }
        }
    }
}

struct ShareableURL: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}

/// UIKit share sheet (works for files on every iOS version).
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}

/// View and edit one visit.
struct VisitDetailView: View {
    let visitID: UUID
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @Environment(CanvassEngine.self) private var engine
    @Environment(AppRouter.self) private var router
    @Query private var visits: [Visit]
    @State private var showPicker = false
    @State private var confirmDelete = false

    init(visitID: UUID) {
        self.visitID = visitID
        _visits = Query(filter: #Predicate<Visit> { $0.id == visitID })
    }

    var body: some View {
        Group {
            if let v = visits.first {
                content(v)
            } else {
                ContentUnavailableView("Visit deleted", systemImage: "trash")
            }
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("Door")
        .navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder
    private func content(_ v: Visit) -> some View {
        @Bindable var v = v
        Form {
            Section("Address") {
                Button { showPicker = true } label: {
                    HStack {
                        VStack(alignment: .leading) {
                            Text(v.displayAddress).font(.headline).foregroundStyle(.white)
                            if !v.address.line2.isEmpty { Text(v.address.line2).font(.caption).foregroundStyle(Theme.textSecondary) }
                        }
                        Spacer()
                        ConfidenceBadge(confidence: v.confidence)
                    }
                }
                LabeledContent("GPS", value: String(format: "%.5f, %.5f (±%.0f m)", v.latitude, v.longitude, max(v.gpsAccuracy, 0)))
                    .font(.caption)
            }
            Section("Outcome") {
                Picker("Outcome", selection: Binding(get: { v.outcome }, set: { new in
                    if let new {
                        let r = engine.log(new, visitID: v.id)
                        if new == .booking && v.lead == nil { router.didLog(new, result: r) }
                    }
                })) {
                    Text("Not logged").tag(Outcome?.none)
                    ForEach(Outcome.padOrder) { o in Text(o.title).tag(Outcome?.some(o)) }
                }
                if let o = v.outcome, o.wantsFollowUp || v.followUpDate != nil {
                    DatePicker("Follow-up", selection: Binding(get: { v.followUpDate ?? Date() }, set: {
                        v.followUpDate = $0
                        v.touch()
                        try? context.save()
                        engine.scheduleFollowUpIfNeeded(v)
                    }))
                }
                if v.outcome == .booking || v.lead != nil {
                    Button(v.lead == nil ? "Add lead details" : "Edit lead details") { router.leadVisitID = v.id }
                }
            }
            Section("Notes") {
                TextField("Notes", text: $v.notes, axis: .vertical)
                    .lineLimit(2...8)
                    .onSubmit { v.touch(); try? context.save() }
            }
            if let lead = v.lead {
                Section("Lead summary") {
                    Text(lead.summary).font(.callout).textSelection(.enabled)
                }
            }
            Section("Details") {
                if let a = v.arrival { LabeledContent("Arrived", value: a.formatted(date: .omitted, time: .shortened)) }
                if let d = v.departure { LabeledContent("Left", value: d.formatted(date: .omitted, time: .shortened)) }
                LabeledContent("Detected", value: v.autoDetected ? "Automatically" : "Manually")
                LabeledContent("Sync", value: v.syncState.title)
            }
            Section {
                Button { ExportService.copyToClipboard(ExportService.visitSummary(v)) } label: {
                    Label("Copy summary", systemImage: "doc.on.doc")
                }
                ShareLink(item: ExportService.visitSummary(v)) { Label("Share", systemImage: "square.and.arrow.up") }
                Button(role: .destructive) { confirmDelete = true } label: { Label("Delete visit", systemImage: "trash") }
            }
        }
        .scrollContentBackground(.hidden)
        .onDisappear { try? context.save() }
        .sheet(isPresented: $showPicker) { AddressPickerView(visit: v) }
        .confirmationDialog("Delete this visit?", isPresented: $confirmDelete) {
            Button("Delete", role: .destructive) { engine.delete(v); dismiss() }
        }
    }
}
