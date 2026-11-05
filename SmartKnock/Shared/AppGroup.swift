import Foundation

/// Resolves the App Group shared by the app and its widget extension.
/// The identifier comes from the APP_GROUP_ID build setting via Info.plist,
/// so changing the bundle prefix in project.yml is the only edit needed.
enum AppGroup {
    static var identifier: String {
        (Bundle.main.object(forInfoDictionaryKey: "SKAppGroupIdentifier") as? String) ?? "group.com.example.smartknock"
    }

    /// Shared container, or nil if the App Group entitlement is missing
    /// (for example with some free signing setups). Callers fall back to
    /// the app's own sandbox, and widgets show "Open app" instead of data.
    static var containerURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: identifier)
    }

    static var defaults: UserDefaults {
        UserDefaults(suiteName: identifier) ?? .standard
    }

    static var isAvailable: Bool { containerURL != nil }
}
