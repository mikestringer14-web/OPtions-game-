import XCTest
@testable import SmartKnockCore

final class ExportTests: XCTestCase {
    func record(_ outcome: Outcome?, notes: String = "", at t: TimeInterval = 1_800_000_000) -> VisitRecord {
        VisitRecord(timestamp: Date(timeIntervalSince1970: t), outcome: outcome,
                    address: PostalAddress(houseNumber: "12", street: "Elm Cres", city: "Oakville", province: "ON"),
                    addressConfidence: .medium, latitude: 43.45, longitude: -79.68, gpsAccuracy: 8,
                    autoDetected: true, notes: notes)
    }

    func testCSVEscaping() {
        XCTAssertEqual(CSVExporter.escape("a,b"), "\"a,b\"")
        XCTAssertEqual(CSVExporter.escape("say \"hi\""), "\"say \"\"hi\"\"\"")
        XCTAssertEqual(CSVExporter.escape("=HYPERLINK()"), "'=HYPERLINK()")
        XCTAssertEqual(CSVExporter.escape("-5"), "-5")
    }

    func testCSVHasHeaderAndRows() {
        let csv = CSVExporter.csv([record(.noAnswer), record(.booking, notes: "Roof, 20 yrs")], timeZone: TimeZone(identifier: "UTC")!)
        let lines = csv.components(separatedBy: "\r\n").filter { !$0.isEmpty }
        XCTAssertEqual(lines.count, 3)
        XCTAssertTrue(lines[0].hasPrefix("id,date,time,outcome"))
        XCTAssertTrue(csv.contains("NO_ANSWER"))
        XCTAssertTrue(csv.contains("\"Roof, 20 yrs\""))
    }

    func testBackupRoundTrip() throws {
        let backup = BackupFile(createdAt: Date(timeIntervalSince1970: 1_800_000_000),
                                visits: [record(.future)],
                                sessions: [SessionRecord(start: Date(timeIntervalSince1970: 1_799_990_000), end: nil, distanceMeters: 1200)])
        let data = try BackupFile.encoder().encode(backup)
        let decoded = try BackupFile.decoder().decode(BackupFile.self, from: data)
        XCTAssertEqual(decoded, backup)
    }

    func testStats() {
        let visits = [record(.noAnswer), record(.noAnswer), record(.booking), record(.renter), record(nil)]
        let start = Date(timeIntervalSince1970: 1_799_990_000)
        let session = SessionRecord(start: start, end: start.addingTimeInterval(7200), distanceMeters: 5000)
        let s = StatsCalculator.stats(visits: visits, sessions: [session], from: start, to: start.addingTimeInterval(86400))
        XCTAssertEqual(s.doors, 4)
        XCTAssertEqual(s.unlogged, 1)
        XCTAssertEqual(s.bookings, 1)
        XCTAssertEqual(s.contacts, 2)
        XCTAssertEqual(s.bookingRatePerDoor, 0.25, accuracy: 0.001)
        XCTAssertEqual(s.bookingRatePerContact, 0.5, accuracy: 0.001)
        XCTAssertEqual(s.doorsPerHour, 2, accuracy: 0.001)
        let report = DailyReport.text(for: start, visits: visits, stats: s)
        XCTAssertTrue(report.contains("Bookings: 1"))
    }
}
