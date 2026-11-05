import Foundation

/// A street address broken into parts. Built from a reverse-geocode result
/// or typed by the rep.
public struct PostalAddress: Codable, Hashable, Sendable {
    public var houseNumber: String
    public var street: String
    public var unit: String
    public var city: String
    public var province: String
    public var postalCode: String

    public init(houseNumber: String = "", street: String = "", unit: String = "",
                city: String = "", province: String = "", postalCode: String = "") {
        self.houseNumber = houseNumber.trimmingCharacters(in: .whitespaces)
        self.street = street.trimmingCharacters(in: .whitespaces)
        self.unit = unit.trimmingCharacters(in: .whitespaces)
        self.city = city.trimmingCharacters(in: .whitespaces)
        self.province = province.trimmingCharacters(in: .whitespaces)
        self.postalCode = postalCode.trimmingCharacters(in: .whitespaces)
    }

    public var isEmpty: Bool { houseNumber.isEmpty && street.isEmpty }

    /// "2145 Walkers Line"
    public var line1: String {
        var s = [houseNumber, street].filter { !$0.isEmpty }.joined(separator: " ")
        if !unit.isEmpty { s = "Unit \(unit), " + s }
        return s
    }

    /// "Burlington, ON L7M 4V1"
    public var line2: String {
        let provPostal = [province, postalCode].filter { !$0.isEmpty }.joined(separator: " ")
        return [city, provPostal].filter { !$0.isEmpty }.joined(separator: ", ")
    }

    public var singleLine: String {
        [line1, line2].filter { !$0.isEmpty }.joined(separator: ", ")
    }

    /// Key used to compare addresses regardless of case/abbreviation.
    public var matchKey: String {
        let num = houseNumber.lowercased()
        return "\(num)|\(Self.normalizeStreet(street))|\(unit.lowercased())"
    }

    public var numericHouseNumber: Int? {
        let digits = houseNumber.prefix { $0.isNumber }
        return Int(digits)
    }

    /// Normalizes common Canadian street suffix spellings so "Walkers Ln" and
    /// "Walkers Line" compare equal.
    public static func normalizeStreet(_ street: String) -> String {
        let map: [String: String] = [
            "street": "st", "st.": "st", "avenue": "ave", "ave.": "ave", "road": "rd", "rd.": "rd",
            "drive": "dr", "dr.": "dr", "crescent": "cres", "cres.": "cres", "cr": "cres",
            "court": "crt", "ct": "crt", "crt.": "crt", "boulevard": "blvd", "blvd.": "blvd",
            "place": "pl", "pl.": "pl", "lane": "ln", "line": "line", "circle": "cir",
            "trail": "trl", "terrace": "terr", "parkway": "pkwy", "highway": "hwy",
            "east": "e", "west": "w", "north": "n", "south": "s", "gate": "gt", "way": "way",
            "square": "sq", "heights": "hts", "grove": "grv"
        ]
        return street.lowercased()
            .split(separator: " ")
            .map { map[String($0)] ?? String($0) }
            .joined(separator: " ")
    }

    /// Returns a copy with a different house number.
    public func withHouseNumber(_ number: String) -> PostalAddress {
        var copy = self
        copy.houseNumber = number
        return copy
    }
}

/// Where a suggested address came from.
public enum CandidateSource: String, Codable, Sendable {
    /// Reverse geocode of the dwell centre.
    case center
    /// Reverse geocode of a point offset along the street.
    case alongStreet
    /// Reverse geocode of a point offset away from the street (toward the house).
    case nearby
    /// Neighbouring house number we guessed (same street, same side). Never assumed correct.
    case estimatedNeighbor
    /// Typed, searched, or tapped on the map by the rep.
    case manual
}

public struct AddressCandidate: Codable, Hashable, Sendable, Identifiable {
    public var address: PostalAddress
    public var source: CandidateSource
    /// Number of geocode lookups that returned this address.
    public var hits: Int
    /// Distance in metres from the dwell centre to the lookup point that produced it.
    public var lookupDistance: Double
    public var score: Double

    public var id: String { address.matchKey }

    public init(address: PostalAddress, source: CandidateSource, hits: Int = 1, lookupDistance: Double = 0, score: Double = 0) {
        self.address = address
        self.source = source
        self.hits = hits
        self.lookupDistance = lookupDistance
        self.score = score
    }
}

/// One raw reverse-geocode answer.
public struct GeocodeHit: Sendable {
    public var address: PostalAddress
    public var source: CandidateSource
    public var lookupDistance: Double

    public init(address: PostalAddress, source: CandidateSource, lookupDistance: Double) {
        self.address = address
        self.source = source
        self.lookupDistance = lookupDistance
    }
}

public struct RankedAddresses: Sendable {
    public var candidates: [AddressCandidate]
    public var confidence: AddressConfidence
    public var best: AddressCandidate? { candidates.first }
}

/// Combines several reverse-geocode answers into an ordered list of likely
/// addresses plus an honest confidence rating.
public enum AddressRanker {

    /// - Parameters:
    ///   - hits: raw geocode results (centre first, then offsets)
    ///   - gpsAccuracy: mean horizontal accuracy of the dwell, metres
    ///   - alreadyVisitedKeys: addresses logged earlier this session, slightly down-weighted
    ///     so consecutive houses are less likely to collapse onto the same number
    public static func rank(hits: [GeocodeHit], gpsAccuracy: Double,
                            alreadyVisitedKeys: Set<String> = [],
                            includeNeighborEstimates: Bool = true) -> RankedAddresses {
        let usable = hits.filter { !$0.address.houseNumber.isEmpty && !$0.address.street.isEmpty }
        guard !usable.isEmpty else {
            return RankedAddresses(candidates: [], confidence: .unresolved)
        }

        var merged: [String: AddressCandidate] = [:]
        var order: [String] = []
        for hit in usable {
            let key = hit.address.matchKey
            let weight: Double
            switch hit.source {
            case .center: weight = 3.0
            case .nearby: weight = 1.5
            case .alongStreet: weight = 1.0
            case .estimatedNeighbor: weight = 0.3
            case .manual: weight = 10
            }
            if var existing = merged[key] {
                existing.hits += 1
                existing.score += weight
                existing.lookupDistance = min(existing.lookupDistance, hit.lookupDistance)
                if hit.source == .center { existing.source = .center }
                merged[key] = existing
            } else {
                merged[key] = AddressCandidate(address: hit.address, source: hit.source, hits: 1,
                                               lookupDistance: hit.lookupDistance, score: weight)
                order.append(key)
            }
        }

        for key in alreadyVisitedKeys where merged[key] != nil {
            merged[key]!.score *= 0.6
        }

        var ranked = order.compactMap { merged[$0] }
            .sorted { a, b in
                if a.score != b.score { return a.score > b.score }
                return a.lookupDistance < b.lookupDistance
            }

        let confidence = confidenceFor(ranked: ranked, totalHits: usable.count, gpsAccuracy: gpsAccuracy)

        if includeNeighborEstimates, let top = ranked.first {
            let existingKeys = Set(ranked.map(\.id))
            for neighbor in neighborNumbers(of: top.address) where !existingKeys.contains(neighbor.matchKey) {
                ranked.append(AddressCandidate(address: neighbor, source: .estimatedNeighbor, hits: 0,
                                               lookupDistance: 15, score: 0))
            }
        }
        return RankedAddresses(candidates: ranked, confidence: confidence)
    }

    static func confidenceFor(ranked: [AddressCandidate], totalHits: Int, gpsAccuracy: Double) -> AddressConfidence {
        guard let top = ranked.first else { return .unresolved }
        let totalScore = ranked.reduce(0) { $0 + $1.score }
        let share = totalScore > 0 ? top.score / totalScore : 0
        let distinct = ranked.count

        // Residential lots are ~12-20 m wide, so anything worse than ~15 m of
        // GPS error cannot honestly pick one house.
        if gpsAccuracy > 25 { return .low }
        if gpsAccuracy <= 10 && share >= 0.75 && top.source == .center { return .high }
        if gpsAccuracy <= 15 && share >= 0.55 { return .medium }
        if distinct == 1 && gpsAccuracy <= 20 { return .medium }
        return .low
    }

    /// Same-side neighbours (+/-2). Ontario suburbs almost always number odd on one
    /// side and even on the other. These are clearly flagged as estimates in the UI.
    public static func neighborNumbers(of address: PostalAddress) -> [PostalAddress] {
        guard let n = address.numericHouseNumber, address.houseNumber == String(n) else { return [] }
        var result: [PostalAddress] = []
        for delta in [-2, 2] {
            let candidate = n + delta
            if candidate > 0 { result.append(address.withHouseNumber(String(candidate))) }
        }
        return result
    }
}
