import Foundation
#if canImport(ActivityKit)
import ActivityKit

/// Live Activity shown on the Lock Screen and Dynamic Island while canvassing.
struct CanvassActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var doors: Int
        var bookings: Int
        var pending: Int
        /// Address of the door waiting to be logged, if any.
        var currentAddress: String
        var confidence: String
        var isAtDoor: Bool
        var isPaused: Bool
    }

    var sessionStart: Date
}
#endif
