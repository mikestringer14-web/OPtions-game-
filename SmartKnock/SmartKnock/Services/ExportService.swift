import Foundation
import SwiftData
import UIKit
import SmartKnockCore

/// Builds CSV / JSON / text files in a temporary folder for the Share Sheet,
/// and marks exported records so the sync queue knows what has left the phone.
@MainActor
enum ExportService {
    enum Format: String, CaseIterable, Identifiable {
        case csv = "CSV"
        case json = "JSON"
        case text = "Daily Summary"
        var id: String { rawValue }
    }

    static func visits(on day: Date, context: ModelContext) -> [Visit] {
        let start = Calendar.current.startOfDay(for: day)
        let end = Calendar.current.date(byAdding: .day, value: 1, to: start)!
        let d = FetchDescriptor<Visit>(predicate: #Predicate { $0.createdAt >= start && $0.createdAt < end },
                                       sortBy: [SortDescriptor(\.createdAt)])
        return (try? context.fetch(d)) ?? []
    }

    static func allVisits(context: ModelContext) -> [Visit] {
        (try? context.fetch(FetchDescriptor<Visit>(sortBy: [SortDescriptor(\.createdAt)]))) ?? []
    }

    static func allSessions(context: ModelContext) -> [CanvassSession] {
        (try? context.fetch(FetchDescriptor<CanvassSession>(sortBy: [SortDescriptor(\.start)]))) ?? []
    }

    static func stats(for day: Date, context: ModelContext) -> CanvassStats {
        let start = Calendar.current.startOfDay(for: day)
        let end = Calendar.current.date(byAdding: .day, value: 1, to: start)!
        return StatsCalculator.stats(visits: allVisits(context: context).map(\.record),
                                     sessions: allSessions(context: context).map(\.record), from: start, to: end)
    }

    static func dailySummaryText(for day: Date, context: ModelContext) -> String {
        let v = visits(on: day, context: context).map(\.record)
        return DailyReport.text(for: day, visits: v, stats: stats(for: day, context: context))
    }

    /// Writes an export file and returns its URL.
    static func makeFile(_ format: Format, visits: [Visit], day: Date?, context: ModelContext, markExported: Bool = true) throws -> URL {
        let stamp = fileStamp(day ?? Date())
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("exports", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url: URL
        let data: Data
        switch format {
        case .csv:
            url = dir.appendingPathComponent("SmartKnock-\(stamp).csv")
            data = Data(CSVExporter.csv(visits.map(\.record)).utf8)
        case .json:
            url = dir.appendingPathComponent("SmartKnock-\(stamp).json")
            let sessions = allSessions(context: context).map(\.record)
            data = try BackupFile.encoder().encode(BackupFile(visits: visits.map(\.record), sessions: sessions))
        case .text:
            url = dir.appendingPathComponent("SmartKnock-Summary-\(stamp).txt")
            data = Data(dailySummaryText(for: day ?? Date(), context: context).utf8)
        }
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        if markExported { markAsExported(visits, context: context) }
        return url
    }

    static func markAsExported(_ visits: [Visit], context: ModelContext) {
        for v in visits where v.syncState == .unsent || v.syncState == .failed {
            v.syncState = .exported
        }
        try? context.save()
    }

    static func copyToClipboard(_ text: String) {
        UIPasteboard.general.string = text
    }

    static func fileStamp(_ d: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: d)
    }

    /// One-visit text used for "Copy" and for pasting into a CRM by hand.
    static func visitSummary(_ v: Visit) -> String {
        var lines: [String] = []
        lines.append("\(v.outcome?.title ?? "Not logged") - \(v.address.isEmpty ? v.displayAddress : v.address.singleLine)")
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .short
        lines.append("Visited: \(f.string(from: v.timestamp))")
        if v.confidence != .confirmed { lines.append("Address confidence: \(v.confidence.title)") }
        if let d = v.followUpDate { lines.append("Follow-up: \(f.string(from: d))") }
        if !v.notes.isEmpty { lines.append("Notes: \(v.notes)") }
        if let lead = v.lead { lines.append(""); lines.append(lead.summary) }
        return lines.joined(separator: "\n")
    }
}

/// Full backup / restore of everything on the phone.
@MainActor
enum BackupService {
    static func makeBackup(context: ModelContext) throws -> URL {
        let backup = BackupFile(visits: ExportService.allVisits(context: context).map(\.record),
                                sessions: ExportService.allSessions(context: context).map(\.record))
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("SmartKnock-Backup-\(ExportService.fileStamp(Date())).json")
        try BackupFile.encoder().encode(backup).write(to: url, options: [.atomic, .completeFileProtection])
        return url
    }

    /// Merges a backup into the store. Existing records with the same ID are
    /// replaced only if the backup copy is newer. Returns (added, updated).
    static func restore(from url: URL, context: ModelContext) throws -> (Int, Int) {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let data = try Data(contentsOf: url)
        let backup = try BackupFile.decoder().decode(BackupFile.self, from: data)
        var added = 0, updated = 0
        for r in backup.visits {
            let id = r.id
            var d = FetchDescriptor<Visit>(predicate: #Predicate { $0.id == id })
            d.fetchLimit = 1
            if let existing = try context.fetch(d).first {
                if r.updatedAt > existing.updatedAt {
                    existing.apply(r)
                    updated += 1
                }
            } else {
                let v = Visit(id: r.id, sessionID: r.sessionID, latitude: r.latitude, longitude: r.longitude,
                              accuracy: r.gpsAccuracy, autoDetected: r.autoDetected)
                v.apply(r)
                context.insert(v)
                added += 1
            }
        }
        for s in backup.sessions {
            let id = s.id
            var d = FetchDescriptor<CanvassSession>(predicate: #Predicate { $0.id == id })
            d.fetchLimit = 1
            if try context.fetch(d).first == nil {
                let cs = CanvassSession(start: s.start)
                cs.id = s.id
                cs.end = s.end ?? s.start
                cs.distanceMeters = s.distanceMeters
                cs.pausedSeconds = s.pausedSeconds
                context.insert(cs)
            }
        }
        try context.save()
        VisitLogger.refreshSnapshot(lastLogged: nil)
        return (added, updated)
    }
}
