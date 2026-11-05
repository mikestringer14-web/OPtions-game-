import XCTest
@testable import SmartKnockCore

final class AddressRankerTests: XCTestCase {
    func addr(_ n: String, _ street: String = "Walkers Line") -> PostalAddress {
        PostalAddress(houseNumber: n, street: street, city: "Burlington", province: "ON", postalCode: "L7M 4V1")
    }

    func testAgreementGivesHighConfidence() {
        let hits = [
            GeocodeHit(address: addr("2145"), source: .center, lookupDistance: 0),
            GeocodeHit(address: addr("2145"), source: .nearby, lookupDistance: 8),
            GeocodeHit(address: addr("2147"), source: .alongStreet, lookupDistance: 15)
        ]
        let r = AddressRanker.rank(hits: hits, gpsAccuracy: 6)
        XCTAssertEqual(r.best?.address.houseNumber, "2145")
        XCTAssertEqual(r.confidence, .high)
    }

    func testPoorGpsNeverClaimsHighConfidence() {
        let hits = [GeocodeHit(address: addr("2145"), source: .center, lookupDistance: 0)]
        XCTAssertEqual(AddressRanker.rank(hits: hits, gpsAccuracy: 30).confidence, .low)
    }

    func testNoResultsIsUnresolved() {
        let r = AddressRanker.rank(hits: [], gpsAccuracy: 5)
        XCTAssertEqual(r.confidence, .unresolved)
        XCTAssertTrue(r.candidates.isEmpty)
    }

    func testStreetOnlyResultIgnored() {
        let hits = [GeocodeHit(address: PostalAddress(street: "Walkers Line"), source: .center, lookupDistance: 0)]
        XCTAssertEqual(AddressRanker.rank(hits: hits, gpsAccuracy: 5).confidence, .unresolved)
    }

    func testNeighborEstimatesAddedAndFlagged() {
        let hits = [GeocodeHit(address: addr("2146"), source: .center, lookupDistance: 0)]
        let r = AddressRanker.rank(hits: hits, gpsAccuracy: 8)
        let estimated = r.candidates.filter { $0.source == .estimatedNeighbor }.map(\.address.houseNumber)
        XCTAssertEqual(Set(estimated), ["2144", "2148"])
        XCTAssertEqual(r.best?.address.houseNumber, "2146")
    }

    func testAlreadyVisitedIsDownWeighted() {
        let hits = [
            GeocodeHit(address: addr("10"), source: .center, lookupDistance: 0),
            GeocodeHit(address: addr("12"), source: .nearby, lookupDistance: 6),
            GeocodeHit(address: addr("12"), source: .alongStreet, lookupDistance: 12)
        ]
        let fresh = AddressRanker.rank(hits: hits, gpsAccuracy: 8)
        XCTAssertEqual(fresh.best?.address.houseNumber, "10")
        let visited = AddressRanker.rank(hits: hits, gpsAccuracy: 8, alreadyVisitedKeys: [addr("10").matchKey])
        XCTAssertEqual(visited.best?.address.houseNumber, "12")
    }

    func testStreetNormalization() {
        XCTAssertEqual(PostalAddress(houseNumber: "5", street: "Upper Middle Road").matchKey,
                       PostalAddress(houseNumber: "5", street: "Upper Middle Rd").matchKey)
    }

    func testSingleLine() {
        XCTAssertEqual(addr("2145").singleLine, "2145 Walkers Line, Burlington, ON L7M 4V1")
    }
}
