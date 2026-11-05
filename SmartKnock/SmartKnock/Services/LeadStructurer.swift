import Foundation
import SmartKnockCore
#if canImport(FoundationModels)
import FoundationModels
#endif

/// Fills empty lead fields from a dictated transcript.
///
/// 1. Rule-based extraction (always available, deterministic).
/// 2. On iPhones with Apple Intelligence (iOS 26+), Apple's on-device model
///    is asked to pull out the same facts. Everything runs on the phone; no
///    customer data is sent anywhere.
/// Every suggestion is checked against the transcript text, so a value the
/// homeowner never said cannot be added. Suggestions only fill blank fields.
@MainActor
enum LeadStructurer {
    struct Suggestions {
        var name: String?
        var phone: String?
        var email: String?
        var services: [ServiceType] = []
        var appointmentDate: Date?
        var hasTime = false
        var usedOnDeviceModel = false
    }

    static var onDeviceModelAvailable: Bool {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *) {
            if case .available = SystemLanguageModel.default.availability { return true }
        }
        #endif
        return false
    }

    static func suggest(from transcript: String) async -> Suggestions {
        let facts = TranscriptExtractor.extract(from: transcript)
        var s = Suggestions(name: facts.name, phone: facts.phone, email: facts.email, services: facts.services)
        if let found = detectAppointment(in: transcript) {
            s.appointmentDate = found.0
            s.hasTime = found.1
        }

        #if canImport(FoundationModels)
        if #available(iOS 26.0, *), onDeviceModelAvailable {
            if let m = try? await OnDeviceLeadExtractor.extract(transcript) {
                s.usedOnDeviceModel = true
                let lower = transcript.lowercased()
                let digits = transcript.filter(\.isNumber)
                if s.name == nil, !m.homeownerName.isEmpty,
                   lower.contains(m.homeownerName.lowercased()) {
                    s.name = m.homeownerName
                }
                let modelDigits = m.phoneNumber.filter(\.isNumber)
                if s.phone == nil, modelDigits.count >= 10, digits.contains(modelDigits.suffix(10)) {
                    s.phone = TranscriptExtractor.formatPhone(modelDigits)
                }
                if s.email == nil, !m.email.isEmpty, lower.contains(m.email.lowercased()) {
                    s.email = m.email
                }
                if s.services.isEmpty {
                    // Only accept services whose keywords actually appear in the transcript.
                    let detected = Set(ServiceType.detect(in: transcript))
                    s.services = m.services.compactMap { ServiceType(rawValue: $0) }.filter { detected.contains($0) }
                }
            }
        }
        #endif
        return s
    }

    /// Uses NSDataDetector to find a spoken date/time ("Thursday at 6:30").
    static func detectAppointment(in text: String) -> (Date, Bool)? {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.date.rawValue) else { return nil }
        let ns = text as NSString
        let matches = detector.matches(in: text, range: NSRange(location: 0, length: ns.length))
        // Prefer a future date.
        guard let m = matches.first(where: { ($0.date ?? .distantPast) > Date().addingTimeInterval(-3600) }) ?? matches.first,
              let date = m.date else { return nil }
        let phrase = ns.substring(with: m.range).lowercased()
        let hasTime = phrase.contains(":") || phrase.contains("am") || phrase.contains("pm") || phrase.contains("a.m") ||
            phrase.contains("p.m") || phrase.contains("noon") || phrase.contains("o'clock")
        return (date, hasTime)
    }
}

#if canImport(FoundationModels)
@available(iOS 26.0, *)
@Generable
struct ExtractedLead {
    @Guide(description: "The homeowner's name exactly as spoken. Empty string if no name was said.")
    var homeownerName: String
    @Guide(description: "The phone number exactly as spoken, digits only. Empty string if none was said.")
    var phoneNumber: String
    @Guide(description: "Email address if one was spelled out. Empty string otherwise.")
    var email: String
    @Guide(description: "Services discussed. Use only these values: roofing, siding, soffit, fascia, eavestroughs, gutterGuards, windows, doors, skylights, bathrooms, other.")
    var services: [String]
}

@available(iOS 26.0, *)
enum OnDeviceLeadExtractor {
    static func extract(_ transcript: String) async throws -> ExtractedLead {
        let session = LanguageModelSession(instructions: """
        You extract facts from a door-to-door sales rep's spoken notes about a home improvement lead.
        Only copy information that is explicitly stated in the notes. Never guess, infer or make up names,
        numbers or services. If something is not stated, return an empty value.
        """)
        let response = try await session.respond(to: "Notes:\n\(transcript)", generating: ExtractedLead.self)
        return response.content
    }
}
#endif
