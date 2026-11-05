import Foundation

public struct CanvassStats: Equatable, Sendable {
    public var doors: Int = 0
    public var counts: [Outcome: Int] = [:]
    public var unlogged: Int = 0
    public var distanceMeters: Double = 0
    public var activeSeconds: Double = 0

    public func count(_ o: Outcome) -> Int { counts[o] ?? 0 }

    public var bookings: Int { count(.booking) }

    /// Bookings divided by doors knocked (logged visits).
    public var bookingRatePerDoor: Double {
        doors > 0 ? Double(bookings) / Double(doors) : 0
    }

    /// Bookings divided by doors where someone answered.
    public var bookingRatePerContact: Double {
        let contacts = counts.filter { $0.key.isContact }.reduce(0) { $0 + $1.value }
        return contacts > 0 ? Double(bookings) / Double(contacts) : 0
    }

    public var contacts: Int { counts.filter { $0.key.isContact }.reduce(0) { $0 + $1.value } }

    public var doorsPerHour: Double {
        activeSeconds >= 60 ? Double(doors) / (activeSeconds / 3600) : 0
    }
}

public struct DailyCount: Equatable, Sendable, Identifiable {
    public var day: Date
    public var doors: Int
    public var bookings: Int
    public var id: Date { day }
}

public enum StatsCalculator {
    /// Stats for visits whose timestamp falls in [start, end).
    public static func stats(visits: [VisitRecord], sessions: [SessionRecord],
                             from start: Date, to end: Date, now: Date = Date()) -> CanvassStats {
        var s = CanvassStats()
        for v in visits where v.timestamp >= start && v.timestamp < end {
            if let o = v.outcome {
                s.doors += 1
                s.counts[o, default: 0] += 1
            } else {
                s.unlogged += 1
            }
        }
        for session in sessions where session.start < end && (session.end ?? now) >= start {
            s.distanceMeters += session.distanceMeters
            s.activeSeconds += session.activeSeconds(now: now)
        }
        return s
    }

    /// Doors and bookings per calendar day, oldest first, for charts.
    public static func daily(visits: [VisitRecord], days: Int, endingOn day: Date,
                             calendar: Calendar = .current) -> [DailyCount] {
        let endDay = calendar.startOfDay(for: day)
        var result: [DailyCount] = []
        for offset in stride(from: days - 1, through: 0, by: -1) {
            guard let d = calendar.date(byAdding: .day, value: -offset, to: endDay),
                  let next = calendar.date(byAdding: .day, value: 1, to: d) else { continue }
            let inDay = visits.filter { $0.timestamp >= d && $0.timestamp < next && $0.outcome != nil }
            result.append(DailyCount(day: d, doors: inDay.count, bookings: inDay.filter { $0.outcome == .booking }.count))
        }
        return result
    }
}

public enum DailyReport {
    /// Plain-text daily summary for Messages/email.
    public static func text(for day: Date, visits: [VisitRecord], stats: CanvassStats,
                            timeZone: TimeZone = .current) -> String {
        let df = DateFormatter()
        df.locale = Locale(identifier: "en_CA")
        df.timeZone = timeZone
        df.dateFormat = "EEEE, MMMM d, yyyy"
        let tf = DateFormatter()
        tf.locale = Locale(identifier: "en_CA")
        tf.timeZone = timeZone
        tf.dateFormat = "h:mm a"

        var out = "Smart Knock Daily Summary\n\(df.string(from: day))\n\n"
        out += "Doors logged: \(stats.doors)\n"
        out += "Contacts (answered): \(stats.contacts)\n"
        out += "Bookings: \(stats.bookings)\n"
        out += String(format: "Booking rate: %.1f%% of doors, %.1f%% of contacts\n",
                      stats.bookingRatePerDoor * 100, stats.bookingRatePerContact * 100)
        out += String(format: "Distance walked: %.2f km\n", stats.distanceMeters / 1000)
        let mins = Int(stats.activeSeconds / 60)
        out += "Canvassing time: \(mins / 60)h \(mins % 60)m\n"
        out += String(format: "Doors per hour: %.1f\n", stats.doorsPerHour)
        if stats.unlogged > 0 { out += "Stops not yet logged: \(stats.unlogged)\n" }
        out += "\nBreakdown:\n"
        for o in Outcome.padOrder where stats.count(o) > 0 {
            out += "  \(o.title): \(stats.count(o))\n"
        }

        let bookings = visits.filter { $0.outcome == .booking }.sorted { $0.timestamp < $1.timestamp }
        if !bookings.isEmpty {
            out += "\nBookings:\n"
            for b in bookings {
                out += "\n- \(b.address.singleLine.isEmpty ? "Address not confirmed" : b.address.singleLine) (\(tf.string(from: b.timestamp)))\n"
                if let summary = b.lead?.summary, !summary.isEmpty {
                    out += summary.split(separator: "\n").map { "  " + $0 }.joined(separator: "\n") + "\n"
                }
            }
        }
        let followUps = visits.filter { $0.outcome == .callBack || $0.outcome == .future }
        if !followUps.isEmpty {
            out += "\nFollow-ups:\n"
            for f in followUps.sorted(by: { $0.timestamp < $1.timestamp }) {
                let when = f.followUpDate.map { " on " + df.string(from: $0) } ?? ""
                out += "- \(f.outcome!.title): \(f.address.singleLine.isEmpty ? "Address not confirmed" : f.address.singleLine)\(when)"
                if !f.notes.isEmpty { out += " (\(f.notes))" }
                out += "\n"
            }
        }
        let noSolicit = visits.filter { $0.outcome == .noSoliciting }
        if !noSolicit.isEmpty {
            out += "\nNo-soliciting addresses:\n"
            for n in noSolicit { out += "- \(n.address.singleLine.isEmpty ? "Address not confirmed" : n.address.singleLine)\n" }
        }
        return out
    }
}
