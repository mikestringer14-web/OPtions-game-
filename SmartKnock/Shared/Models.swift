import Foundation
import SwiftData
import SmartKnockCore

/// One door. Created when a stop is detected (outcome nil = "waiting to be logged")
/// or when the rep logs manually.
@Model
final class Visit {
    @Attribute(.unique) var id: UUID = UUID()
    var sessionID: UUID?
    var createdAt: Date = Date()
    var arrival: Date?
    var departure: Date?
    var loggedAt: Date?
    var outcomeRaw: String?
    var houseNumber: String = ""
    var street: String = ""
    var unit: String = ""
    var city: String = ""
    var province: String = ""
    var postalCode: String = ""
    var confidenceRaw: String = AddressConfidence.unresolved.rawValue
    var latitude: Double = 0
    var longitude: Double = 0
    var gpsAccuracy: Double = -1
    var approachBearing: Double?
    var autoDetected: Bool = false
    var notes: String = ""
    var followUpDate: Date?
    var syncStateRaw: String = SyncState.unsent.rawValue
    /// JSON-encoded [AddressCandidate].
    var candidatesData: Data?
    /// JSON-encoded LeadRecord, set for bookings (and optionally referrals).
    var leadData: Data?
    var updatedAt: Date = Date()
    var addressLookupAttempts: Int = 0
    /// True after the "log this door" prompt has been shown.
    var promptSent: Bool = false

    init(id: UUID = UUID(), sessionID: UUID?, latitude: Double, longitude: Double, accuracy: Double, autoDetected: Bool) {
        self.id = id
        self.sessionID = sessionID
        self.latitude = latitude
        self.longitude = longitude
        self.gpsAccuracy = accuracy
        self.autoDetected = autoDetected
        self.createdAt = Date()
        self.updatedAt = Date()
    }

    // MARK: Typed accessors

    var outcome: Outcome? {
        get { outcomeRaw.flatMap(Outcome.init(rawValue:)) }
        set { outcomeRaw = newValue?.rawValue; touch() }
    }

    var confidence: AddressConfidence {
        get { AddressConfidence(rawValue: confidenceRaw) ?? .unresolved }
        set { confidenceRaw = newValue.rawValue }
    }

    var syncState: SyncState {
        get { SyncState(rawValue: syncStateRaw) ?? .unsent }
        set { syncStateRaw = newValue.rawValue }
    }

    var address: PostalAddress {
        get { PostalAddress(houseNumber: houseNumber, street: street, unit: unit, city: city, province: province, postalCode: postalCode) }
        set {
            houseNumber = newValue.houseNumber
            street = newValue.street
            unit = newValue.unit
            city = newValue.city
            province = newValue.province
            postalCode = newValue.postalCode
            touch()
        }
    }

    var candidates: [AddressCandidate] {
        get {
            guard let data = candidatesData else { return [] }
            return (try? JSONDecoder().decode([AddressCandidate].self, from: data)) ?? []
        }
        set { candidatesData = try? JSONEncoder().encode(newValue) }
    }

    var lead: LeadRecord? {
        get {
            guard let data = leadData else { return nil }
            return try? BackupFile.decoder().decode(LeadRecord.self, from: data)
        }
        set {
            leadData = newValue.flatMap { try? BackupFile.encoder().encode($0) }
            touch()
        }
    }

    var displayAddress: String {
        let a = address
        if a.isEmpty { return String(format: "Near %.5f, %.5f", latitude, longitude) }
        return a.line1
    }

    var isPending: Bool { outcomeRaw == nil }

    /// Time used for "today" grouping and sorting.
    var timestamp: Date { loggedAt ?? departure ?? arrival ?? createdAt }

    func touch() {
        updatedAt = Date()
        // Any edit after export/sync means the outside copy is stale.
        if syncState == .exported || syncState == .synchronized { syncState = .unsent }
    }

    var record: VisitRecord {
        VisitRecord(id: id, sessionID: sessionID, timestamp: timestamp, arrival: arrival, departure: departure,
                    outcome: outcome, address: address, addressConfidence: confidence,
                    latitude: latitude, longitude: longitude, gpsAccuracy: gpsAccuracy,
                    autoDetected: autoDetected, notes: notes, followUpDate: followUpDate,
                    syncState: syncState, lead: lead, updatedAt: updatedAt)
    }

    func apply(_ r: VisitRecord) {
        sessionID = r.sessionID
        arrival = r.arrival
        departure = r.departure
        loggedAt = r.outcome == nil ? nil : r.timestamp
        createdAt = r.arrival ?? r.timestamp
        outcomeRaw = r.outcome?.rawValue
        houseNumber = r.address.houseNumber
        street = r.address.street
        unit = r.address.unit
        city = r.address.city
        province = r.address.province
        postalCode = r.address.postalCode
        confidenceRaw = r.addressConfidence.rawValue
        latitude = r.latitude
        longitude = r.longitude
        gpsAccuracy = r.gpsAccuracy
        autoDetected = r.autoDetected
        notes = r.notes
        followUpDate = r.followUpDate
        syncStateRaw = r.syncState.rawValue
        leadData = r.lead.flatMap { try? BackupFile.encoder().encode($0) }
        updatedAt = r.updatedAt
        promptSent = true
    }
}

@Model
final class CanvassSession {
    @Attribute(.unique) var id: UUID = UUID()
    var start: Date = Date()
    var end: Date?
    var distanceMeters: Double = 0
    var pausedSeconds: Double = 0
    var pauseStartedAt: Date?

    init(start: Date = Date()) {
        self.id = UUID()
        self.start = start
    }

    var isActive: Bool { end == nil }
    var isPaused: Bool { pauseStartedAt != nil }

    func activeSeconds(now: Date = Date()) -> Double {
        var paused = pausedSeconds
        if let p = pauseStartedAt { paused += now.timeIntervalSince(p) }
        return max(0, (end ?? now).timeIntervalSince(start) - paused)
    }

    var record: SessionRecord {
        SessionRecord(id: id, start: start, end: end, distanceMeters: distanceMeters, pausedSeconds: pausedSeconds)
    }
}
