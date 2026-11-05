import AppIntents
import SwiftUI
import WidgetKit

/// Control Center / Lock Screen controls (iOS 18+). Can also be put on the
/// Action Button on iPhone 15 Pro and later.
@available(iOSApplicationExtension 18.0, *)
struct NoAnswerControl: ControlWidget {
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "SmartKnock.NoAnswerControl") {
            ControlWidgetButton(action: LogOutcomeIntent(outcome: .noAnswer)) {
                Label("No Answer", systemImage: "door.left.hand.closed")
            }
        }
        .displayName("Log No Answer")
        .description("Logs No Answer for the door you just left.")
    }
}

@available(iOSApplicationExtension 18.0, *)
struct OpenLoggerControl: ControlWidget {
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "SmartKnock.OpenLoggerControl") {
            ControlWidgetButton(action: OpenLoggerIntent()) {
                Label("Door Logger", systemImage: "square.grid.3x3.fill")
            }
        }
        .displayName("Open Door Logger")
    }
}
