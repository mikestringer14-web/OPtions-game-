import Foundation

public enum ServiceType: String, CaseIterable, Codable, Identifiable, Sendable {
    case roofing, siding, soffit, fascia, eavestroughs, gutterGuards, windows, doors, skylights, bathrooms, other

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .roofing: return "Roofing"
        case .siding: return "Siding"
        case .soffit: return "Soffit"
        case .fascia: return "Fascia"
        case .eavestroughs: return "Eavestroughs"
        case .gutterGuards: return "Gutter Guards"
        case .windows: return "Windows"
        case .doors: return "Doors"
        case .skylights: return "Skylights"
        case .bathrooms: return "Bathrooms"
        case .other: return "Other"
        }
    }

    /// Words that, when spoken in a dictation, indicate this service was discussed.
    /// Order matters: "gutter guard" must be checked before "gutter".
    var keywords: [String] {
        switch self {
        case .roofing: return ["roof", "roofing", "shingle", "shingles", "reroof", "re-roof"]
        case .siding: return ["siding", "vinyl siding", "cladding"]
        case .soffit: return ["soffit", "soffits"]
        case .fascia: return ["fascia"]
        case .eavestroughs: return ["eavestrough", "eavestroughs", "eaves trough", "gutter", "gutters", "downspout", "downspouts"]
        case .gutterGuards: return ["gutter guard", "gutter guards", "leaf guard", "gutter cover", "gutter covers"]
        case .windows: return ["window", "windows"]
        case .doors: return ["door", "doors", "patio door", "front door", "garage door"]
        case .skylights: return ["skylight", "skylights"]
        case .bathrooms: return ["bathroom", "bathrooms", "shower", "tub"]
        case .other: return []
        }
    }

    /// Detects services mentioned in free text. Never returns `.other` on its own.
    public static func detect(in text: String) -> [ServiceType] {
        let lower = " " + text.lowercased().replacingOccurrences(of: "\n", with: " ") + " "
        var found: [ServiceType] = []
        for service in ServiceType.allCases where service != .other {
            var matched = false
            for keyword in service.keywords {
                // Whole-word style match.
                if lower.range(of: "\\b" + NSRegularExpression.escapedPattern(for: keyword) + "\\b",
                               options: .regularExpression) != nil {
                    matched = true
                    break
                }
            }
            if matched { found.append(service) }
        }
        // "front door" is how reps describe walking up; only count doors when the word
        // appears with a replacement-type phrase.
        if found.contains(.doors) {
            let doorIntent = ["new door", "replace the door", "replace door", "door replacement",
                              "patio door", "entry door", "garage door", "doors replaced", "new doors", "replace doors", "replace the doors"]
            if !doorIntent.contains(where: { lower.contains($0) }) {
                found.removeAll { $0 == .doors }
            }
        }
        // A mention of "gutter guards" also matches "gutters"; keep eavestroughs only
        // if gutters are mentioned without the guard phrase.
        if found.contains(.gutterGuards) && found.contains(.eavestroughs) {
            let stripped = lower
                .replacingOccurrences(of: "gutter guards", with: "")
                .replacingOccurrences(of: "gutter guard", with: "")
                .replacingOccurrences(of: "gutter covers", with: "")
                .replacingOccurrences(of: "gutter cover", with: "")
            let stillHasTrough = ServiceType.eavestroughs.keywords.contains { kw in
                stripped.range(of: "\\b" + NSRegularExpression.escapedPattern(for: kw) + "\\b", options: .regularExpression) != nil
            }
            if !stillHasTrough { found.removeAll { $0 == .eavestroughs } }
        }
        return found
    }
}
