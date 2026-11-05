import CoreLocation
import MapKit
import SmartKnockCore

enum AddressLookupError: Error {
    case offline
    case throttled
    case noResult
}

/// Turns a stop location into ranked street addresses using Apple's
/// reverse geocoder. It looks up the stop itself plus points along the street
/// (based on the direction the rep was walking) to surface the neighbours.
@MainActor
final class AddressResolver {
    private let geocoder = CLGeocoder()
    /// Cache keyed by ~5 m grid cell so revisits and retries do not re-query.
    private var cache: [String: PostalAddress?] = [:]

    func resolve(center: GeoPoint, approachBearing: Double?, accuracy: Double,
                 visitedKeys: Set<String>, settings: AppSettings) async throws -> RankedAddresses {
        var points: [(GeoPoint, CandidateSource, Double)] = [(center, .center, 0)]
        let depth = settings.addressLookupDepth
        if depth >= 3 {
            if let b = approachBearing {
                points.append((GeoMath.offset(center, meters: 14, bearing: b), .alongStreet, 14))
                points.append((GeoMath.offset(center, meters: 14, bearing: b + 180), .alongStreet, 14))
            } else {
                points.append((GeoMath.offset(center, meters: 9, bearing: 0), .nearby, 9))
                points.append((GeoMath.offset(center, meters: 9, bearing: 180), .nearby, 9))
            }
        }
        if depth >= 5 {
            let side = (approachBearing ?? 0) + 90
            points.append((GeoMath.offset(center, meters: 8, bearing: side), .nearby, 8))
            points.append((GeoMath.offset(center, meters: 8, bearing: side + 180), .nearby, 8))
        }

        var hits: [GeocodeHit] = []
        var sawOffline = false
        for (point, source, dist) in points {
            do {
                if let addr = try await reverseGeocode(point) {
                    hits.append(GeocodeHit(address: addr, source: source, lookupDistance: dist))
                }
            } catch AddressLookupError.offline {
                sawOffline = true
                break
            } catch AddressLookupError.throttled {
                // Use what we have rather than wait; the centre lookup is the important one.
                break
            } catch {
                continue
            }
        }
        if hits.isEmpty && sawOffline { throw AddressLookupError.offline }
        return AddressRanker.rank(hits: hits, gpsAccuracy: accuracy, alreadyVisitedKeys: visitedKeys,
                                  includeNeighborEstimates: settings.suggestNeighborNumbers)
    }

    /// Single lookup, used when the rep taps a spot on the map.
    func address(at point: GeoPoint) async throws -> PostalAddress? {
        try await reverseGeocode(point)
    }

    private func reverseGeocode(_ p: GeoPoint) async throws -> PostalAddress? {
        let key = String(format: "%.5f,%.5f", (p.latitude * 20000).rounded() / 20000, (p.longitude * 20000).rounded() / 20000)
        if let cached = cache[key] { return cached }
        let location = CLLocation(latitude: p.latitude, longitude: p.longitude)
        do {
            let placemarks = try await geocoder.reverseGeocodeLocation(location, preferredLocale: Locale(identifier: "en_CA"))
            let addr = placemarks.first.map(Self.postalAddress(from:))
            let usable = (addr?.houseNumber.isEmpty == false) ? addr : nil
            cache[key] = .some(usable)
            return usable
        } catch let error as CLError {
            switch error.code {
            case .network: throw AddressLookupError.offline
            case .geocodeFoundNoResult, .geocodeFoundPartialResult:
                cache[key] = .some(nil)
                return nil
            default:
                // CLGeocoder reports throttling as a network error with a specific
                // userInfo; treat other failures as throttling so we back off.
                throw AddressLookupError.throttled
            }
        }
    }

    static func postalAddress(from pm: CLPlacemark) -> PostalAddress {
        PostalAddress(houseNumber: pm.subThoroughfare ?? "",
                      street: pm.thoroughfare ?? "",
                      city: pm.locality ?? pm.subAdministrativeArea ?? "",
                      province: abbreviateProvince(pm.administrativeArea ?? ""),
                      postalCode: pm.postalCode ?? "")
    }

    static func abbreviateProvince(_ s: String) -> String {
        let map = ["Ontario": "ON", "Quebec": "QC", "Québec": "QC", "British Columbia": "BC", "Alberta": "AB",
                   "Manitoba": "MB", "Saskatchewan": "SK", "Nova Scotia": "NS", "New Brunswick": "NB",
                   "Newfoundland and Labrador": "NL", "Prince Edward Island": "PE"]
        return map[s] ?? s
    }
}

/// Address search for manual correction, biased toward where the rep is.
@MainActor
final class AddressSearch: NSObject, ObservableObject, MKLocalSearchCompleterDelegate {
    @Published var results: [MKLocalSearchCompletion] = []
    private let completer = MKLocalSearchCompleter()

    override init() {
        super.init()
        completer.delegate = self
        completer.resultTypes = .address
    }

    func update(query: String, near: CLLocationCoordinate2D?) {
        if let c = near {
            completer.region = MKCoordinateRegion(center: c, latitudinalMeters: 4000, longitudinalMeters: 4000)
        }
        completer.queryFragment = query
    }

    func resolve(_ completion: MKLocalSearchCompletion) async -> (PostalAddress, CLLocationCoordinate2D)? {
        let request = MKLocalSearch.Request(completion: completion)
        guard let response = try? await MKLocalSearch(request: request).start(),
              let item = response.mapItems.first else { return nil }
        let pm = item.placemark
        return (AddressResolver.postalAddress(from: pm), pm.coordinate)
    }

    nonisolated func completerDidUpdateResults(_ completer: MKLocalSearchCompleter) {
        let r = completer.results
        Task { @MainActor in self.results = r }
    }

    nonisolated func completer(_ completer: MKLocalSearchCompleter, didFailWithError error: Error) {}
}
