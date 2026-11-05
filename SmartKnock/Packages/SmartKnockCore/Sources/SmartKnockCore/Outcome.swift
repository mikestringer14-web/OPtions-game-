import Foundation

/// The nine door outcomes. Raw values are stable and used in storage and exports,
/// so never rename an existing case's raw value.
public enum Outcome: String, CaseIterable, Codable, Identifiable, Sendable {
    case booking = "BOOKING"
    case noSoliciting = "NO_SOLICITING"
    case renter = "RENTER"
    case previousCustomer = "PREVIOUS_CUSTOMER"
    case referral = "REFERRAL"
    case future = "FUTURE"
    case callBack = "CALL_BACK"
    case noAnswer = "NO_ANSWER"
    case other = "OTHER"

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .booking: return "Booking"
        case .noSoliciting: return "No Soliciting"
        case .renter: return "Renter"
        case .previousCustomer: return "Previous Customer"
        case .referral: return "Referral"
        case .future: return "Future"
        case .callBack: return "Call Back"
        case .noAnswer: return "No Answer"
        case .other: return "Other"
        }
    }

    /// Short label that fits on a small widget button.
    public var shortTitle: String {
        switch self {
        case .booking: return "Book"
        case .noSoliciting: return "No Sol."
        case .renter: return "Renter"
        case .previousCustomer: return "Prev. Cust"
        case .referral: return "Referral"
        case .future: return "Future"
        case .callBack: return "Call Back"
        case .noAnswer: return "No Answer"
        case .other: return "Other"
        }
    }

    public var detail: String {
        switch self {
        case .booking: return "Appointment successfully scheduled"
        case .noSoliciting: return "Property has a no-soliciting restriction"
        case .renter: return "Occupant rents the property"
        case .previousCustomer: return "Occupant reports prior service from the company"
        case .referral: return "Potential lead referred by a homeowner"
        case .future: return "May be interested in future work"
        case .callBack: return "Return visit or follow-up requested"
        case .noAnswer: return "Nobody answered the door"
        case .other: return "Any other result"
        }
    }

    /// SF Symbol name.
    public var symbol: String {
        switch self {
        case .booking: return "calendar.badge.checkmark"
        case .noSoliciting: return "hand.raised.fill"
        case .renter: return "key.fill"
        case .previousCustomer: return "star.fill"
        case .referral: return "person.2.fill"
        case .future: return "clock.arrow.circlepath"
        case .callBack: return "phone.arrow.up.right.fill"
        case .noAnswer: return "door.left.hand.closed"
        case .other: return "ellipsis.circle.fill"
        }
    }

    /// Hex colour used for buttons and map markers (high contrast on charcoal).
    public var hexColor: String {
        switch self {
        case .booking: return "#22C55E"        // green
        case .noSoliciting: return "#EF4444"   // red
        case .renter: return "#A855F7"         // purple
        case .previousCustomer: return "#EAB308" // gold
        case .referral: return "#14B8A6"       // teal
        case .future: return "#3B82F6"         // blue
        case .callBack: return "#F97316"       // orange
        case .noAnswer: return "#64748B"       // slate
        case .other: return "#94A3B8"          // light slate
        }
    }

    /// Whether this outcome counts as someone answering the door.
    public var isContact: Bool {
        switch self {
        case .noAnswer, .noSoliciting: return false
        default: return true
        }
    }

    /// Outcomes that should ask for a follow-up date and create a reminder.
    public var wantsFollowUp: Bool {
        self == .callBack || self == .future
    }

    /// Display order on the logging pad. No Answer comes first and is the biggest button.
    public static let padOrder: [Outcome] = [
        .noAnswer, .booking, .callBack,
        .future, .referral, .previousCustomer,
        .renter, .noSoliciting, .other
    ]
}
