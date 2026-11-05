import SwiftUI
import SwiftData
import MapKit
import SmartKnockCore

/// All logged doors on a map, colour-coded by outcome, with filters.
struct VisitMapView: View {
    @Query(sort: \Visit.createdAt, order: .reverse) private var visits: [Visit]
    @Environment(AppRouter.self) private var router
    @State private var position: MapCameraPosition = .userLocation(fallback: .region(
        MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: 43.3255, longitude: -79.7990), // Burlington
                           latitudinalMeters: 6000, longitudinalMeters: 6000)))
    @State private var enabled: Set<Outcome> = Set(Outcome.allCases)
    @State private var range = Range.today
    @State private var showUnlogged = true

    enum Range: String, CaseIterable, Identifiable {
        case today = "Today", week = "7 days", month = "30 days", all = "All"
        var id: String { rawValue }
        var start: Date? {
            let cal = Calendar.current
            switch self {
            case .today: return cal.startOfDay(for: Date())
            case .week: return cal.date(byAdding: .day, value: -7, to: Date())
            case .month: return cal.date(byAdding: .day, value: -30, to: Date())
            case .all: return nil
            }
        }
    }

    private var shown: [Visit] {
        let start = range.start
        return visits.filter { v in
            guard v.latitude != 0 || v.longitude != 0 else { return false }
            if let s = start, v.createdAt < s { return false }
            if let o = v.outcome { return enabled.contains(o) }
            return showUnlogged
        }
    }

    var body: some View {
        NavigationStack {
            Map(position: $position) {
                UserAnnotation()
                ForEach(shown) { v in
                    Annotation(v.displayAddress, coordinate: CLLocationCoordinate2D(latitude: v.latitude, longitude: v.longitude),
                               anchor: .center) {
                        Button { router.detailVisitID = v.id } label: {
                            ZStack {
                                Circle().fill(v.outcome?.color ?? Theme.textSecondary).frame(width: 26, height: 26)
                                Image(systemName: v.outcome?.symbol ?? "questionmark")
                                    .font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
                            }
                            .overlay(Circle().strokeBorder(.white, lineWidth: 1.5))
                        }
                    }
                    .annotationTitles(.hidden)
                }
            }
            .mapStyle(.standard(pointsOfInterest: .excludingAll))
            .mapControls {
                MapUserLocationButton()
                MapCompass()
                MapScaleView()
            }
            .safeAreaInset(edge: .top) { filters }
            .navigationTitle("Map")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private var filters: some View {
        VStack(spacing: 8) {
            Picker("Range", selection: $range) {
                ForEach(Range.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(Outcome.padOrder) { o in
                        let on = enabled.contains(o)
                        Button {
                            if on { enabled.remove(o) } else { enabled.insert(o) }
                        } label: {
                            Label(o.title, systemImage: o.symbol)
                                .font(.caption.bold())
                                .padding(.horizontal, 10).padding(.vertical, 6)
                                .foregroundStyle(.white)
                                .background(Capsule().fill(on ? o.color : Theme.surfaceRaised))
                        }
                        .buttonStyle(.plain)
                    }
                    Button { showUnlogged.toggle() } label: {
                        Text("Not logged").font(.caption.bold())
                            .padding(.horizontal, 10).padding(.vertical, 6)
                            .background(Capsule().fill(showUnlogged ? Theme.textSecondary : Theme.surfaceRaised))
                    }
                    .buttonStyle(.plain)
                }
            }
            Text("\(shown.count) doors shown").font(.caption).foregroundStyle(Theme.textSecondary)
        }
        .padding(10)
        .background(.ultraThinMaterial)
    }
}
