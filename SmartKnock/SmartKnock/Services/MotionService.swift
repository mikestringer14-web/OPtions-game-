import CoreMotion
import Foundation
import SmartKnockCore

/// Reports walking / stationary / driving from the motion coprocessor.
/// Cheap on battery and helps reject false stops (red lights, driving).
@MainActor
final class MotionService {
    private let activityManager = CMMotionActivityManager()
    var onHint: ((MotionHint) -> Void)?
    private(set) var current: MotionHint = .unknown

    static var isAvailable: Bool { CMMotionActivityManager.isActivityAvailable() }

    static var authorizationStatus: CMAuthorizationStatus { CMMotionActivityManager.authorizationStatus() }

    func start() {
        guard Self.isAvailable else { return }
        activityManager.startActivityUpdates(to: .main) { [weak self] activity in
            guard let self, let a = activity, a.confidence != .low else { return }
            let hint: MotionHint
            if a.automotive { hint = .automotive }
            else if a.cycling { hint = .cycling }
            else if a.running { hint = .running }
            else if a.walking { hint = .walking }
            else if a.stationary { hint = .stationary }
            else { hint = .unknown }
            MainActor.assumeIsolated {
                self.current = hint
                self.onHint?(hint)
            }
        }
    }

    func stop() {
        activityManager.stopActivityUpdates()
        current = .unknown
    }
}
