import CoreLocation
import Foundation

/// Wraps CLLocationManager for canvassing: high accuracy while walking,
/// background updates with the blue indicator, and relaunch support.
@MainActor
final class LocationService: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var backgroundSession: CLBackgroundActivitySession?

    var onLocation: ((CLLocation) -> Void)?
    var onAuthorizationChange: ((CLAuthorizationStatus) -> Void)?

    private(set) var isRunning = false

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        manager.activityType = .fitness
        manager.pausesLocationUpdatesAutomatically = false
    }

    var authorizationStatus: CLAuthorizationStatus { manager.authorizationStatus }
    var accuracyAuthorization: CLAccuracyAuthorization { manager.accuracyAuthorization }
    var lastLocation: CLLocation? { manager.location }

    func requestWhenInUse() {
        manager.requestWhenInUseAuthorization()
    }

    /// "Always" lets iOS relaunch the app if it is terminated mid-session.
    /// Only asked for after When In Use is granted, as Apple requires.
    func requestAlways() {
        manager.requestAlwaysAuthorization()
    }

    /// Precise location is essential to tell houses apart.
    func requestTemporaryPrecise() {
        manager.requestTemporaryFullAccuracyAuthorization(withPurposeKey: "DoorDetection")
    }

    func start() {
        guard !isRunning else { return }
        isRunning = true
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
        // Keeps When In Use authorization valid while the app is in the background.
        backgroundSession = CLBackgroundActivitySession()
        manager.allowsBackgroundLocationUpdates = true
        manager.showsBackgroundLocationIndicator = true
        manager.startUpdatingLocation()
        if manager.authorizationStatus == .authorizedAlways {
            // Lets iOS relaunch us after a crash or memory-pressure termination.
            manager.startMonitoringSignificantLocationChanges()
        }
        if manager.accuracyAuthorization == .reducedAccuracy { requestTemporaryPrecise() }
    }

    func stop() {
        isRunning = false
        manager.stopUpdatingLocation()
        manager.stopMonitoringSignificantLocationChanges()
        manager.allowsBackgroundLocationUpdates = false
        backgroundSession?.invalidate()
        backgroundSession = nil
    }

    /// Lower power while on a break: coarser fixes, updates only on movement.
    func setLowPower(_ low: Bool) {
        manager.desiredAccuracy = low ? kCLLocationAccuracyHundredMeters : kCLLocationAccuracyBest
        manager.distanceFilter = low ? 50 : kCLDistanceFilterNone
    }

    // MARK: Delegate

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        Task { @MainActor in
            for l in locations { self.onLocation?(l) }
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in self.onAuthorizationChange?(status) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // kCLErrorLocationUnknown is transient; keep running.
    }
}
