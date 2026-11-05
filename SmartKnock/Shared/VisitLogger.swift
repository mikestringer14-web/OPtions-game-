import Foundation
import SwiftData
import SmartKnockCore
#if canImport(WidgetKit)
import WidgetKit
#endif

extension Notification.Name {
    /// Posted in-process after any outcome is logged or changed.
    static let smartKnockDataChanged = Notification.Name("SmartKnockDataChanged")
}

/// The one place outcomes get written. Used by the app UI, notification
/// actions, widgets, the Live Activity, Siri and the Action Button.
@MainActor
enum VisitLogger {

    struct Result {
        var visitID: UUID
        var previousOutcome: Outcome?
        var addressText: String
        var createdNewVisit: Bool
    }

    static var context: ModelContext { Persistence.container.mainContext }

    /// Logs `outcome` against a specific visit, or against the visit that is
    /// waiting to be logged, or (if none) against a new visit at the last known
    /// location. A second tap on the same door corrects it instead of
    /// creating a duplicate.
    @discardableResult
    static func log(_ outcome: Outcome, visitID: UUID? = nil, now: Date = Date()) throws -> Result {
        let ctx = context
        var created = false
        let visit: Visit

        if let id = visitID, let v = fetchVisit(id, in: ctx) {
            visit = v
        } else if let pending = currentPendingVisit(in: ctx, now: now) {
            visit = pending
        } else if let recent = recentlyLoggedNearby(in: ctx, now: now) {
            // Rep tapped twice for the same door from a widget: treat as correction.
            visit = recent
        } else {
            let loc = SharedState.lastLocation
            let fresh = loc.map { now.timeIntervalSince($0.time) < 180 } ?? false
            visit = Visit(sessionID: SharedState.sessionID,
                          latitude: fresh ? loc!.latitude : 0,
                          longitude: fresh ? loc!.longitude : 0,
                          accuracy: fresh ? loc!.accuracy : -1,
                          autoDetected: false)
            visit.arrival = now
            ctx.insert(visit)
            created = true
        }

        let previous = visit.outcome
        visit.outcome = outcome
        visit.loggedAt = visit.loggedAt ?? now
        if visit.departure == nil, !created { visit.departure = now }
        if outcome.wantsFollowUp, visit.followUpDate == nil {
            let hours = SharedState.settings.defaultCallbackHours
            visit.followUpDate = outcome == .callBack ? now.addingTimeInterval(Double(hours) * 3600) : nil
        }
        try ctx.save()

        if SharedState.pendingVisitID == visit.id { SharedState.pendingVisitID = nil }
        refreshSnapshot(lastLogged: visit)
        return Result(visitID: visit.id, previousOutcome: previous, addressText: visit.displayAddress, createdNewVisit: created)
    }

    /// Restores the outcome a visit had before the last log (Undo).
    static func undo(_ result: Result) throws {
        let ctx = context
        guard let v = fetchVisit(result.visitID, in: ctx) else { return }
        if result.createdNewVisit {
            ctx.delete(v)
        } else {
            v.outcome = result.previousOutcome
            if result.previousOutcome == nil {
                v.loggedAt = nil
                SharedState.pendingVisitID = v.id
            }
        }
        try ctx.save()
        refreshSnapshot(lastLogged: nil)
    }

    static func fetchVisit(_ id: UUID, in ctx: ModelContext) -> Visit? {
        var d = FetchDescriptor<Visit>(predicate: #Predicate { $0.id == id })
        d.fetchLimit = 1
        return try? ctx.fetch(d).first
    }

    /// The newest unlogged visit in the last 20 minutes.
    static func currentPendingVisit(in ctx: ModelContext, now: Date) -> Visit? {
        if let id = SharedState.pendingVisitID, let v = fetchVisit(id, in: ctx), v.isPending {
            return v
        }
        let cutoff = now.addingTimeInterval(-20 * 60)
        var d = FetchDescriptor<Visit>(predicate: #Predicate { $0.outcomeRaw == nil && $0.createdAt >= cutoff },
                                       sortBy: [SortDescriptor(\.createdAt, order: .reverse)])
        d.fetchLimit = 1
        return try? ctx.fetch(d).first
    }

    static func recentlyLoggedNearby(in ctx: ModelContext, now: Date) -> Visit? {
        guard let loc = SharedState.lastLocation, now.timeIntervalSince(loc.time) < 60 else { return nil }
        let cutoff = now.addingTimeInterval(-45)
        var d = FetchDescriptor<Visit>(predicate: #Predicate { $0.loggedAt != nil && $0.updatedAt >= cutoff },
                                       sortBy: [SortDescriptor(\.updatedAt, order: .reverse)])
        d.fetchLimit = 1
        guard let v = try? ctx.fetch(d).first else { return nil }
        let dist = GeoMath.distance(GeoPoint(latitude: v.latitude, longitude: v.longitude),
                                    GeoPoint(latitude: loc.latitude, longitude: loc.longitude))
        return dist <= 6 ? v : nil
    }

    static func todaysVisits(in ctx: ModelContext, now: Date = Date()) -> [Visit] {
        let start = Calendar.current.startOfDay(for: now)
        let d = FetchDescriptor<Visit>(predicate: #Predicate { $0.createdAt >= start },
                                       sortBy: [SortDescriptor(\.createdAt)])
        return (try? ctx.fetch(d)) ?? []
    }

    /// Recomputes widget numbers and tells everyone that data changed.
    static func refreshSnapshot(lastLogged: Visit?) {
        let today = todaysVisits(in: context)
        var s = SharedState.snapshot
        s.day = Calendar.current.startOfDay(for: Date())
        s.doorsToday = today.filter { !$0.isPending }.count
        s.bookingsToday = today.filter { $0.outcome == .booking }.count
        s.noAnswerToday = today.filter { $0.outcome == .noAnswer }.count
        s.pendingCount = today.filter(\.isPending).count
        if let v = lastLogged {
            s.lastLoggedAddress = v.displayAddress
            s.lastLoggedOutcome = v.outcomeRaw
        }
        if let id = SharedState.pendingVisitID, let p = fetchVisit(id, in: context), p.isPending {
            s.currentAddress = p.displayAddress
            s.currentConfidence = p.confidenceRaw
        } else {
            s.currentAddress = ""
            s.currentConfidence = AddressConfidence.unresolved.rawValue
        }
        SharedState.snapshot = s
        SharedState.dataVersion += 1
        NotificationCenter.default.post(name: .smartKnockDataChanged, object: nil)
        #if canImport(WidgetKit)
        WidgetCenter.shared.reloadAllTimelines()
        #endif
    }
}
