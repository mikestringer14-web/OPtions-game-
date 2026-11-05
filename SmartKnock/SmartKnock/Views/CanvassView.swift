import SwiftUI
import SwiftData
import CoreLocation
import SmartKnockCore

/// Main walking screen: session status, the current door, and the outcome pad.
struct CanvassView: View {
    @Environment(CanvassEngine.self) private var engine
    @Environment(AppRouter.self) private var router
    @Environment(\.modelContext) private var context
    @Query(sort: \Visit.createdAt, order: .reverse) private var allVisits: [Visit]
    @State private var showStopConfirm = false
    @State private var addressPickerVisit: Visit?
    @State private var now = Date()

    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var todays: [Visit] {
        let start = Calendar.current.startOfDay(for: Date())
        return allVisits.filter { $0.createdAt >= start }
    }

    private var currentVisit: Visit? {
        guard let id = engine.pendingVisitID else { return nil }
        return allVisits.first { $0.id == id && $0.isPending }
    }

    private var unloggedStops: [Visit] {
        todays.filter { $0.isPending && $0.id != engine.pendingVisitID }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 14) {
                    if engine.authorization == .denied || engine.authorization == .restricted {
                        PermissionBanner()
                    } else if !engine.isPreciseLocation {
                        Card {
                            Label("Precise Location is off", systemImage: "location.slash")
                                .font(.headline).foregroundStyle(Theme.warning)
                            Text("Without Precise Location the app cannot tell neighbouring houses apart.")
                                .font(.subheadline).foregroundStyle(Theme.textSecondary)
                            Button("Turn on Precise Location") { engine.requestPrecise() }
                                .buttonStyle(.borderedProminent)
                        }
                    }

                    sessionHeader

                    if engine.isActive || currentVisit != nil {
                        currentDoorCard
                    }

                    OutcomePad(highlighted: nil) { outcome in
                        logTapped(outcome)
                    }
                    .opacity(engine.isPaused ? 0.5 : 1)

                    if !unloggedStops.isEmpty { unloggedSection }

                    recentSection
                }
                .padding(.horizontal, 14)
                .padding(.bottom, 90)
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Smart Knock")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { GPSIndicator(accuracy: engine.isActive ? engine.currentAccuracy : nil) }
            }
            .overlay(alignment: .bottom) { undoToast }
            .sheet(item: $addressPickerVisit) { v in AddressPickerView(visit: v) }
            .confirmationDialog("End today's canvassing session?", isPresented: $showStopConfirm, titleVisibility: .visible) {
                Button("End Session", role: .destructive) { engine.stop() }
            }
            .onReceive(timer) { now = $0 }
        }
    }

    // MARK: Sections

    private var sessionHeader: some View {
        VStack(spacing: 12) {
            HStack(spacing: 10) {
                StatTile(title: "Doors today", value: "\(todays.filter { !$0.isPending }.count)", symbol: "door.left.hand.open")
                StatTile(title: "Bookings", value: "\(todays.filter { $0.outcome == .booking }.count)",
                         tint: Outcome.booking.color, symbol: "calendar.badge.checkmark")
            }
            if engine.isActive {
                HStack(spacing: 10) {
                    StatTile(title: engine.isPaused ? "On break" : "Session", value: sessionDuration,
                             tint: engine.isPaused ? Theme.warning : Theme.accent, symbol: "timer")
                    StatTile(title: "Walked", value: engine.distanceMeters.kmString, symbol: "figure.walk")
                }
            }
            HStack(spacing: 10) {
                if engine.isActive {
                    Button {
                        engine.togglePause()
                    } label: {
                        Label(engine.isPaused ? "Resume" : "Break", systemImage: engine.isPaused ? "play.fill" : "pause.fill")
                            .frame(maxWidth: .infinity, minHeight: 52)
                    }
                    .buttonStyle(.bordered)
                    .tint(Theme.warning)
                    Button(role: .destructive) {
                        showStopConfirm = true
                    } label: {
                        Label("Stop", systemImage: "stop.fill").frame(maxWidth: .infinity, minHeight: 52)
                    }
                    .buttonStyle(.bordered)
                } else {
                    Button {
                        engine.start()
                    } label: {
                        Label("Start Canvassing", systemImage: "figure.walk.motion")
                            .font(.title3.bold())
                            .frame(maxWidth: .infinity, minHeight: 60)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Theme.accent)
                }
            }
        }
    }

    private var sessionDuration: String {
        guard let start = engine.sessionStart else { return "0h 00m" }
        _ = now
        return (engine.currentSession()?.activeSeconds(now: now) ?? now.timeIntervalSince(start)).durationString
    }

    private var currentDoorCard: some View {
        Card {
            HStack {
                Text(engine.isAtDoor ? "AT DOOR" : (currentVisit != nil ? "LAST STOP: LOG IT" : "WALKING"))
                    .font(.caption.weight(.heavy))
                    .foregroundStyle(engine.isAtDoor ? Theme.success : Theme.accent)
                Spacer()
                if let v = currentVisit {
                    if engine.resolvingIDs.contains(v.id) {
                        ProgressView().controlSize(.small)
                    } else {
                        ConfidenceBadge(confidence: v.confidence)
                    }
                }
            }
            if let v = currentVisit {
                Button {
                    addressPickerVisit = v
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(v.displayAddress).font(.title2.bold()).foregroundStyle(.white)
                            Text(v.confidence.needsReview ? "Tap to confirm the house" : "Tap to change")
                                .font(.caption).foregroundStyle(Theme.textSecondary)
                        }
                        Spacer()
                        Image(systemName: "pencil.circle.fill").font(.title2).foregroundStyle(Theme.accent)
                    }
                }
                let alternatives = v.candidates.filter { $0.address.matchKey != v.address.matchKey }.prefix(3)
                if !alternatives.isEmpty && v.confidence != .confirmed {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack {
                            ForEach(Array(alternatives)) { c in
                                Button {
                                    engine.setAddress(c.address, for: v)
                                } label: {
                                    Text(c.address.line1 + (c.source == .estimatedNeighbor ? " (est.)" : ""))
                                        .font(.subheadline.weight(.semibold))
                                        .padding(.horizontal, 12).padding(.vertical, 8)
                                        .background(Capsule().fill(Theme.surfaceRaised))
                                }
                            }
                        }
                    }
                }
                if engine.isAtDoor {
                    Button("Done at this door") { engine.finishCurrentDoor() }
                        .font(.subheadline.weight(.semibold))
                }
            } else if engine.isActive {
                Text(engine.isPaused ? "Paused. Detection is off during breaks." : "Walk to the next door. Smart Knock will pick up the stop.")
                    .font(.subheadline).foregroundStyle(Theme.textSecondary)
                Button {
                    engine.markDoorHere()
                } label: {
                    Label("Mark a door here", systemImage: "mappin.and.ellipse")
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.bordered)
            }
        }
    }

    private var unloggedSection: some View {
        Card {
            Text("Stops not logged (\(unloggedStops.count))").font(.headline)
            ForEach(unloggedStops.prefix(5)) { v in
                Button {
                    router.loggerVisitID = v.id
                } label: {
                    HStack {
                        Text(v.displayAddress).foregroundStyle(.white)
                        Spacer()
                        Text(v.createdAt, style: .time).font(.caption).foregroundStyle(Theme.textSecondary)
                        Image(systemName: "chevron.right").foregroundStyle(Theme.textSecondary)
                    }
                    .padding(.vertical, 4)
                }
            }
        }
    }

    private var recentSection: some View {
        let recent = todays.filter { !$0.isPending }.prefix(6)
        return Group {
            if !recent.isEmpty {
                Card {
                    Text("Recent").font(.headline)
                    ForEach(Array(recent)) { v in
                        Button {
                            router.detailVisitID = v.id
                        } label: {
                            HStack {
                                OutcomeChip(outcome: v.outcome)
                                Text(v.displayAddress).foregroundStyle(.white).lineLimit(1)
                                Spacer()
                                if v.confidence.needsReview {
                                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Theme.warning)
                                }
                                Text(v.timestamp, style: .time).font(.caption).foregroundStyle(Theme.textSecondary)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder private var undoToast: some View {
        if let last = engine.lastLog,
           let v = allVisits.first(where: { $0.id == last.visitID }), let o = v.outcome {
            HStack(spacing: 12) {
                Image(systemName: o.symbol).foregroundStyle(o.color)
                VStack(alignment: .leading, spacing: 0) {
                    Text("\(o.title) logged").font(.subheadline.bold())
                    Text(v.displayAddress).font(.caption).foregroundStyle(Theme.textSecondary).lineLimit(1)
                }
                Spacer()
                Button("Change") { router.detailVisitID = v.id; engine.lastLog = nil }
                Button("Undo") { engine.undoLastLog() }.bold()
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 14).fill(Theme.surfaceRaised).shadow(radius: 8))
            .padding(.horizontal, 14)
            .padding(.bottom, 8)
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .task(id: last.visitID) {
                try? await Task.sleep(nanoseconds: 6_000_000_000)
                if engine.lastLog?.visitID == last.visitID { engine.lastLog = nil }
            }
        }
    }

    private func logTapped(_ outcome: Outcome) {
        if engine.pendingVisitID == nil {
            // No detected stop waiting: create the door at the current GPS fix so
            // it gets a fresh position and address lookup.
            engine.markDoorHere()
        }
        let result = engine.log(outcome, visitID: engine.pendingVisitID)
        router.didLog(outcome, result: result)
    }
}

struct PermissionBanner: View {
    var body: some View {
        Card {
            Label("Location access is off", systemImage: "location.slash.fill")
                .font(.headline).foregroundStyle(Theme.danger)
            Text("Smart Knock needs location to detect doors. You can still log manually, but addresses will not be filled in.")
                .font(.subheadline).foregroundStyle(Theme.textSecondary)
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
            }
            .buttonStyle(.borderedProminent)
        }
    }
}

/// Full logger for one specific visit (from a notification or the unlogged list).
struct LoggerSheet: View {
    let visitID: UUID
    @Environment(CanvassEngine.self) private var engine
    @Environment(AppRouter.self) private var router
    @Environment(\.dismiss) private var dismiss
    @Query private var visits: [Visit]
    @State private var showPicker = false

    init(visitID: UUID) {
        self.visitID = visitID
        _visits = Query(filter: #Predicate<Visit> { $0.id == visitID })
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                if let v = visits.first {
                    VStack(spacing: 14) {
                        Card {
                            HStack {
                                Text(v.displayAddress).font(.title2.bold())
                                Spacer()
                                ConfidenceBadge(confidence: v.confidence)
                            }
                            Button("Change address") { showPicker = true }
                        }
                        OutcomePad(highlighted: v.outcome) { o in
                            let r = engine.log(o, visitID: v.id)
                            dismiss()
                            router.didLog(o, result: r)
                        }
                        Button(role: .destructive) {
                            engine.delete(v)
                            dismiss()
                        } label: {
                            Label("Not a door, discard this stop", systemImage: "trash")
                        }
                        .padding(.top, 6)
                    }
                    .padding(14)
                    .sheet(isPresented: $showPicker) { AddressPickerView(visit: v) }
                } else {
                    ContentUnavailableView("Visit not found", systemImage: "questionmark.circle")
                }
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Log Door")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
        }
    }
}
