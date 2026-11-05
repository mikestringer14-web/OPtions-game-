import Foundation

/// One location fix fed into the detector.
public struct LocationSample: Sendable, Equatable {
    public var point: GeoPoint
    /// Horizontal accuracy radius in metres (lower is better).
    public var accuracy: Double
    public var timestamp: Date
    /// Ground speed in m/s, negative if unknown.
    public var speed: Double

    public init(point: GeoPoint, accuracy: Double, timestamp: Date, speed: Double = -1) {
        self.point = point
        self.accuracy = accuracy
        self.timestamp = timestamp
        self.speed = speed
    }
}

/// Coarse activity from Core Motion.
public enum MotionHint: String, Sendable, Codable {
    case unknown, stationary, walking, running, cycling, automotive
}

/// Tunable thresholds. Defaults are tuned for suburban Ontario lots
/// (roughly 12 to 20 m frontages, 6 to 15 m setbacks).
public struct DetectionConfig: Codable, Equatable, Sendable {
    /// Samples within this radius of the dwell centre count as "standing still".
    public var dwellRadius: Double = 8
    /// How long the rep must stay inside the radius before it counts as a door stop.
    public var minDwellSeconds: Double = 20
    /// Stops longer than this are treated as breaks (lunch, phone call) and ignored.
    public var maxDwellSeconds: Double = 20 * 60
    /// Distance from the dwell centre that means the rep has left, regardless of speed.
    public var departureDistance: Double = 14
    /// While moving at walking pace, this shorter distance also counts as leaving.
    /// Neighbouring front doors are often only 12 to 18 m apart.
    public var walkingDepartureDistance: Double = 10
    /// Speed (m/s) treated as "walking away".
    public var walkingSpeedThreshold: Double = 0.7
    /// How many consecutive far-away samples confirm a departure (filters GPS jumps).
    public var departureConfirmSamples: Int = 3
    /// Fixes worse than this are ignored entirely.
    public var maxAcceptableAccuracy: Double = 35
    /// Minimum seconds between the end of one detected visit and the start of the next dwell.
    public var interVisitCooldownSeconds: Double = 8
    /// A new visit closer than this to the previous one, within `duplicateWindowSeconds`,
    /// is treated as the same door (rep stepped away and came back).
    public var duplicateRadius: Double = 8
    public var duplicateWindowSeconds: Double = 10 * 60
    /// Minimum seconds between "log this door" prompts.
    public var notificationCooldownSeconds: Double = 15
    /// Speeds above this (m/s) mean the rep is driving; detection pauses. 4 m/s is about 14 km/h.
    public var maxWalkingSpeed: Double = 4.0

    public init() {}
}

/// A completed door stop.
public struct DetectedVisit: Sendable, Equatable {
    public var center: GeoPoint
    public var arrival: Date
    public var departure: Date
    /// Mean accuracy of the samples used, metres.
    public var meanAccuracy: Double
    public var sampleCount: Int
    /// Direction the rep was walking before stopping, degrees. Used to look up
    /// next-door addresses along the street. Nil if unknown.
    public var approachBearing: Double?

    public var dwellSeconds: Double { departure.timeIntervalSince(arrival) }
}

public enum DetectorEvent: Sendable, Equatable {
    /// The rep has been standing at one spot long enough to look like a door.
    case dwellStarted(center: GeoPoint, at: Date, approachBearing: Double?)
    /// The rep walked away; the visit is complete and should be logged.
    case visitEnded(DetectedVisit)
    /// The rep returned to the spot of the previous visit within the duplicate window.
    case duplicateOfPrevious(DetectedVisit)
    /// The dwell was too long and is being ignored.
    case dwellDiscarded(reason: String)
}

/// Pure state machine that turns a stream of GPS fixes into door visits.
/// Not thread-safe; drive it from a single actor/queue.
public final class StopDetector {
    public var config: DetectionConfig

    private enum State {
        case moving
        case dwelling(start: Date, samples: [LocationSample], approachBearing: Double?, outsideCount: Int)
    }

    private var state: State = .moving
    /// Recent accepted fixes while moving, used to spot the start of a dwell.
    private var recent: [LocationSample] = []
    private var lastVisitEnd: Date?
    private var lastVisit: DetectedVisit?
    private var motion: MotionHint = .unknown

    public init(config: DetectionConfig = DetectionConfig()) {
        self.config = config
    }

    public var isDwelling: Bool {
        if case .dwelling = state { return true }
        return false
    }

    /// Current dwell centre, if dwelling.
    public var dwellCenter: GeoPoint? {
        if case let .dwelling(_, samples, _, _) = state {
            return GeoMath.weightedCentroid(samples.map { ($0.point, $0.accuracy) })
        }
        return nil
    }

    public func reset() {
        state = .moving
        recent.removeAll()
        lastVisitEnd = nil
        lastVisit = nil
        motion = .unknown
    }

    public func update(motion: MotionHint) {
        self.motion = motion
        if motion == .automotive, isDwelling {
            // Sitting in a car at a light is not a door.
            state = .moving
            recent.removeAll()
        }
    }

    /// Feed one fix. Returns any events produced.
    @discardableResult
    public func process(_ sample: LocationSample) -> [DetectorEvent] {
        guard sample.accuracy >= 0, sample.accuracy <= config.maxAcceptableAccuracy else { return [] }
        if motion == .automotive || (sample.speed > config.maxWalkingSpeed) {
            if isDwelling { state = .moving }
            recent.removeAll()
            return []
        }

        switch state {
        case .moving:
            return handleMoving(sample)
        case let .dwelling(start, samples, bearing, outsideCount):
            return handleDwelling(sample, start: start, samples: samples, bearing: bearing, outsideCount: outsideCount)
        }
    }

    /// Force the current dwell to end now (for example, the rep tapped "Done at this door").
    public func forceEnd(at date: Date) -> [DetectorEvent] {
        guard case let .dwelling(start, samples, bearing, _) = state else { return [] }
        state = .moving
        recent.removeAll()
        return finish(start: start, end: date, samples: samples, bearing: bearing)
    }

    // MARK: - Private

    private func handleMoving(_ sample: LocationSample) -> [DetectorEvent] {
        recent.append(sample)
        // Keep a window slightly longer than the dwell threshold.
        let horizon = sample.timestamp.addingTimeInterval(-(config.minDwellSeconds * 3))
        recent.removeAll { $0.timestamp < horizon }

        if let end = lastVisitEnd, sample.timestamp.timeIntervalSince(end) < config.interVisitCooldownSeconds {
            return []
        }

        // Samples within the last minDwellSeconds.
        let windowStart = sample.timestamp.addingTimeInterval(-config.minDwellSeconds)
        let window = recent.filter { $0.timestamp >= windowStart }
        guard let first = window.first,
              sample.timestamp.timeIntervalSince(first.timestamp) >= config.minDwellSeconds * 0.8,
              window.count >= 3,
              let center = GeoMath.weightedCentroid(window.map { ($0.point, $0.accuracy) })
        else { return [] }

        // The window must also reach back far enough: require an older sample before it,
        // or a full window of samples, so a single slow fix does not trigger a dwell.
        let allInside = window.allSatisfy { GeoMath.distance($0.point, center) <= config.dwellRadius + min($0.accuracy, 10) * 0.5 }
        guard allInside else { return [] }

        // Approach bearing: from the oldest sample outside the dwell radius to the centre.
        var bearing: Double?
        if let approachFrom = recent.first(where: { GeoMath.distance($0.point, center) > config.dwellRadius * 1.5 }) {
            bearing = GeoMath.bearing(from: approachFrom.point, to: center)
        }

        state = .dwelling(start: first.timestamp, samples: window, approachBearing: bearing, outsideCount: 0)
        recent.removeAll()
        return [.dwellStarted(center: center, at: first.timestamp, approachBearing: bearing)]
    }

    private func handleDwelling(_ sample: LocationSample, start: Date, samples: [LocationSample],
                                bearing: Double?, outsideCount: Int) -> [DetectorEvent] {
        let center = GeoMath.weightedCentroid(samples.map { ($0.point, $0.accuracy) }) ?? sample.point
        let d = GeoMath.distance(sample.point, center)

        let walkingAway = sample.speed >= config.walkingSpeedThreshold && d > config.walkingDepartureDistance
        if d > config.departureDistance || walkingAway {
            let count = outsideCount + 1
            if count >= config.departureConfirmSamples {
                // Departure time is the last sample that was still inside.
                let end = samples.last?.timestamp ?? sample.timestamp
                state = .moving
                recent = [sample]
                return finish(start: start, end: end, samples: samples, bearing: bearing)
            }
            state = .dwelling(start: start, samples: samples, approachBearing: bearing, outsideCount: count)
            return []
        }

        var updated = samples
        if d <= config.dwellRadius * 1.5 { updated.append(sample) }
        // Cap memory on very long dwells.
        if updated.count > 300 { updated.removeFirst(updated.count - 300) }
        state = .dwelling(start: start, samples: updated, approachBearing: bearing, outsideCount: 0)
        return []
    }

    private func finish(start: Date, end: Date, samples: [LocationSample], bearing: Double?) -> [DetectorEvent] {
        let duration = end.timeIntervalSince(start)
        guard duration <= config.maxDwellSeconds else {
            lastVisitEnd = end
            return [.dwellDiscarded(reason: "Stopped for \(Int(duration / 60)) min, longer than the door limit")]
        }
        guard let center = GeoMath.weightedCentroid(samples.map { ($0.point, $0.accuracy) }) else { return [] }
        let meanAcc = samples.map(\.accuracy).reduce(0, +) / Double(max(samples.count, 1))
        let visit = DetectedVisit(center: center, arrival: start, departure: end,
                                  meanAccuracy: meanAcc, sampleCount: samples.count, approachBearing: bearing)
        defer {
            lastVisitEnd = end
            lastVisit = visit
        }
        if let prev = lastVisit,
           start.timeIntervalSince(prev.departure) <= config.duplicateWindowSeconds,
           GeoMath.distance(prev.center, center) <= config.duplicateRadius {
            return [.duplicateOfPrevious(visit)]
        }
        return [.visitEnded(visit)]
    }
}
