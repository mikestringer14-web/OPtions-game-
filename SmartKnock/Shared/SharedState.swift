import Foundation
import SmartKnockCore

/// User-adjustable behaviour. Stored as JSON in the App Group defaults so
/// widgets and intents see the same values as the app.
struct AppSettings: Codable, Equatable {
    var detection = DetectionConfig()
    /// Show the "log this door" notification when a visit ends.
    var promptOnDeparture = true
    /// Number of reverse-geocode lookups per stop: 1, 3 or 5.
    var addressLookupDepth = 3
    /// Offer +/-2 neighbouring numbers as estimates.
    var suggestNeighborNumbers = true
    /// Auto-delete visits older than this many days. 0 = keep forever.
    var retentionDays = 0
    /// Default follow-up offset for Call Back, in hours.
    var defaultCallbackHours = 48
    /// Remind about callbacks and future prospects.
    var followUpReminders = true
    /// Voice dictation consent acknowledged.
    var dictationConsentGiven = false
    /// Ask for a quick follow-up date after Call Back / Future.
    var askFollowUpDate = true
}

/// Small key-value state shared between app, widgets, Live Activity and intents.
enum SharedState {
    private static var d: UserDefaults { AppGroup.defaults }

    private enum Key {
        static let settings = "settings.v1"
        static let sessionActive = "session.active"
        static let sessionID = "session.id"
        static let sessionStart = "session.start"
        static let lastLat = "loc.lat"
        static let lastLon = "loc.lon"
        static let lastAcc = "loc.acc"
        static let lastTime = "loc.time"
        static let snapshot = "snapshot.v1"
        static let dataVersion = "data.version"
        static let pendingVisitID = "pending.visit"
    }

    static var settings: AppSettings {
        get {
            guard let data = d.data(forKey: Key.settings),
                  let s = try? JSONDecoder().decode(AppSettings.self, from: data) else { return AppSettings() }
            return s
        }
        set { d.set(try? JSONEncoder().encode(newValue), forKey: Key.settings) }
    }

    static var sessionActive: Bool {
        get { d.bool(forKey: Key.sessionActive) }
        set { d.set(newValue, forKey: Key.sessionActive) }
    }

    static var sessionID: UUID? {
        get { d.string(forKey: Key.sessionID).flatMap(UUID.init(uuidString:)) }
        set { d.set(newValue?.uuidString, forKey: Key.sessionID) }
    }

    static var sessionStart: Date? {
        get { d.object(forKey: Key.sessionStart) as? Date }
        set { d.set(newValue, forKey: Key.sessionStart) }
    }

    /// The visit currently waiting for an outcome (most recent detected stop).
    static var pendingVisitID: UUID? {
        get { d.string(forKey: Key.pendingVisitID).flatMap(UUID.init(uuidString:)) }
        set { d.set(newValue?.uuidString, forKey: Key.pendingVisitID) }
    }

    struct LastLocation {
        var latitude: Double
        var longitude: Double
        var accuracy: Double
        var time: Date
    }

    static var lastLocation: LastLocation? {
        get {
            guard let t = d.object(forKey: Key.lastTime) as? Date else { return nil }
            return LastLocation(latitude: d.double(forKey: Key.lastLat), longitude: d.double(forKey: Key.lastLon),
                                accuracy: d.double(forKey: Key.lastAcc), time: t)
        }
        set {
            guard let v = newValue else { d.removeObject(forKey: Key.lastTime); return }
            d.set(v.latitude, forKey: Key.lastLat)
            d.set(v.longitude, forKey: Key.lastLon)
            d.set(v.accuracy, forKey: Key.lastAcc)
            d.set(v.time, forKey: Key.lastTime)
        }
    }

    /// Bumped every time any process writes visits; the app watches it to
    /// pick up changes made by widgets.
    static var dataVersion: Int {
        get { d.integer(forKey: Key.dataVersion) }
        set { d.set(newValue, forKey: Key.dataVersion) }
    }

    /// Numbers shown on widgets, so the widget never has to open the database.
    struct Snapshot: Codable, Equatable {
        var day: Date = Calendar.current.startOfDay(for: Date())
        var doorsToday = 0
        var bookingsToday = 0
        var noAnswerToday = 0
        var pendingCount = 0
        var lastLoggedAddress = ""
        var lastLoggedOutcome: String?
        var currentAddress = ""
        var currentConfidence = AddressConfidence.unresolved.rawValue
    }

    static var snapshot: Snapshot {
        get {
            guard let data = d.data(forKey: Key.snapshot),
                  var s = try? JSONDecoder().decode(Snapshot.self, from: data) else { return Snapshot() }
            if !Calendar.current.isDateInToday(s.day) {
                s = Snapshot()
            }
            return s
        }
        set { d.set(try? JSONEncoder().encode(newValue), forKey: Key.snapshot) }
    }
}
