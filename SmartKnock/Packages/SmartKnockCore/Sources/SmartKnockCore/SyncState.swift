import Foundation

/// Where a record stands relative to outside systems.
public enum SyncState: String, CaseIterable, Codable, Sendable {
    /// Saved on the phone only.
    case unsent = "UNSENT"
    /// Included in a CSV/JSON export or shared manually.
    case exported = "EXPORTED"
    /// Confirmed accepted by an authorized CRM integration.
    case synchronized = "SYNCHRONIZED"
    /// An authorized sync attempt failed; will be retried.
    case failed = "FAILED"

    public var title: String {
        switch self {
        case .unsent: return "Unsent"
        case .exported: return "Exported"
        case .synchronized: return "Synced"
        case .failed: return "Failed"
        }
    }
}

/// How sure we are about which house a visit belongs to.
public enum AddressConfidence: String, Codable, CaseIterable, Comparable, Sendable {
    case unresolved = "UNRESOLVED"
    case low = "LOW"
    case medium = "MEDIUM"
    case high = "HIGH"
    /// The rep picked or typed the address themselves.
    case confirmed = "CONFIRMED"

    private var rank: Int {
        switch self {
        case .unresolved: return 0
        case .low: return 1
        case .medium: return 2
        case .high: return 3
        case .confirmed: return 4
        }
    }

    public static func < (lhs: AddressConfidence, rhs: AddressConfidence) -> Bool { lhs.rank < rhs.rank }

    public var title: String {
        switch self {
        case .unresolved: return "Address pending"
        case .low: return "Low confidence"
        case .medium: return "Likely"
        case .high: return "High confidence"
        case .confirmed: return "Confirmed"
        }
    }

    /// True when the rep should be nudged to double-check the address.
    public var needsReview: Bool { self <= .low }
}
