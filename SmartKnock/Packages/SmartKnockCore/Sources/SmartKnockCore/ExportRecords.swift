import Foundation

/// Flat, Codable snapshot of one door visit. This is the stable export/backup
/// format and the shape a future CRM integration maps from.
public struct VisitRecord: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var sessionID: UUID?
    public var timestamp: Date
    public var arrival: Date?
    public var departure: Date?
    public var outcome: Outcome?
    public var address: PostalAddress
    public var addressConfidence: AddressConfidence
    public var latitude: Double
    public var longitude: Double
    public var gpsAccuracy: Double
    public var autoDetected: Bool
    public var notes: String
    public var followUpDate: Date?
    public var syncState: SyncState
    public var lead: LeadRecord?
    public var updatedAt: Date

    public init(id: UUID = UUID(), sessionID: UUID? = nil, timestamp: Date, arrival: Date? = nil, departure: Date? = nil,
                outcome: Outcome?, address: PostalAddress, addressConfidence: AddressConfidence,
                latitude: Double, longitude: Double, gpsAccuracy: Double, autoDetected: Bool,
                notes: String = "", followUpDate: Date? = nil, syncState: SyncState = .unsent,
                lead: LeadRecord? = nil, updatedAt: Date? = nil) {
        self.id = id
        self.sessionID = sessionID
        self.timestamp = timestamp
        self.arrival = arrival
        self.departure = departure
        self.outcome = outcome
        self.address = address
        self.addressConfidence = addressConfidence
        self.latitude = latitude
        self.longitude = longitude
        self.gpsAccuracy = gpsAccuracy
        self.autoDetected = autoDetected
        self.notes = notes
        self.followUpDate = followUpDate
        self.syncState = syncState
        self.lead = lead
        self.updatedAt = updatedAt ?? timestamp
    }
}

public struct LeadRecord: Codable, Equatable, Sendable {
    public var input: LeadInput
    public var summary: String
    public var createdAt: Date

    public init(input: LeadInput, summary: String, createdAt: Date) {
        self.input = input
        self.summary = summary
        self.createdAt = createdAt
    }
}

public struct SessionRecord: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var start: Date
    public var end: Date?
    public var distanceMeters: Double
    public var pausedSeconds: Double

    public init(id: UUID = UUID(), start: Date, end: Date?, distanceMeters: Double, pausedSeconds: Double = 0) {
        self.id = id
        self.start = start
        self.end = end
        self.distanceMeters = distanceMeters
        self.pausedSeconds = pausedSeconds
    }

    public func activeSeconds(now: Date = Date()) -> Double {
        max(0, (end ?? now).timeIntervalSince(start) - pausedSeconds)
    }
}

/// Full-device backup file.
public struct BackupFile: Codable, Equatable, Sendable {
    public static let currentVersion = 1
    public var version: Int
    public var app: String
    public var createdAt: Date
    public var visits: [VisitRecord]
    public var sessions: [SessionRecord]

    public init(createdAt: Date = Date(), visits: [VisitRecord], sessions: [SessionRecord]) {
        self.version = Self.currentVersion
        self.app = "Smart Knock"
        self.createdAt = createdAt
        self.visits = visits
        self.sessions = sessions
    }

    public static func encoder() -> JSONEncoder {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        return e
    }

    public static func decoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }
}

public enum CSVExporter {
    public static let header = [
        "id", "date", "time", "outcome", "house_number", "street", "unit", "city", "province", "postal_code",
        "full_address", "address_confidence", "latitude", "longitude", "gps_accuracy_m", "auto_detected",
        "dwell_seconds", "notes", "follow_up_date", "sync_state",
        "lead_name", "lead_phone", "lead_email", "appointment", "services", "lead_summary"
    ]

    public static func csv(_ records: [VisitRecord], timeZone: TimeZone = .current) -> String {
        let dateF = DateFormatter()
        dateF.locale = Locale(identifier: "en_US_POSIX")
        dateF.timeZone = timeZone
        dateF.dateFormat = "yyyy-MM-dd"
        let timeF = DateFormatter()
        timeF.locale = Locale(identifier: "en_US_POSIX")
        timeF.timeZone = timeZone
        timeF.dateFormat = "HH:mm:ss"
        let stampF = DateFormatter()
        stampF.locale = Locale(identifier: "en_US_POSIX")
        stampF.timeZone = timeZone
        stampF.dateFormat = "yyyy-MM-dd HH:mm"

        var lines = [header.joined(separator: ",")]
        for r in records.sorted(by: { $0.timestamp < $1.timestamp }) {
            let dwell: String
            if let a = r.arrival, let d = r.departure { dwell = String(Int(d.timeIntervalSince(a))) } else { dwell = "" }
            let lead = r.lead?.input
            let appointment: String
            if let date = lead?.appointmentDate {
                appointment = (lead?.hasAppointmentTime ?? false) ? stampF.string(from: date) : dateF.string(from: date)
            } else { appointment = "" }
            let fields: [String] = [
                r.id.uuidString,
                dateF.string(from: r.timestamp),
                timeF.string(from: r.timestamp),
                r.outcome?.rawValue ?? "UNLOGGED",
                r.address.houseNumber, r.address.street, r.address.unit, r.address.city,
                r.address.province, r.address.postalCode, r.address.singleLine,
                r.addressConfidence.rawValue,
                String(format: "%.6f", r.latitude), String(format: "%.6f", r.longitude),
                String(format: "%.0f", r.gpsAccuracy),
                r.autoDetected ? "yes" : "no",
                dwell,
                r.notes,
                r.followUpDate.map { stampF.string(from: $0) } ?? "",
                r.syncState.rawValue,
                lead?.homeownerName ?? "", lead?.phone ?? "", lead?.email ?? "",
                appointment,
                lead?.services.map(\.title).joined(separator: "; ") ?? "",
                r.lead?.summary ?? ""
            ]
            lines.append(fields.map(escape).joined(separator: ","))
        }
        return lines.joined(separator: "\r\n") + "\r\n"
    }

    /// RFC 4180 quoting, plus a leading apostrophe on values that spreadsheets
    /// would otherwise run as formulas.
    public static func escape(_ value: String) -> String {
        var v = value
        if let first = v.first, "=+-@".contains(first), Double(v) == nil {
            v = "'" + v
        }
        if v.contains(",") || v.contains("\"") || v.contains("\n") || v.contains("\r") {
            return "\"" + v.replacingOccurrences(of: "\"", with: "\"\"") + "\""
        }
        return v
    }
}
