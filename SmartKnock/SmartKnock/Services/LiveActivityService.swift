import ActivityKit
import Foundation

/// Starts, updates and ends the canvassing Live Activity.
/// If the rep has Live Activities turned off, every call is a quiet no-op.
@MainActor
final class LiveActivityService {
    private var activity: Activity<CanvassActivityAttributes>?
    private var lastState: CanvassActivityAttributes.ContentState?

    var isEnabledBySystem: Bool { ActivityAuthorizationInfo().areActivitiesEnabled }

    func start(sessionStart: Date, state: CanvassActivityAttributes.ContentState) {
        // Re-attach to an activity left over from before a relaunch.
        if let existing = Activity<CanvassActivityAttributes>.activities.first {
            activity = existing
            update(state)
            return
        }
        guard isEnabledBySystem else { return }
        let attributes = CanvassActivityAttributes(sessionStart: sessionStart)
        activity = try? Activity.request(attributes: attributes,
                                         content: ActivityContent(state: state, staleDate: nil),
                                         pushType: nil)
        lastState = state
    }

    func update(_ state: CanvassActivityAttributes.ContentState) {
        guard let activity, state != lastState else { return }
        lastState = state
        Task { await activity.update(ActivityContent(state: state, staleDate: nil)) }
    }

    func end() {
        let all = Activity<CanvassActivityAttributes>.activities
        activity = nil
        lastState = nil
        Task {
            for a in all { await a.end(nil, dismissalPolicy: .immediate) }
        }
    }
}
