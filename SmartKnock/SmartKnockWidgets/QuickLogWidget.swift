import AppIntents
import SwiftUI
import WidgetKit
import SmartKnockCore

struct CanvassEntry: TimelineEntry {
    let date: Date
    let snapshot: SharedState.Snapshot
    let sessionActive: Bool
    let sessionStart: Date?
    let sharedStorage: Bool
}

struct CanvassProvider: TimelineProvider {
    func placeholder(in context: Context) -> CanvassEntry {
        CanvassEntry(date: Date(), snapshot: .init(doorsToday: 42, bookingsToday: 3, noAnswerToday: 25),
                     sessionActive: true, sessionStart: Date().addingTimeInterval(-5400), sharedStorage: true)
    }

    func getSnapshot(in context: Context, completion: @escaping (CanvassEntry) -> Void) {
        completion(context.isPreview ? placeholder(in: context) : current())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<CanvassEntry>) -> Void) {
        // The app and intents call reloadAllTimelines() after every log, so a
        // slow fallback refresh is enough and saves battery.
        let next = Calendar.current.date(byAdding: .minute, value: 30, to: Date())!
        completion(Timeline(entries: [current()], policy: .after(next)))
    }

    private func current() -> CanvassEntry {
        CanvassEntry(date: Date(), snapshot: SharedState.snapshot, sessionActive: SharedState.sessionActive,
                     sessionStart: SharedState.sessionStart, sharedStorage: AppGroup.isAvailable)
    }
}

/// Home Screen widget. Small: No Answer + counts. Medium: five quickest
/// outcomes. Large: all nine. Booking opens the app for the lead form.
struct QuickLogWidget: Widget {
    let kind = "QuickLogWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: CanvassProvider()) { entry in
            QuickLogWidgetView(entry: entry)
                .containerBackground(Theme.background, for: .widget)
        }
        .configurationDisplayName("Quick Log")
        .description("Log door outcomes without opening the app.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

struct QuickLogWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: CanvassEntry

    var body: some View {
        switch family {
        case .systemSmall: small
        case .systemMedium: medium
        default: large
        }
    }

    private var header: some View {
        HStack(spacing: 6) {
            Image(systemName: entry.sessionActive ? "figure.walk.motion" : "pause.circle")
                .foregroundStyle(entry.sessionActive ? Theme.accent : Theme.textSecondary)
            Text("\(entry.snapshot.doorsToday) doors").font(.caption.bold()).foregroundStyle(.white)
            Text("· \(entry.snapshot.bookingsToday) booked").font(.caption.bold()).foregroundStyle(Outcome.booking.color)
            Spacer(minLength: 0)
        }
    }

    private var currentLine: some View {
        Text(entry.snapshot.currentAddress.isEmpty
             ? (entry.snapshot.lastLoggedAddress.isEmpty ? "No door waiting" : "Last: \(entry.snapshot.lastLoggedAddress)")
             : "Now: \(entry.snapshot.currentAddress)")
            .font(.caption2)
            .foregroundStyle(Theme.textSecondary)
            .lineLimit(1)
    }

    private var small: some View {
        VStack(alignment: .leading, spacing: 6) {
            header
            currentLine
            WidgetOutcomeButton(outcome: .noAnswer, entry: entry, tall: true)
        }
    }

    private var medium: some View {
        VStack(alignment: .leading, spacing: 6) {
            header
            currentLine
            HStack(spacing: 6) {
                WidgetOutcomeButton(outcome: .noAnswer, entry: entry, tall: true)
                VStack(spacing: 6) {
                    HStack(spacing: 6) {
                        WidgetOutcomeButton(outcome: .booking, entry: entry)
                        WidgetOutcomeButton(outcome: .callBack, entry: entry)
                    }
                    HStack(spacing: 6) {
                        WidgetOutcomeButton(outcome: .future, entry: entry)
                        Link(destination: URL(string: "smartknock://log")!) {
                            WidgetTile(title: "More", symbol: "square.grid.3x3.fill", color: Theme.surfaceRaised)
                        }
                    }
                }
            }
        }
    }

    private var large: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            currentLine
            let rows = stride(from: 0, to: Outcome.padOrder.count, by: 3).map { Array(Outcome.padOrder[$0..<min($0 + 3, Outcome.padOrder.count)]) }
            ForEach(rows.indices, id: \.self) { r in
                HStack(spacing: 6) {
                    ForEach(rows[r]) { o in WidgetOutcomeButton(outcome: o, entry: entry, tall: true) }
                }
            }
        }
    }
}

struct WidgetTile: View {
    let title: String
    let symbol: String
    let color: Color
    var tall = false

    var body: some View {
        VStack(spacing: 2) {
            Image(systemName: symbol).font(.system(size: tall ? 18 : 13, weight: .bold))
            Text(title).font(.system(size: tall ? 12 : 10, weight: .heavy)).lineLimit(1).minimumScaleFactor(0.6)
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(color))
    }
}

/// Logs in place via App Intent. Booking (needs the lead form) and setups
/// without a shared App Group open the app instead.
struct WidgetOutcomeButton: View {
    let outcome: Outcome
    let entry: CanvassEntry
    var tall = false

    var body: some View {
        let tile = WidgetTile(title: outcome.shortTitle.uppercased(), symbol: outcome.symbol, color: outcome.color, tall: tall)
        if outcome == .booking || !entry.sharedStorage {
            Link(destination: URL(string: "smartknock://log?outcome=\(outcome.rawValue)")!) { tile }
        } else {
            Button(intent: LogOutcomeIntent(outcome: outcome)) { tile }
                .buttonStyle(.plain)
        }
    }
}

/// Lock Screen widgets.
struct LockScreenWidget: Widget {
    let kind = "LockScreenWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: CanvassProvider()) { entry in
            LockScreenWidgetView(entry: entry)
                .containerBackground(.clear, for: .widget)
        }
        .configurationDisplayName("Door Logger")
        .description("No Answer in one tap, or jump to the logger.")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

struct LockScreenWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: CanvassEntry

    var body: some View {
        switch family {
        case .accessoryCircular:
            if entry.sharedStorage {
                Button(intent: LogOutcomeIntent(outcome: .noAnswer)) {
                    ZStack {
                        AccessoryWidgetBackground()
                        VStack(spacing: 0) {
                            Image(systemName: Outcome.noAnswer.symbol).font(.system(size: 16, weight: .bold))
                            Text("N/A").font(.system(size: 10, weight: .heavy))
                        }
                    }
                }
                .buttonStyle(.plain)
            } else {
                ZStack {
                    AccessoryWidgetBackground()
                    Image(systemName: "door.left.hand.open")
                }
                .widgetURL(URL(string: "smartknock://log"))
            }
        case .accessoryRectangular:
            VStack(alignment: .leading, spacing: 2) {
                Text("Smart Knock").font(.headline).widgetAccentable()
                Text("\(entry.snapshot.doorsToday) doors · \(entry.snapshot.bookingsToday) booked")
                Text(entry.snapshot.currentAddress.isEmpty ? "Tap to log a door" : entry.snapshot.currentAddress)
                    .font(.caption).lineLimit(1)
            }
            .widgetURL(URL(string: "smartknock://log"))
        default:
            Text("\(entry.snapshot.doorsToday) doors · \(entry.snapshot.bookingsToday) booked")
                .widgetURL(URL(string: "smartknock://log"))
        }
    }
}
