import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit
import SmartKnockCore

/// Lock Screen + Dynamic Island while a session is running. The three
/// buttons log instantly via LiveActivityIntent; "All" opens the full pad.
struct CanvassLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: CanvassActivityAttributes.self) { context in
            LockScreenActivityView(context: context)
                .activityBackgroundTint(Theme.background)
                .activitySystemActionForegroundColor(.white)
                .widgetURL(URL(string: "smartknock://log"))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Label("\(context.state.doors)", systemImage: "door.left.hand.open").font(.headline)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Label("\(context.state.bookings)", systemImage: "calendar.badge.checkmark")
                        .font(.headline).foregroundStyle(Outcome.booking.color)
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(context.state.currentAddress.isEmpty ? "Walking" : context.state.currentAddress)
                        .font(.subheadline.bold()).lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    ActivityButtons(state: context.state)
                }
            } compactLeading: {
                Label("\(context.state.doors)", systemImage: "door.left.hand.open").font(.caption.bold())
            } compactTrailing: {
                if context.state.pending > 0 || !context.state.currentAddress.isEmpty {
                    Image(systemName: "hand.tap.fill").foregroundStyle(Theme.accent)
                } else {
                    Text("\(context.state.bookings)").foregroundStyle(Outcome.booking.color).font(.caption.bold())
                }
            } minimal: {
                Text("\(context.state.doors)").font(.caption.bold())
            }
            .widgetURL(URL(string: "smartknock://log"))
            .keylineTint(Theme.accent)
        }
    }
}

struct LockScreenActivityView: View {
    let context: ActivityViewContext<CanvassActivityAttributes>

    var body: some View {
        let s = context.state
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: s.isPaused ? "pause.circle.fill" : "figure.walk.motion")
                    .foregroundStyle(s.isPaused ? Theme.warning : Theme.accent)
                Text("\(s.doors) doors").font(.headline)
                Text("· \(s.bookings) booked").font(.headline).foregroundStyle(Outcome.booking.color)
                Spacer()
                Text(context.attributes.sessionStart, style: .timer)
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(Theme.textSecondary)
                    .multilineTextAlignment(.trailing)
                    .frame(width: 70)
            }
            HStack(spacing: 6) {
                if !s.currentAddress.isEmpty {
                    let conf = AddressConfidence(rawValue: s.confidence) ?? .unresolved
                    Image(systemName: conf.symbol).foregroundStyle(conf.color)
                    Text((s.isAtDoor ? "At " : "Log: ") + s.currentAddress).font(.subheadline.bold()).lineLimit(1)
                } else {
                    Text(s.isPaused ? "On break" : "Walking to the next door").font(.subheadline).foregroundStyle(Theme.textSecondary)
                }
                Spacer()
            }
            ActivityButtons(state: s)
        }
        .padding(14)
        .foregroundStyle(.white)
    }
}

struct ActivityButtons: View {
    let state: CanvassActivityAttributes.ContentState

    var body: some View {
        HStack(spacing: 6) {
            ForEach([Outcome.noAnswer, .callBack, .future]) { o in
                Button(intent: LogOutcomeIntent(outcome: o)) {
                    Label(o.shortTitle, systemImage: o.symbol)
                        .font(.caption.bold())
                        .lineLimit(1)
                        .frame(maxWidth: .infinity, minHeight: 34)
                }
                .tint(o.color)
                .buttonStyle(.borderedProminent)
            }
            Link(destination: URL(string: "smartknock://log")!) {
                Label("All", systemImage: "square.grid.3x3.fill")
                    .font(.caption.bold())
                    .frame(maxWidth: .infinity, minHeight: 34)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Theme.accent))
            }
        }
    }
}
