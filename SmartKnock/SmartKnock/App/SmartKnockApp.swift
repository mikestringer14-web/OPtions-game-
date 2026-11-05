import SwiftUI
import SwiftData
import UserNotifications
import SmartKnockCore

@main
struct SmartKnockApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @State private var router = AppRouter.shared
    @State private var engine = CanvassEngine.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(engine)
                .environment(router)
                .modelContainer(Persistence.container)
                .preferredColorScheme(.dark)
                .tint(Theme.accent)
                .onOpenURL { router.handle(url: $0) }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                engine.sceneBecameActive()
                router.consumeLaunchRequest()
            }
        }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        // Also runs on background relaunch (location key), which resumes an
        // active session after iOS terminated the app.
        MainActor.assumeIsolated {
            CanvassEngine.shared.bootstrap()
        }
        return true
    }

    // Show door prompts as banners even in the foreground only when useful.
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async
        -> UNNotificationPresentationOptions {
        if notification.request.content.categoryIdentifier == NotificationService.Category.doorVisit {
            return [.list]   // The in-app pad is already on screen.
        }
        return [.banner, .list, .sound]
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        let info = response.notification.request.content.userInfo
        let visitID = (info["visitID"] as? String).flatMap(UUID.init(uuidString:))
        let action = response.actionIdentifier
        await MainActor.run {
            if let outcome = NotificationService.Action.parseOutcome(action) {
                CanvassEngine.shared.log(outcome, visitID: visitID)
                if outcome.wantsFollowUp, let id = visitID {
                    // Default follow-up was applied; schedule its reminder.
                    if let v = VisitLogger.fetchVisit(id, in: Persistence.container.mainContext) {
                        CanvassEngine.shared.scheduleFollowUpIfNeeded(v)
                    }
                }
            } else if action == NotificationService.Action.openLogger || action == UNNotificationDefaultActionIdentifier {
                if let id = visitID {
                    if response.notification.request.content.categoryIdentifier == NotificationService.Category.followUp {
                        AppRouter.shared.detailVisitID = id
                    } else {
                        AppRouter.shared.loggerVisitID = id
                    }
                }
            }
        }
    }
}

/// Navigation state shared by deep links, notifications and intents.
@MainActor
@Observable
final class AppRouter {
    static let shared = AppRouter()

    enum Tab: Hashable { case canvass, map, history, dashboard, settings }

    var tab: Tab = .canvass
    /// Full nine-button logger for a specific visit.
    var loggerVisitID: UUID?
    /// Booking lead form.
    var leadVisitID: UUID?
    /// Quick follow-up date picker.
    var followUpVisitID: UUID?
    /// Visit detail / edit screen.
    var detailVisitID: UUID?

    /// After any outcome is logged from the UI, open the right follow-up screen.
    func didLog(_ outcome: Outcome, result: VisitLogger.Result?) {
        guard let id = result?.visitID else { return }
        loggerVisitID = nil
        if outcome == .booking {
            leadVisitID = id
        } else if outcome.wantsFollowUp && SharedState.settings.askFollowUpDate {
            followUpVisitID = id
        }
    }

    /// smartknock://log, smartknock://log?outcome=BOOKING, smartknock://visit?id=UUID
    func handle(url: URL) {
        guard url.scheme == "smartknock" else { return }
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let value = { (name: String) in items.first(where: { $0.name == name })?.value }
        switch url.host {
        case "log":
            tab = .canvass
            if let raw = value("outcome"), let outcome = Outcome(rawValue: raw) {
                let r = CanvassEngine.shared.log(outcome, visitID: value("visit").flatMap(UUID.init(uuidString:)))
                didLog(outcome, result: r)
            } else if let pending = CanvassEngine.shared.pendingVisitID {
                loggerVisitID = pending
            }
        case "visit":
            if let id = value("id").flatMap(UUID.init(uuidString:)) { detailVisitID = id }
        default:
            tab = .canvass
        }
    }

    /// Picks up a request written by OpenLoggerIntent.
    func consumeLaunchRequest() {
        let d = AppGroup.defaults
        guard let raw = d.string(forKey: "launch.request") else { return }
        d.removeObject(forKey: "launch.request")
        tab = .canvass
        if let outcome = Outcome(rawValue: raw) {
            let r = CanvassEngine.shared.log(outcome)
            didLog(outcome, result: r)
        } else if let pending = CanvassEngine.shared.pendingVisitID {
            loggerVisitID = pending
        }
    }
}
