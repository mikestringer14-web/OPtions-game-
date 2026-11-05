import Foundation
import SwiftData

@MainActor
enum RetentionService {
    /// Deletes visits older than the configured retention period (0 = keep forever).
    static func purgeIfNeeded(context: ModelContext) {
        let days = SharedState.settings.retentionDays
        guard days > 0, let cutoff = Calendar.current.date(byAdding: .day, value: -days, to: Date()) else { return }
        try? context.delete(model: Visit.self, where: #Predicate { $0.createdAt < cutoff })
        try? context.delete(model: CanvassSession.self, where: #Predicate { $0.start < cutoff })
        try? context.save()
    }

    static func deleteAll(context: ModelContext) {
        try? context.delete(model: Visit.self)
        try? context.delete(model: CanvassSession.self)
        try? context.save()
        SharedState.pendingVisitID = nil
        SharedState.snapshot = .init()
    }
}
