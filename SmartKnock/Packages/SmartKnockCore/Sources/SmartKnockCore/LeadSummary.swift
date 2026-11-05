import Foundation

/// Everything the rep entered or dictated for a booking.
public struct LeadInput: Codable, Equatable, Sendable {
    public var homeownerName: String = ""
    public var phone: String = ""
    public var email: String = ""
    public var address: String = ""
    public var appointmentDate: Date?
    /// True when the rep set a specific time (not just a day).
    public var hasAppointmentTime: Bool = false
    public var services: [ServiceType] = []
    public var otherServiceDescription: String = ""
    public var projectDetails: String = ""
    public var notes: String = ""
    public var referralSource: String = ""
    public var followUp: String = ""
    /// Raw voice-to-text transcript, exactly as recognized.
    public var transcript: String = ""

    public init() {}
}

/// Pulls obvious facts out of a dictated transcript. It only copies what was
/// said; it never guesses.
public struct TranscriptFacts: Equatable, Sendable {
    public var phone: String?
    public var email: String?
    public var name: String?
    public var services: [ServiceType] = []
    /// Sentences describing problems or the reason for the visit.
    public var concernSentences: [String] = []
    /// All sentences except those that only carry contact details.
    public var jobSentences: [String] = []
}

public enum TranscriptExtractor {

    static let phonePattern = #"(?:\+?1[\s.\-]?)?\(?\b(\d{3})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})\b"#
    static let emailPattern = #"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"#
    static let namePattern = #"(?:(?:his|her|their|the homeowner'?s?|owner'?s?) name is|name is|named|spoke (?:with|to)|talked (?:with|to)|homeowner is|met with)\s+([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)?)"#

    static let concernWords = [
        "leak", "leaking", "leaks", "missing", "damage", "damaged", "curl", "curling", "granule", "granules",
        "rot", "rotting", "rotten", "sag", "sagging", "moss", "ice dam", "draft", "drafty", "drafts",
        "fog", "foggy", "fogged", "condensation", "years old", "old", "crack", "cracked", "peeling",
        "faded", "overflow", "overflowing", "clog", "clogged", "insurance", "storm", "wind", "hail",
        "mould", "mold", "water", "stain", "stains", "worried", "concern", "concerned", "wants",
        "looking to", "interested", "quote", "estimate", "replace", "replacement", "repair", "lifting", "blown off"
    ]

    public static func extract(from transcript: String) -> TranscriptFacts {
        var facts = TranscriptFacts()
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return facts }

        if let m = firstMatch(phonePattern, in: text) {
            facts.phone = formatPhone(m)
        }
        if let e = firstMatch(emailPattern, in: text) { facts.email = e }
        if let n = firstCapture(namePattern, in: text) { facts.name = n }
        facts.services = ServiceType.detect(in: text)

        for sentence in sentences(text) {
            let lower = sentence.lowercased()
            let isContactOnly = isContactSentence(sentence)
            if !isContactOnly { facts.jobSentences.append(sentence) }
            if !isContactOnly && concernWords.contains(where: { containsWord(lower, $0) }) {
                facts.concernSentences.append(sentence)
            }
        }
        return facts
    }

    /// A sentence that is basically just "her number is 905..." or "name is Jane".
    static func isContactSentence(_ s: String) -> Bool {
        let lower = s.lowercased()
        let hasPhone = firstMatch(phonePattern, in: s) != nil
        let hasEmail = firstMatch(emailPattern, in: s) != nil
        let hasName = firstCapture(namePattern, in: s) != nil
        guard hasPhone || hasEmail || hasName else { return false }
        // If the sentence also talks about the job, keep it as job info.
        let jobish = concernWords.contains { containsWord(lower, $0) } || !ServiceType.detect(in: s).isEmpty
        return !jobish
    }

    public static func sentences(_ text: String) -> [String] {
        var result: [String] = []
        var current = ""
        let chars = Array(text)
        for (i, ch) in chars.enumerated() {
            if ch == "\n" {
                let t = current.trimmingCharacters(in: .whitespaces)
                if !t.isEmpty { result.append(t) }
                current = ""
                continue
            }
            current.append(ch)
            if ch == "." || ch == "!" || ch == "?" {
                // Do not split decimals like 2.5 or initials inside emails.
                let next: Character? = i + 1 < chars.count ? chars[i + 1] : nil
                if next == nil || next == " " || next == "\n" {
                    let t = current.trimmingCharacters(in: .whitespaces)
                    if !t.isEmpty { result.append(t) }
                    current = ""
                }
            }
        }
        let t = current.trimmingCharacters(in: .whitespaces)
        if !t.isEmpty { result.append(t) }
        return result.map { s in
            // Ensure terminal punctuation so paragraphs read cleanly.
            if let last = s.last, ".!?".contains(last) { return s }
            return s + "."
        }
    }

    public static func formatPhone(_ raw: String) -> String {
        let digits = raw.filter(\.isNumber)
        let ten = digits.count == 11 && digits.hasPrefix("1") ? String(digits.dropFirst()) : digits
        guard ten.count == 10 else { return raw }
        let a = ten.prefix(3), b = ten.dropFirst(3).prefix(3), c = ten.suffix(4)
        return "(\(a)) \(b)-\(c)"
    }

    static func containsWord(_ haystack: String, _ word: String) -> Bool {
        haystack.range(of: "\\b" + NSRegularExpression.escapedPattern(for: word) + "\\b", options: .regularExpression) != nil
    }

    static func firstMatch(_ pattern: String, in text: String) -> String? {
        guard let re = try? NSRegularExpression(pattern: pattern) else { return nil }
        let ns = text as NSString
        guard let m = re.firstMatch(in: text, range: NSRange(location: 0, length: ns.length)) else { return nil }
        return ns.substring(with: m.range)
    }

    static func firstCapture(_ pattern: String, in text: String) -> String? {
        guard let re = try? NSRegularExpression(pattern: pattern) else { return nil }
        let ns = text as NSString
        guard let m = re.firstMatch(in: text, range: NSRange(location: 0, length: ns.length)),
              m.numberOfRanges > 1, m.range(at: 1).location != NSNotFound else { return nil }
        let name = ns.substring(with: m.range(at: 1))
        // Words that commonly follow "spoke with" but are not names.
        let stop: Set<String> = ["The", "He", "She", "They", "Him", "Her", "Them", "Homeowner", "Owner", "A", "An"]
        if let firstWord = name.split(separator: " ").first, stop.contains(String(firstWord)) { return nil }
        return name
    }
}

/// Builds the three-paragraph lead summary. Missing mandatory fields are
/// written as "Not provided"; nothing is invented.
public struct LeadSummaryFormatter {
    public static let notProvided = "Not provided"

    public var timeZone: TimeZone
    public var locale: Locale

    public init(timeZone: TimeZone = .current, locale: Locale = Locale(identifier: "en_CA")) {
        self.timeZone = timeZone
        self.locale = locale
    }

    /// Merges form fields with transcript facts. Form fields always win.
    public func resolved(_ input: LeadInput) -> (input: LeadInput, facts: TranscriptFacts) {
        let facts = TranscriptExtractor.extract(from: input.transcript)
        var merged = input
        if merged.homeownerName.isBlank, let n = facts.name { merged.homeownerName = n }
        if merged.phone.isBlank, let p = facts.phone { merged.phone = p }
        if merged.email.isBlank, let e = facts.email { merged.email = e }
        if merged.services.isEmpty { merged.services = facts.services }
        return (merged, facts)
    }

    public func paragraphs(for raw: LeadInput, bookedAt: Date? = nil) -> [String] {
        let (input, facts) = resolved(raw)

        // Paragraph 1: contact
        var p1 = "Contact Information: "
        p1 += "Homeowner: \(input.homeownerName.orNotProvided). "
        p1 += "Phone: \(input.phone.isBlank ? Self.notProvided : TranscriptExtractor.formatPhone(input.phone)). "
        p1 += "Address: \(input.address.orNotProvided)."
        if !input.email.isBlank { p1 += " Email: \(input.email)." }

        // Paragraph 2: appointment
        var p2 = "Appointment Information: "
        if let booked = bookedAt { p2 += "Booked \(format(booked, dateStyle: true, timeStyle: false)). " }
        if let date = input.appointmentDate {
            p2 += "Appointment date: \(format(date, dateStyle: true, timeStyle: false)). "
            p2 += "Appointment time: \(input.hasAppointmentTime ? format(date, dateStyle: false, timeStyle: true) : Self.notProvided). "
        } else {
            p2 += "Appointment date: \(Self.notProvided). Appointment time: \(Self.notProvided). "
        }
        let serviceNames = input.services.map { s -> String in
            if s == .other, !input.otherServiceDescription.isBlank { return "Other (\(input.otherServiceDescription))" }
            return s.title
        }
        p2 += "Services requested: \(serviceNames.isEmpty ? Self.notProvided : serviceNames.joined(separator: ", ")). "
        let reason = facts.concernSentences.first ?? firstSentence(of: input.projectDetails)
        p2 += "Reason for consultation: \(reason.map { $0.trimmedTrailingPeriod } ?? Self.notProvided)."

        // Paragraph 3: job detail
        var parts: [String] = []
        if !input.projectDetails.isBlank { parts.append(input.projectDetails.sentenceTerminated) }
        let detailsLower = input.projectDetails.lowercased()
        parts.append(contentsOf: facts.jobSentences.filter { !detailsLower.contains($0.lowercased().trimmedTrailingPeriod) })
        if !input.notes.isBlank { parts.append("Notes: " + input.notes.sentenceTerminated) }
        if !input.referralSource.isBlank { parts.append("Referral source: " + input.referralSource.sentenceTerminated) }
        if !input.followUp.isBlank { parts.append("Follow-up required: " + input.followUp.sentenceTerminated) }
        let p3 = "Detailed Job Information: " + (parts.isEmpty ? Self.notProvided + "." : parts.joined(separator: " "))

        return [p1, p2, p3]
    }

    public func summary(for input: LeadInput, bookedAt: Date? = nil) -> String {
        paragraphs(for: input, bookedAt: bookedAt).joined(separator: "\n\n")
    }

    /// Mandatory fields that are still empty after merging the transcript.
    public func missingMandatoryFields(_ raw: LeadInput) -> [String] {
        let input = resolved(raw).input
        var missing: [String] = []
        if input.homeownerName.isBlank { missing.append("Homeowner name") }
        if input.phone.isBlank { missing.append("Phone number") }
        if input.address.isBlank { missing.append("Address") }
        if input.appointmentDate == nil { missing.append("Appointment date") }
        if !input.hasAppointmentTime { missing.append("Appointment time") }
        if input.services.isEmpty { missing.append("Service requested") }
        return missing
    }

    private func firstSentence(of text: String) -> String? {
        TranscriptExtractor.sentences(text).first
    }

    private func format(_ date: Date, dateStyle: Bool, timeStyle: Bool) -> String {
        let f = DateFormatter()
        f.locale = locale
        f.timeZone = timeZone
        if dateStyle && !timeStyle {
            f.dateFormat = "EEEE, MMMM d, yyyy"
        } else if timeStyle && !dateStyle {
            f.dateFormat = "h:mm a"
        } else {
            f.dateFormat = "EEEE, MMMM d, yyyy 'at' h:mm a"
        }
        return f.string(from: date)
    }
}

extension String {
    var isBlank: Bool { trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    var orNotProvided: String { isBlank ? LeadSummaryFormatter.notProvided : trimmingCharacters(in: .whitespacesAndNewlines) }
    var trimmedTrailingPeriod: String {
        var s = trimmingCharacters(in: .whitespacesAndNewlines)
        while let last = s.last, last == "." { s.removeLast() }
        return s
    }
    var sentenceTerminated: String {
        let s = trimmingCharacters(in: .whitespacesAndNewlines)
        guard let last = s.last else { return s }
        return ".!?".contains(last) ? s : s + "."
    }
}
