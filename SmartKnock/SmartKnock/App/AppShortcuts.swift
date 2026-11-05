import AppIntents

/// Siri phrases, Spotlight, and Action Button support.
/// Settings > Action Button > Shortcut > Smart Knock > "Log Door Outcome".
struct SmartKnockShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: LogOutcomeIntent(outcome: .noAnswer),
                    phrases: ["Log no answer in \(.applicationName)",
                              "\(.applicationName) no answer"],
                    shortTitle: "No Answer",
                    systemImageName: "door.left.hand.closed")
        AppShortcut(intent: LogOutcomeIntent(),
                    phrases: ["Log \(\.$outcome) in \(.applicationName)",
                              "\(.applicationName) \(\.$outcome)"],
                    shortTitle: "Log Outcome",
                    systemImageName: "square.grid.3x3.fill")
        AppShortcut(intent: OpenLoggerIntent(),
                    phrases: ["Open \(.applicationName) logger"],
                    shortTitle: "Open Logger",
                    systemImageName: "hand.tap.fill")
    }
}
