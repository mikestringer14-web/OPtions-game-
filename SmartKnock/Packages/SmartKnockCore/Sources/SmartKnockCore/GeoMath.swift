import Foundation

/// Minimal coordinate type so the core does not depend on CoreLocation.
public struct GeoPoint: Codable, Hashable, Sendable {
    public var latitude: Double
    public var longitude: Double

    public init(latitude: Double, longitude: Double) {
        self.latitude = latitude
        self.longitude = longitude
    }
}

public enum GeoMath {
    static let earthRadius = 6_371_000.0

    /// Great-circle distance in metres.
    public static func distance(_ a: GeoPoint, _ b: GeoPoint) -> Double {
        let lat1 = a.latitude * .pi / 180, lat2 = b.latitude * .pi / 180
        let dLat = lat2 - lat1
        let dLon = (b.longitude - a.longitude) * .pi / 180
        let h = sin(dLat / 2) * sin(dLat / 2) + cos(lat1) * cos(lat2) * sin(dLon / 2) * sin(dLon / 2)
        return 2 * earthRadius * asin(min(1, sqrt(h)))
    }

    /// Initial bearing from a to b in degrees (0 = north, clockwise).
    public static func bearing(from a: GeoPoint, to b: GeoPoint) -> Double {
        let lat1 = a.latitude * .pi / 180, lat2 = b.latitude * .pi / 180
        let dLon = (b.longitude - a.longitude) * .pi / 180
        let y = sin(dLon) * cos(lat2)
        let x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dLon)
        let deg = atan2(y, x) * 180 / .pi
        return (deg + 360).truncatingRemainder(dividingBy: 360)
    }

    /// Point reached by travelling `meters` along `bearing` degrees from `origin`.
    public static func offset(_ origin: GeoPoint, meters: Double, bearing: Double) -> GeoPoint {
        let delta = meters / earthRadius
        let theta = bearing * .pi / 180
        let lat1 = origin.latitude * .pi / 180
        let lon1 = origin.longitude * .pi / 180
        let lat2 = asin(sin(lat1) * cos(delta) + cos(lat1) * sin(delta) * cos(theta))
        let lon2 = lon1 + atan2(sin(theta) * sin(delta) * cos(lat1), cos(delta) - sin(lat1) * sin(lat2))
        return GeoPoint(latitude: lat2 * 180 / .pi, longitude: lon2 * 180 / .pi)
    }

    /// Accuracy-weighted centroid (weight = 1/accuracy^2). Falls back to a plain mean.
    public static func weightedCentroid(_ points: [(GeoPoint, Double)]) -> GeoPoint? {
        guard !points.isEmpty else { return nil }
        var wSum = 0.0, lat = 0.0, lon = 0.0
        for (p, acc) in points {
            let w = 1.0 / max(acc * acc, 1)
            wSum += w
            lat += p.latitude * w
            lon += p.longitude * w
        }
        return GeoPoint(latitude: lat / wSum, longitude: lon / wSum)
    }

    /// Total path length of an ordered list of points, in metres.
    public static func pathLength(_ points: [GeoPoint]) -> Double {
        guard points.count > 1 else { return 0 }
        var total = 0.0
        for i in 1..<points.count { total += distance(points[i - 1], points[i]) }
        return total
    }
}
