import Foundation
import Security
import SwiftData
import SmartKnockCore

/// Connection state for an outside CRM.
enum CRMConnectionStatus: Equatable {
    /// No credentials or endpoint entered.
    case notConfigured
    /// Credentials entered but the provider has not confirmed which record
    /// types and fields the account may write.
    case awaitingVerification(String)
    /// Verified, authorized access.
    case connected
    case error(String)

    var title: String {
        switch self {
        case .notConfigured: return "Not connected"
        case .awaitingVerification: return "Awaiting verified access"
        case .connected: return "Connected"
        case .error: return "Error"
        }
    }
}

/// Maps a Smart Knock field to the CRM's field name for that record type.
struct CRMFieldMapping: Codable, Equatable {
    var addressField = ""
    var outcomeField = ""
    var notesField = ""
    var leadNameField = ""
    var leadPhoneField = ""
    var appointmentField = ""
    /// Smart Knock outcome raw value -> CRM status value.
    var outcomeValues: [String: String] = [:]
}

enum SyncPushResult {
    case accepted
    case rejected(String)
}

/// Any future integration implements this. Phase 1 never depends on it.
protocol CRMSyncProvider {
    var id: String { get }
    var displayName: String { get }
    func currentStatus() -> CRMConnectionStatus
    /// Confirms with the provider what this account is authorized to do.
    func verifyAccess() async -> CRMConnectionStatus
    /// Sends records. Only called when `verifyAccess` returned `.connected`.
    func push(_ records: [VisitRecord], mapping: CRMFieldMapping) async -> [UUID: SyncPushResult]
}

/// Knockio adapter.
///
/// IMPORTANT: At the time of writing there is no publicly documented Knockio
/// API for third-party apps to create door-knock records, and a sales rep
/// account usually has no admin/API permissions. This adapter therefore does
/// NOT send anything. It stores credentials securely and reports
/// `awaitingVerification` until a real, authorized endpoint and field list are
/// provided by Knockio or the company's Knockio administrator. Implement
/// `push` against that documented API at that point. Never scrape the web
/// app or reuse a browser session to get around permissions.
struct KnockioSyncProvider: CRMSyncProvider {
    let id = "knockio"
    let displayName = "Knockio"

    func currentStatus() -> CRMConnectionStatus {
        guard let token = Keychain.read("knockio.token"), !token.isEmpty else { return .notConfigured }
        return .awaitingVerification("Credentials saved. Waiting for Knockio to confirm an authorized import API and field list for door outcomes.")
    }

    func verifyAccess() async -> CRMConnectionStatus {
        currentStatus()
    }

    func push(_ records: [VisitRecord], mapping: CRMFieldMapping) async -> [UUID: SyncPushResult] {
        Dictionary(uniqueKeysWithValues: records.map { ($0.id, .rejected("Knockio API access has not been verified.")) })
    }

    static func saveToken(_ token: String) { Keychain.save(token, for: "knockio.token") }
    static func clearToken() { Keychain.delete("knockio.token") }
}

/// Tracks which visits are unsent / exported / synced / failed and drives
/// pushes to a verified provider.
@MainActor
enum SyncQueue {
    static func counts(context: ModelContext) -> [SyncState: Int] {
        var result: [SyncState: Int] = [:]
        let visits = (try? context.fetch(FetchDescriptor<Visit>())) ?? []
        for v in visits where !v.isPending { result[v.syncState, default: 0] += 1 }
        return result
    }

    /// Attempts a sync. Returns a message for the UI.
    static func run(provider: CRMSyncProvider, mapping: CRMFieldMapping, context: ModelContext) async -> String {
        let status = await provider.verifyAccess()
        guard status == .connected else {
            return "\(provider.displayName): \(status.title). Nothing was sent. Use CSV/JSON export in the meantime."
        }
        let unsentRaw = SyncState.unsent.rawValue, failedRaw = SyncState.failed.rawValue, exportedRaw = SyncState.exported.rawValue
        let d = FetchDescriptor<Visit>(predicate: #Predicate {
            $0.outcomeRaw != nil && ($0.syncStateRaw == unsentRaw || $0.syncStateRaw == failedRaw || $0.syncStateRaw == exportedRaw)
        })
        let visits = (try? context.fetch(d)) ?? []
        let results = await provider.push(visits.map(\.record), mapping: mapping)
        var ok = 0, bad = 0
        for v in visits {
            switch results[v.id] {
            case .accepted?: v.syncState = .synchronized; ok += 1
            case .rejected?: v.syncState = .failed; bad += 1
            case nil: break
            }
        }
        try? context.save()
        return "Synced \(ok), failed \(bad)."
    }
}

/// Minimal Keychain wrapper for API tokens (never stored in UserDefaults).
enum Keychain {
    private static let service = "SmartKnock"

    static func save(_ value: String, for key: String) {
        delete(key)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    static func read(_ key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var out: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(_ key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]
        SecItemDelete(query as CFDictionary)
    }
}
