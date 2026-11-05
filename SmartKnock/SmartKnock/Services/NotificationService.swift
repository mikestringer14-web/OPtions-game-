import Foundation
import UserNotifications
import SmartKnockCore

/// Actionable "log this door" prompts and follow-up reminders.
///
/// iOS limitation: a notification shows at most a handful of action buttons
/// when long-pressed, so the prompt carries the four quickest outcomes and a
/// "More / Booking" action that opens the full nine-button pad.
@MainActor
final class NotificationService: NSObject {
    static let shared = NotificationService()

    enum Category {
        static let doorVisit = "DOOR_VISIT"
        static let followUp = "FOLLOW_UP"
    }

    enum Action {
        static let openLogger = "OPEN_LOGGER"
        static func outcome(_ o: Outcome) -> String { "LOG_" + o.rawValue }
        static func parseOutcome(_ id: String) -> Outcome? {
            guard id.hasPrefix("LOG_") else { return nil }
            return Outcome(rawValue: String(id.dropFirst(4)))
        }
    }

    static let quickOutcomes: [Outcome] = [.noAnswer, .callBack, .future]

    private var lastPromptAt: Date?

    func registerCategories() {
        var actions: [UNNotificationAction] = Self.quickOutcomes.map {
            UNNotificationAction(identifier: Action.outcome($0), title: $0.title, options: [],
                                 icon: UNNotificationActionIcon(systemImageName: $0.symbol))
        }
        actions.append(UNNotificationAction(identifier: Action.openLogger, title: "Booking / More…",
                                            options: [.foreground],
                                            icon: UNNotificationActionIcon(systemImageName: "square.grid.3x3.fill")))
        let door = UNNotificationCategory(identifier: Category.doorVisit, actions: actions, intentIdentifiers: [],
                                          options: [.customDismissAction])
        let open = UNNotificationAction(identifier: Action.openLogger, title: "Open", options: [.foreground])
        let follow = UNNotificationCategory(identifier: Category.followUp, actions: [open], intentIdentifiers: [], options: [])
        UNUserNotificationCenter.current().setNotificationCategories([door, follow])
    }

    func requestAuthorization() async -> Bool {
        (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    func authorizationStatus() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    /// Prompts the rep to log a door they just walked away from.
    /// Respects the cooldown so a fast walker is not spammed.
    func promptForVisit(id: UUID, address: String, confidence: AddressConfidence, cooldown: Double) {
        let now = Date()
        if let last = lastPromptAt, now.timeIntervalSince(last) < cooldown { return }
        lastPromptAt = now

        let content = UNMutableNotificationContent()
        content.title = "Log door: \(address)"
        content.body = confidence.needsReview
            ? "Address uncertain. Hold to log, or tap to confirm the house."
            : "Hold for quick outcomes, or tap for all nine."
        content.categoryIdentifier = Category.doorVisit
        content.threadIdentifier = "canvass"
        content.userInfo = ["visitID": id.uuidString]
        content.sound = nil
        content.interruptionLevel = .active
        content.relevanceScore = 1
        let request = UNNotificationRequest(identifier: "visit-\(id.uuidString)", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    func clearPrompt(for id: UUID) {
        UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: ["visit-\(id.uuidString)"])
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: ["visit-\(id.uuidString)"])
    }

    func scheduleFollowUp(id: UUID, outcome: Outcome, address: String, at date: Date) {
        cancelFollowUp(id: id)
        guard date > Date() else { return }
        let content = UNMutableNotificationContent()
        content.title = "\(outcome.title): \(address)"
        content.body = "Follow-up due today."
        content.categoryIdentifier = Category.followUp
        content.userInfo = ["visitID": id.uuidString]
        content.sound = .default
        let comps = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: date)
        let trigger = UNCalendarNotificationTrigger(dateMatching: comps, repeats: false)
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "follow-\(id.uuidString)", content: content, trigger: trigger))
    }

    func cancelFollowUp(id: UUID) {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: ["follow-\(id.uuidString)"])
    }
}
