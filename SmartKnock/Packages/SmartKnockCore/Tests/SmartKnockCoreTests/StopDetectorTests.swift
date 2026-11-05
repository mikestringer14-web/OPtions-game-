import XCTest
@testable import SmartKnockCore

final class StopDetectorTests: XCTestCase {
    // A point on a Burlington residential street.
    let origin = GeoPoint(latitude: 43.3600, longitude: -79.8200)

    /// Walk east at 1.3 m/s for `seconds`, one fix per second.
    func walk(_ detector: StopDetector, from start: GeoPoint, bearing: Double, seconds: Int, t0: Date) -> (GeoPoint, Date, [DetectorEvent]) {
        var p = start
        var t = t0
        var events: [DetectorEvent] = []
        for _ in 0..<seconds {
            p = GeoMath.offset(p, meters: 1.3, bearing: bearing)
            t = t.addingTimeInterval(1)
            events += detector.process(LocationSample(point: p, accuracy: 6, timestamp: t, speed: 1.3))
        }
        return (p, t, events)
    }

    /// Stand still with small jitter.
    func stand(_ detector: StopDetector, at p: GeoPoint, seconds: Int, t0: Date) -> (Date, [DetectorEvent]) {
        var t = t0
        var events: [DetectorEvent] = []
        for i in 0..<seconds {
            let jitter = GeoMath.offset(p, meters: Double(i % 3), bearing: Double((i * 97) % 360))
            t = t.addingTimeInterval(1)
            events += detector.process(LocationSample(point: jitter, accuracy: 7, timestamp: t, speed: 0))
        }
        return (t, events)
    }

    func testDetectsDoorStopAndDeparture() {
        let d = StopDetector()
        let t0 = Date(timeIntervalSince1970: 1_700_000_000)
        let (p1, t1, e1) = walk(d, from: origin, bearing: 90, seconds: 30, t0: t0)
        XCTAssertTrue(e1.isEmpty)
        let (t2, e2) = stand(d, at: p1, seconds: 60, t0: t1)
        XCTAssertTrue(e2.contains { if case .dwellStarted = $0 { return true }; return false })
        let (_, _, e3) = walk(d, from: p1, bearing: 90, seconds: 30, t0: t2)
        let ended = e3.compactMap { e -> DetectedVisit? in if case let .visitEnded(v) = e { return v }; return nil }
        XCTAssertEqual(ended.count, 1)
        let v = ended[0]
        XCTAssertLessThan(GeoMath.distance(v.center, p1), 5)
        XCTAssertGreaterThan(v.dwellSeconds, 40)
        XCTAssertNotNil(v.approachBearing)
        XCTAssertEqual(v.approachBearing ?? 0, 90, accuracy: 10)
    }

    func testContinuousWalkingProducesNoVisits() {
        let d = StopDetector()
        let (_, _, e) = walk(d, from: origin, bearing: 45, seconds: 600, t0: Date())
        XCTAssertTrue(e.isEmpty)
    }

    func testShortPauseIsIgnored() {
        let d = StopDetector()
        let t0 = Date()
        let (p1, t1, _) = walk(d, from: origin, bearing: 90, seconds: 20, t0: t0)
        let (t2, e2) = stand(d, at: p1, seconds: 8, t0: t1)
        XCTAssertTrue(e2.isEmpty)
        let (_, _, e3) = walk(d, from: p1, bearing: 90, seconds: 20, t0: t2)
        XCTAssertTrue(e3.isEmpty)
    }

    func testDrivingSuppressesDetection() {
        let d = StopDetector()
        d.update(motion: .automotive)
        let (_, e) = stand(d, at: origin, seconds: 120, t0: Date())
        XCTAssertTrue(e.isEmpty)
    }

    func testLongStopIsDiscarded() {
        var cfg = DetectionConfig()
        cfg.maxDwellSeconds = 120
        let d = StopDetector(config: cfg)
        let t0 = Date()
        let (p1, t1, _) = walk(d, from: origin, bearing: 0, seconds: 20, t0: t0)
        let (t2, _) = stand(d, at: p1, seconds: 300, t0: t1)
        let (_, _, e) = walk(d, from: p1, bearing: 0, seconds: 20, t0: t2)
        XCTAssertTrue(e.contains { if case .dwellDiscarded = $0 { return true }; return false })
    }

    func testReturningToSameDoorIsDuplicate() {
        let d = StopDetector()
        let t0 = Date()
        let (p1, t1, _) = walk(d, from: origin, bearing: 90, seconds: 20, t0: t0)
        let (t2, _) = stand(d, at: p1, seconds: 40, t0: t1)
        // Step 30 m away and come straight back.
        let (p2, t3, _) = walk(d, from: p1, bearing: 270, seconds: 25, t0: t2)
        let (_, t4, _) = walk(d, from: p2, bearing: 90, seconds: 25, t0: t3)
        let (t5, _) = stand(d, at: p1, seconds: 40, t0: t4)
        let (_, _, e) = walk(d, from: p1, bearing: 90, seconds: 25, t0: t5)
        XCTAssertTrue(e.contains { if case .duplicateOfPrevious = $0 { return true }; return false })
    }

    func testPoorAccuracyIgnored() {
        let d = StopDetector()
        var t = Date()
        var events: [DetectorEvent] = []
        for _ in 0..<120 {
            t = t.addingTimeInterval(1)
            events += d.process(LocationSample(point: origin, accuracy: 80, timestamp: t))
        }
        XCTAssertTrue(events.isEmpty)
    }

    func testConsecutiveHousesProduceSeparateVisits() {
        let d = StopDetector()
        var t = Date()
        var p = origin
        var visits = 0
        for _ in 0..<5 {
            let w = walk(d, from: p, bearing: 90, seconds: 14, t0: t) // ~18 m frontage
            p = w.0; t = w.1
            visits += w.2.filter { if case .visitEnded = $0 { return true }; return false }.count
            let s = stand(d, at: p, seconds: 35, t0: t)
            t = s.0
        }
        let w = walk(d, from: p, bearing: 90, seconds: 20, t0: t)
        visits += w.2.filter { if case .visitEnded = $0 { return true }; return false }.count
        XCTAssertEqual(visits, 5)
    }
}
