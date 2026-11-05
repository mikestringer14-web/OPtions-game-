import AppIntents
import Foundation
import SmartKnockCore

/// AppEnum mirror of Outcome for Shortcuts, Siri, widgets and the Action Button.
enum OutcomeOption: String, AppEnum {
    case booking = "BOOKING"
    case noSoliciting = "NO_SOLICITING"
    case renter = "RENTER"
    case previousCustomer = "PREVIOUS_CUSTOMER"
    case referral = "REFERRAL"
    case future = "FUTURE"
    case callBack = "CALL_BACK"
    case noAnswer = "NO_ANSWER"
    case other = "OTHER"

    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Door Outcome"
    static var caseDisplayRepresentations: [OutcomeOption: DisplayRepresentation] = [
        .booking: "Booking",
        .noSoliciting: "No Soliciting",
        .renter: "Renter",
        .previousCustomer: "Previous Customer",
        .referral: "Referral",
        .future: "Future",
        .callBack: "Call Back",
        .noAnswer: "No Answer",
        .other: "Other"
    ]

    var outcome: Outcome { Outcome(rawValue: rawValue)! }

    init(_ outcome: Outcome) { self = OutcomeOption(rawValue: outcome.rawValue)! }
}

/// Logs an outcome for the current door without opening the app.
/// Conforming to LiveActivityIntent lets it run from Live Activity buttons and
/// makes the system run it in the app's process when the app is alive.
struct LogOutcomeIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Log Door Outcome"
    static var description = IntentDescription("Records the result for the door you just visited.")
    static var openAppWhenRun: Bool = false

    @Parameter(title: "Outcome", default: .noAnswer)
    var outcome: OutcomeOption

    init() {}

    init(outcome: Outcome) {
        self.outcome = OutcomeOption(outcome)
    }

    static var parameterSummary: some ParameterSummary {
        Summary("Log \(\.$outcome)")
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let result = try VisitLogger.log(outcome.outcome)
        return .result(dialog: "\(outcome.outcome.title) logged for \(result.addressText).")
    }
}

/// Opens the app straight onto the logging pad (used where nine buttons
/// will not fit, and for Booking which needs the lead form).
struct OpenLoggerIntent: AppIntent {
    static var title: LocalizedStringResource = "Open Door Logger"
    static var description = IntentDescription("Opens Smart Knock on the logging screen.")
    static var openAppWhenRun: Bool = true

    @Parameter(title: "Outcome")
    var outcome: OutcomeOption?

    init() {}

    init(outcome: Outcome?) {
        self.outcome = outcome.map(OutcomeOption.init)
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        AppGroup.defaults.set(outcome?.rawValue ?? "OPEN", forKey: "launch.request")
        return .result()
    }
}
