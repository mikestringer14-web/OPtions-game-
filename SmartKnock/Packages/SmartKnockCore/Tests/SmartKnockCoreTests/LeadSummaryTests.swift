import XCTest
@testable import SmartKnockCore

final class LeadSummaryTests: XCTestCase {
    let tz = TimeZone(identifier: "America/Toronto")!

    func testEmptyLeadMarksEverythingNotProvided() {
        let f = LeadSummaryFormatter(timeZone: tz)
        let paras = f.paragraphs(for: LeadInput())
        XCTAssertEqual(paras.count, 3)
        XCTAssertTrue(paras[0].hasPrefix("Contact Information:"))
        XCTAssertTrue(paras[0].contains("Homeowner: Not provided"))
        XCTAssertTrue(paras[0].contains("Phone: Not provided"))
        XCTAssertTrue(paras[1].hasPrefix("Appointment Information:"))
        XCTAssertTrue(paras[1].contains("Services requested: Not provided"))
        XCTAssertTrue(paras[2].hasPrefix("Detailed Job Information: Not provided"))
        XCTAssertEqual(f.missingMandatoryFields(LeadInput()).count, 6)
    }

    func testTranscriptFillsBlanksWithoutInventing() {
        var input = LeadInput()
        input.address = "2145 Walkers Line, Burlington, ON"
        input.transcript = "Spoke with Sarah Jones. Her number is 905 555 1234. The roof is about 22 years old and shingles are curling on the south side. She also wants a quote on gutter guards. Husband is skeptical about price."
        let f = LeadSummaryFormatter(timeZone: tz)
        let text = f.summary(for: input)
        XCTAssertTrue(text.contains("Homeowner: Sarah Jones"))
        XCTAssertTrue(text.contains("Phone: (905) 555-1234"))
        XCTAssertTrue(text.contains("Roofing"))
        XCTAssertTrue(text.contains("Gutter Guards"))
        XCTAssertFalse(text.contains("Eavestroughs"))
        XCTAssertTrue(text.contains("Appointment date: Not provided"))
        XCTAssertTrue(text.contains("Husband is skeptical about price."))
        // Contact-only sentence should not be repeated in the job paragraph.
        let p3 = f.paragraphs(for: input)[2]
        XCTAssertFalse(p3.contains("number is"))
    }

    func testFormFieldsWinOverTranscript() {
        var input = LeadInput()
        input.homeownerName = "Mark Lee"
        input.phone = "2895550000"
        input.transcript = "Spoke with Sarah. Number 905-555-1234."
        let text = LeadSummaryFormatter(timeZone: tz).summary(for: input)
        XCTAssertTrue(text.contains("Homeowner: Mark Lee"))
        XCTAssertTrue(text.contains("(289) 555-0000"))
        XCTAssertFalse(text.contains("Sarah"))
    }

    func testAppointmentFormatting() {
        var input = LeadInput()
        var comps = DateComponents()
        comps.year = 2026; comps.month = 11; comps.day = 12; comps.hour = 18; comps.minute = 30
        var cal = Calendar(identifier: .gregorian); cal.timeZone = tz
        input.appointmentDate = cal.date(from: comps)
        input.hasAppointmentTime = true
        let p2 = LeadSummaryFormatter(timeZone: tz).paragraphs(for: input)[1]
        XCTAssertTrue(p2.contains("Thursday, November 12, 2026"), p2)
        XCTAssertTrue(p2.contains("6:30"), p2)
    }

    func testDateWithoutTimeSaysTimeNotProvided() {
        var input = LeadInput()
        input.appointmentDate = Date(timeIntervalSince1970: 1_800_000_000)
        input.hasAppointmentTime = false
        let p2 = LeadSummaryFormatter(timeZone: tz).paragraphs(for: input)[1]
        XCTAssertTrue(p2.contains("Appointment time: Not provided"))
    }

    func testPhoneFormatting() {
        XCTAssertEqual(TranscriptExtractor.formatPhone("+1 905.555.1234"), "(905) 555-1234")
        XCTAssertEqual(TranscriptExtractor.formatPhone("555"), "555")
    }

    func testServiceDetectionFrontDoorNotCounted() {
        XCTAssertEqual(ServiceType.detect(in: "Knocked on the front door, talked about windows"), [.windows])
        XCTAssertTrue(ServiceType.detect(in: "wants a new patio door").contains(.doors))
        XCTAssertEqual(ServiceType.detect(in: "eavestroughs are overflowing"), [.eavestroughs])
    }
}
