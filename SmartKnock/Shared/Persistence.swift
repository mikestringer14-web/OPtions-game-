import Foundation
import SwiftData

@MainActor
enum Persistence {
    static let schema = Schema([Visit.self, CanvassSession.self])

    /// Single container per process. The store lives in the App Group so the
    /// widget extension and intents write to the same database as the app.
    static let container: ModelContainer = {
        let url = storeURL()
        let config = ModelConfiguration("SmartKnock", schema: schema, url: url)
        do {
            return try ModelContainer(for: schema, configurations: [config])
        } catch {
            // Last resort: never crash a rep mid-street. Use a fresh store next to
            // the broken one and keep the old file for recovery.
            let fallback = url.deletingLastPathComponent().appendingPathComponent("SmartKnock-recovered.store")
            let cfg = ModelConfiguration("SmartKnockRecovered", schema: schema, url: fallback)
            return try! ModelContainer(for: schema, configurations: [cfg])
        }
    }()

    static func storeURL() -> URL {
        let base: URL
        if let group = AppGroup.containerURL {
            base = group.appendingPathComponent("Library/Application Support", isDirectory: true)
        } else {
            base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        }
        let dir = base.appendingPathComponent("SmartKnock", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        // Encrypted at rest; readable after first unlock so logging from the
        // lock screen and in the background keeps working.
        try? FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                                               ofItemAtPath: dir.path)
        return dir.appendingPathComponent("SmartKnock.store")
    }
}
