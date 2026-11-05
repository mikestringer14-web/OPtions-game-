import CoreLocation
import Foundation
import Network
import Observation
import SwiftData
import UIKit
import SmartKnockCore

/// Orchestrates a canvassing session: GPS + motion -> stop detection ->
/// address lookup -> prompt -> one-tap logging. All UI reads state from here.
@MainActor
@Observable
final class CanvassEngine {
    static let shared = CanvassEngine()

    // MARK: Observable state
    private(set) var isActive = false
    private(set) var isPaused = false
    private(set) var sessionID: UUID?
    private(set) var sessionStart: Date?
    private(set) var distanceMeters: Double = 0
    private(set) var currentAccuracy: Double?
    private(set) var isAtDoor = false
    private(set) var pendingVisitID: UUID?
    private(set) var resolvingIDs: Set<UUID> = []
    private(set) var isOnline = true
    private(set) var motion: MotionHint = .unknown
    private(set) var authorization: CLAuthorizationStatus = .notDetermined
    private(set) var isPreciseLocation = true
    /// Most recent log, for the Undo / Change toast.
    var lastLog: VisitLogger.Result?
    /// Increments when data changes so views can refresh derived values.
    private(set) var revision = 0

    // MARK: Services
    @ObservationIgnored private let location = LocationService()
    @ObservationIgnored private let motionService = MotionService()
    @ObservationIgnored let resolver = AddressResolver()
    @ObservationIgnored private let liveActivity = LiveActivityService()
    @ObservationIgnored private let detector = StopDetector()
    @ObservationIgnored private let pathMonitor = NWPathMonitor()
    @ObservationIgnored private var lastDistancePoint: CLLocation?
    @ObservationIgnored private var lastLocationWrite: Date = .distantPast
    @ObservationIgnored private var lastSessionSave: Date = .distantPast
    @ObservationIgnored private var lastEndedVisitID: UUID?
    @ObservationIgnored private var seenDataVersion = 0
    @ObservationIgnored private var bootstrapped = false

    private var context: ModelContext { Persistence.container.mainContext }

    private init() {}

    // MARK: Lifecycle

    /// Call once at launch (including background relaunches).
    func bootstrap() {
        guard !bootstrapped else { return }
        bootstrapped = true
        authorization = location.authorizationStatus
        isPreciseLocation = location.accuracyAuthorization == .fullAccuracy

        location.onLocation = { [weak self] loc in self?.handle(location: loc) }
        location.onAuthorizationChange = { [weak self] status in
            guard let self else { return }
            self.authorization = status
            self.isPreciseLocation = self.location.accuracyAuthorization == .fullAccuracy
        }
        motionService.onHint = { [weak self] hint in
            guard let self else { return }
            self.motion = hint
            self.detector.update(motion: hint)
        }

        NotificationService.shared.registerCategories()

        pathMonitor.pathUpdateHandler = { [weak self] path in
            let online = path.status == .satisfied
            Task { @MainActor in
                guard let self else { return }
                let cameOnline = online && !self.isOnline
                self.isOnline = online
                if cameOnline { self.retryUnresolvedAddresses() }
            }
        }
        pathMonitor.start(queue: DispatchQueue(label: "smartknock.path"))

        NotificationCenter.default.addObserver(forName: .smartKnockDataChanged, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.dataDidChange() }
        }

        RetentionService.purgeIfNeeded(context: context)
        restoreSessionIfNeeded()
        VisitLogger.refreshSnapshot(lastLogged: nil)
        retryUnresolvedAddresses()
    }

    /// Called when the app returns to the foreground.
    func sceneBecameActive() {
        // Pick up anything logged from widgets in another process.
        if SharedState.dataVersion != seenDataVersion {
            seenDataVersion = SharedState.dataVersion
            revision += 1
        }
        authorization = location.authorizationStatus
        isPreciseLocation = location.accuracyAuthorization == .fullAccuracy
        retryUnresolvedAddresses()
        pushLiveActivity()
    }

    private func restoreSessionIfNeeded() {
        guard SharedState.sessionActive, let id = SharedState.sessionID else { return }
        var d = FetchDescriptor<CanvassSession>(predicate: #Predicate { $0.id == id })
        d.fetchLimit = 1
        guard let s = try? context.fetch(d).first, s.end == nil else {
            SharedState.sessionActive = false
            return
        }
        // If the phone sat idle for hours the session was clearly forgotten.
        if let last = SharedState.lastLocation?.time, Date().timeIntervalSince(last) > 4 * 3600 {
            s.end = last
            try? context.save()
            SharedState.sessionActive = false
            liveActivity.end()
            return
        }
        sessionID = s.id
        sessionStart = s.start
        distanceMeters = s.distanceMeters
        isPaused = s.isPaused
        isActive = true
        pendingVisitID = SharedState.pendingVisitID
        beginTracking(sessionStart: s.start)
    }

    // MARK: Session control

    func start() {
        guard !isActive else { return }
        let s = CanvassSession()
        context.insert(s)
        try? context.save()
        sessionID = s.id
        sessionStart = s.start
        distanceMeters = 0
        isPaused = false
        isActive = true
        SharedState.sessionID = s.id
        SharedState.sessionStart = s.start
        SharedState.sessionActive = true
        Task { _ = await NotificationService.shared.requestAuthorization() }
        beginTracking(sessionStart: s.start)
    }

    private func beginTracking(sessionStart: Date) {
        detector.config = SharedState.settings.detection
        detector.reset()
        lastDistancePoint = nil
        location.start()
        location.setLowPower(isPaused)
        motionService.start()
        liveActivity.start(sessionStart: sessionStart, state: activityState())
        // Ask for Always once When In Use is in place, for crash/termination recovery.
        if location.authorizationStatus == .authorizedWhenInUse && !AppGroup.defaults.bool(forKey: "askedAlways") {
            AppGroup.defaults.set(true, forKey: "askedAlways")
            location.requestAlways()
        }
    }

    func stop() {
        guard isActive else { return }
        for e in detector.forceEnd(at: Date()) { handle(event: e) }
        if let s = currentSession() {
            if let p = s.pauseStartedAt { s.pausedSeconds += Date().timeIntervalSince(p); s.pauseStartedAt = nil }
            s.end = Date()
            s.distanceMeters = distanceMeters
        }
        try? context.save()
        location.stop()
        motionService.stop()
        liveActivity.end()
        isActive = false
        isPaused = false
        isAtDoor = false
        SharedState.sessionActive = false
        SharedState.pendingVisitID = nil
        pendingVisitID = nil
        VisitLogger.refreshSnapshot(lastLogged: nil)
    }

    func togglePause() {
        guard isActive, let s = currentSession() else { return }
        if let p = s.pauseStartedAt {
            s.pausedSeconds += Date().timeIntervalSince(p)
            s.pauseStartedAt = nil
            isPaused = false
            detector.reset()
            location.setLowPower(false)
        } else {
            for e in detector.forceEnd(at: Date()) { handle(event: e) }
            s.pauseStartedAt = Date()
            isPaused = true
            location.setLowPower(true)
        }
        try? context.save()
        pushLiveActivity()
    }

    func applySettings() {
        detector.config = SharedState.settings.detection
    }

    func currentSession() -> CanvassSession? {
        guard let id = sessionID else { return nil }
        var d = FetchDescriptor<CanvassSession>(predicate: #Predicate { $0.id == id })
        d.fetchLimit = 1
        return try? context.fetch(d).first
    }

    // MARK: Location pipeline

    private func handle(location loc: CLLocation) {
        guard isActive else { return }
        currentAccuracy = loc.horizontalAccuracy
        let now = Date()

        if now.timeIntervalSince(lastLocationWrite) > 5 {
            lastLocationWrite = now
            SharedState.lastLocation = .init(latitude: loc.coordinate.latitude, longitude: loc.coordinate.longitude,
                                             accuracy: loc.horizontalAccuracy, time: loc.timestamp)
        }

        // Walking distance: ignore jitter and jumps.
        if loc.horizontalAccuracy > 0, loc.horizontalAccuracy <= 20 {
            if let prev = lastDistancePoint {
                let d = loc.distance(from: prev)
                if d >= 3 && d < 120 && motion != .automotive {
                    distanceMeters += d
                    lastDistancePoint = loc
                } else if d >= 120 {
                    lastDistancePoint = loc
                }
            } else {
                lastDistancePoint = loc
            }
        }
        if now.timeIntervalSince(lastSessionSave) > 30, let s = currentSession() {
            lastSessionSave = now
            s.distanceMeters = distanceMeters
            try? context.save()
        }

        // Pick up logs made from widgets / Live Activity in the extension process.
        if SharedState.dataVersion != seenDataVersion {
            seenDataVersion = SharedState.dataVersion
            dataDidChange()
        }

        guard !isPaused else { return }
        let sample = LocationSample(point: GeoPoint(latitude: loc.coordinate.latitude, longitude: loc.coordinate.longitude),
                                    accuracy: loc.horizontalAccuracy, timestamp: loc.timestamp, speed: loc.speed)
        for e in detector.process(sample) { handle(event: e) }
    }

    private func handle(event: DetectorEvent) {
        switch event {
        case let .dwellStarted(center, at, bearing):
            let v = Visit(sessionID: sessionID, latitude: center.latitude, longitude: center.longitude,
                          accuracy: currentAccuracy ?? -1, autoDetected: true)
            v.arrival = at
            v.approachBearing = bearing
            context.insert(v)
            try? context.save()
            setPending(v.id)
            isAtDoor = true
            resolveAddress(for: v)
            VisitLogger.refreshSnapshot(lastLogged: nil)

        case let .visitEnded(dv):
            isAtDoor = false
            guard let id = pendingVisitID, let v = VisitLogger.fetchVisit(id, in: context) else { break }
            v.latitude = dv.center.latitude
            v.longitude = dv.center.longitude
            v.gpsAccuracy = dv.meanAccuracy
            v.arrival = dv.arrival
            v.departure = dv.departure
            v.approachBearing = dv.approachBearing ?? v.approachBearing
            try? context.save()
            lastEndedVisitID = v.id
            if v.isPending {
                promptIfBackgrounded(v)
            } else {
                setPending(nil)
            }
            pushLiveActivity()

        case let .duplicateOfPrevious(dv):
            isAtDoor = false
            // Same door as last time: drop the new stop, extend the earlier visit.
            if let id = pendingVisitID, let dup = VisitLogger.fetchVisit(id, in: context), dup.isPending, id != lastEndedVisitID {
                context.delete(dup)
            }
            if let prevID = lastEndedVisitID, let prev = VisitLogger.fetchVisit(prevID, in: context) {
                prev.departure = dv.departure
                setPending(prev.isPending ? prev.id : nil)
                if prev.isPending { promptIfBackgrounded(prev) }
            } else {
                setPending(nil)
            }
            try? context.save()
            VisitLogger.refreshSnapshot(lastLogged: nil)

        case .dwellDiscarded:
            isAtDoor = false
            if let id = pendingVisitID, let v = VisitLogger.fetchVisit(id, in: context), v.isPending, v.autoDetected {
                context.delete(v)
                try? context.save()
            }
            setPending(nil)
            VisitLogger.refreshSnapshot(lastLogged: nil)
        }
    }

    private func setPending(_ id: UUID?) {
        pendingVisitID = id
        SharedState.pendingVisitID = id
    }

    private func promptIfBackgrounded(_ v: Visit) {
        let settings = SharedState.settings
        guard settings.promptOnDeparture, !v.promptSent else { return }
        v.promptSent = true
        try? context.save()
        if UIApplication.shared.applicationState != .active {
            NotificationService.shared.promptForVisit(id: v.id, address: v.displayAddress, confidence: v.confidence,
                                                      cooldown: settings.detection.notificationCooldownSeconds)
        } else {
            UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        }
    }

    // MARK: Manual actions

    /// Creates a door at the current spot (when automatic detection missed it).
    @discardableResult
    func markDoorHere() -> Visit? {
        guard let loc = location.lastLocation ?? lastKnownCLLocation() else { return nil }
        if let id = pendingVisitID, let existing = VisitLogger.fetchVisit(id, in: context), existing.isPending,
           GeoMath.distance(GeoPoint(latitude: existing.latitude, longitude: existing.longitude),
                            GeoPoint(latitude: loc.coordinate.latitude, longitude: loc.coordinate.longitude)) < 8 {
            return existing
        }
        let v = Visit(sessionID: sessionID, latitude: loc.coordinate.latitude, longitude: loc.coordinate.longitude,
                      accuracy: loc.horizontalAccuracy, autoDetected: false)
        v.arrival = Date()
        context.insert(v)
        try? context.save()
        setPending(v.id)
        resolveAddress(for: v)
        VisitLogger.refreshSnapshot(lastLogged: nil)
        return v
    }

    /// Rep says they are done at this door before walking away.
    func finishCurrentDoor() {
        for e in detector.forceEnd(at: Date()) { handle(event: e) }
    }

    private func lastKnownCLLocation() -> CLLocation? {
        guard let l = SharedState.lastLocation else { return nil }
        return CLLocation(coordinate: CLLocationCoordinate2D(latitude: l.latitude, longitude: l.longitude),
                          altitude: 0, horizontalAccuracy: l.accuracy, verticalAccuracy: -1, timestamp: l.time)
    }

    /// One-tap log. Booking/Call Back/Future follow-up screens are handled by the UI.
    @discardableResult
    func log(_ outcome: Outcome, visitID: UUID? = nil) -> VisitLogger.Result? {
        guard let result = try? VisitLogger.log(outcome, visitID: visitID) else { return nil }
        NotificationService.shared.clearPrompt(for: result.visitID)
        if pendingVisitID == result.visitID { setPending(nil) }
        if let v = VisitLogger.fetchVisit(result.visitID, in: context) {
            if result.createdNewVisit { resolveAddress(for: v) }
            scheduleFollowUpIfNeeded(v)
        }
        lastLog = result
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        pushLiveActivity()
        return result
    }

    func undoLastLog() {
        guard let r = lastLog else { return }
        try? VisitLogger.undo(r)
        NotificationService.shared.cancelFollowUp(id: r.visitID)
        if r.previousOutcome == nil && !r.createdNewVisit { setPending(r.visitID) }
        lastLog = nil
        pushLiveActivity()
    }

    func scheduleFollowUpIfNeeded(_ v: Visit) {
        guard SharedState.settings.followUpReminders, let o = v.outcome, o.wantsFollowUp, let date = v.followUpDate else {
            NotificationService.shared.cancelFollowUp(id: v.id)
            return
        }
        NotificationService.shared.scheduleFollowUp(id: v.id, outcome: o, address: v.displayAddress, at: date)
    }

    func delete(_ v: Visit) {
        NotificationService.shared.clearPrompt(for: v.id)
        NotificationService.shared.cancelFollowUp(id: v.id)
        if pendingVisitID == v.id { setPending(nil) }
        context.delete(v)
        try? context.save()
        VisitLogger.refreshSnapshot(lastLogged: nil)
    }

    // MARK: Addresses

    func resolveAddress(for v: Visit) {
        guard v.latitude != 0 || v.longitude != 0, !resolvingIDs.contains(v.id), v.confidence != .confirmed else { return }
        resolvingIDs.insert(v.id)
        let id = v.id
        let center = GeoPoint(latitude: v.latitude, longitude: v.longitude)
        let bearing = v.approachBearing
        let accuracy = v.gpsAccuracy > 0 ? v.gpsAccuracy : 20
        let visited = visitedAddressKeys(excluding: id)
        Task { @MainActor in
            defer { self.resolvingIDs.remove(id) }
            guard let visit = VisitLogger.fetchVisit(id, in: self.context) else { return }
            do {
                let ranked = try await self.resolver.resolve(center: center, approachBearing: bearing, accuracy: accuracy,
                                                             visitedKeys: visited, settings: SharedState.settings)
                guard visit.confidence != .confirmed else { return }
                visit.candidates = ranked.candidates
                if let best = ranked.best {
                    visit.address = best.address
                    visit.confidence = ranked.confidence
                } else {
                    visit.addressLookupAttempts += 1
                }
            } catch {
                visit.addressLookupAttempts += 1
            }
            try? self.context.save()
            VisitLogger.refreshSnapshot(lastLogged: nil)
            self.pushLiveActivity()
        }
    }

    /// Visits saved while offline get their address once the network returns.
    func retryUnresolvedAddresses() {
        let raw = AddressConfidence.unresolved.rawValue
        let d = FetchDescriptor<Visit>(predicate: #Predicate { $0.confidenceRaw == raw && $0.addressLookupAttempts < 6 },
                                       sortBy: [SortDescriptor(\.createdAt, order: .reverse)])
        guard let list = try? context.fetch(d) else { return }
        for v in list.prefix(20) where v.latitude != 0 || v.longitude != 0 {
            resolveAddress(for: v)
        }
    }

    func setAddress(_ address: PostalAddress, for v: Visit, coordinate: CLLocationCoordinate2D? = nil) {
        v.address = address
        v.confidence = .confirmed
        if let c = coordinate {
            v.latitude = c.latitude
            v.longitude = c.longitude
        }
        var list = v.candidates
        if !list.contains(where: { $0.address.matchKey == address.matchKey }) {
            list.insert(AddressCandidate(address: address, source: .manual, hits: 0, lookupDistance: 0, score: 0), at: 0)
            v.candidates = list
        }
        try? context.save()
        VisitLogger.refreshSnapshot(lastLogged: nil)
        pushLiveActivity()
    }

    private func visitedAddressKeys(excluding id: UUID) -> Set<String> {
        let today = VisitLogger.todaysVisits(in: context)
        return Set(today.filter { $0.id != id && !$0.address.isEmpty }.map { $0.address.matchKey })
    }

    // MARK: Live Activity

    private func dataDidChange() {
        revision += 1
        if let id = pendingVisitID, let v = VisitLogger.fetchVisit(id, in: context), !v.isPending {
            setPending(nil)
        }
        pushLiveActivity()
    }

    func activityState() -> CanvassActivityAttributes.ContentState {
        let snap = SharedState.snapshot
        var address = ""
        var confidence = AddressConfidence.unresolved.rawValue
        if let id = pendingVisitID, let v = VisitLogger.fetchVisit(id, in: context), v.isPending {
            address = v.displayAddress
            confidence = v.confidenceRaw
        }
        return .init(doors: snap.doorsToday, bookings: snap.bookingsToday, pending: snap.pendingCount,
                     currentAddress: address, confidence: confidence, isAtDoor: isAtDoor, isPaused: isPaused)
    }

    private func pushLiveActivity() {
        guard isActive else { return }
        liveActivity.update(activityState())
        revision += 1
    }

    // MARK: Permissions passthrough

    func requestLocationPermission() { location.requestWhenInUse() }
    func requestAlwaysPermission() { location.requestAlways() }
    func requestPrecise() { location.requestTemporaryPrecise() }
}
