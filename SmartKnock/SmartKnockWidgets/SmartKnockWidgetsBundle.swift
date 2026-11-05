import SwiftUI
import WidgetKit

@main
struct SmartKnockWidgetsBundle: WidgetBundle {
    var body: some Widget {
        QuickLogWidget()
        LockScreenWidget()
        CanvassLiveActivity()
        if #available(iOSApplicationExtension 18.0, *) {
            NoAnswerControl()
            OpenLoggerControl()
        }
    }
}
