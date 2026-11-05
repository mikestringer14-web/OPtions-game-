import SwiftUI
import MapKit
import SmartKnockCore

/// Correct a visit's address by: picking a suggestion, nudging the house
/// number, searching, or tapping the house on a map.
struct AddressPickerView: View {
    @Bindable var visit: Visit
    @Environment(CanvassEngine.self) private var engine
    @Environment(\.dismiss) private var dismiss
    @StateObject private var search = AddressSearch()
    @State private var query = ""
    @State private var number = ""
    @State private var street = ""
    @State private var unit = ""
    @State private var mode = Mode.suggestions

    enum Mode: String, CaseIterable, Identifiable {
        case suggestions = "Suggestions", edit = "Edit", search = "Search", map = "Map"
        var id: String { rawValue }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                Picker("Mode", selection: $mode) {
                    ForEach(Mode.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)

                switch mode {
                case .suggestions: suggestions
                case .edit: editor
                case .search: searchView
                case .map: MapAddressPicker(visit: visit) { addr, coord in
                    engine.setAddress(addr, for: visit, coordinate: coord)
                    dismiss()
                }
                }
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Which house?")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .onAppear {
                number = visit.houseNumber
                street = visit.street
                unit = visit.unit
                if visit.candidates.isEmpty { mode = .edit }
            }
        }
    }

    private var suggestions: some View {
        List {
            Section {
                HStack {
                    Text("GPS accuracy")
                    Spacer()
                    Text(visit.gpsAccuracy > 0 ? String(format: "±%.0f m", visit.gpsAccuracy) : "Unknown")
                        .foregroundStyle(Theme.textSecondary)
                }
                HStack {
                    Text("Current")
                    Spacer()
                    ConfidenceBadge(confidence: visit.confidence)
                }
            } footer: {
                Text("GPS on a phone is usually accurate to 5 to 15 m, about one lot width. Suggestions marked \"estimated\" are neighbouring numbers, not lookups.")
            }
            Section("Suggested addresses") {
                if visit.candidates.isEmpty {
                    Text(engine.isOnline ? "No suggestions yet." : "Offline. Addresses will be looked up when you have signal.")
                        .foregroundStyle(Theme.textSecondary)
                }
                ForEach(visit.candidates) { c in
                    Button {
                        engine.setAddress(c.address, for: visit)
                        dismiss()
                    } label: {
                        HStack {
                            VStack(alignment: .leading) {
                                Text(c.address.line1).font(.headline).foregroundStyle(.white)
                                Text(sourceLabel(c)).font(.caption).foregroundStyle(Theme.textSecondary)
                            }
                            Spacer()
                            if c.address.matchKey == visit.address.matchKey {
                                Image(systemName: "checkmark").foregroundStyle(Theme.accent)
                            }
                        }
                    }
                }
            }
            if let n = visit.address.numericHouseNumber {
                Section("Quick adjust") {
                    HStack(spacing: 12) {
                        ForEach([-4, -2, 2, 4], id: \.self) { delta in
                            Button(delta < 0 ? "\(n + delta)" : "\(n + delta)") {
                                engine.setAddress(visit.address.withHouseNumber(String(n + delta)), for: visit)
                                dismiss()
                            }
                            .buttonStyle(.bordered)
                            .disabled(n + delta <= 0)
                        }
                    }
                }
            }
        }
        .scrollContentBackground(.hidden)
    }

    private func sourceLabel(_ c: AddressCandidate) -> String {
        switch c.source {
        case .center: return "Lookup at your stop (\(c.hits) match\(c.hits == 1 ? "" : "es"))"
        case .alongStreet: return "Next door along the street"
        case .nearby: return "Nearby lookup"
        case .estimatedNeighbor: return "Estimated neighbouring number"
        case .manual: return "Entered by you"
        }
    }

    private var editor: some View {
        Form {
            Section("Address") {
                TextField("House number", text: $number).keyboardType(.numbersAndPunctuation)
                TextField("Street", text: $street).textInputAutocapitalization(.words)
                TextField("Unit (optional)", text: $unit)
            }
            Section {
                Button("Save address") {
                    var a = visit.address
                    a.houseNumber = number.trimmingCharacters(in: .whitespaces)
                    a.street = street.trimmingCharacters(in: .whitespaces)
                    a.unit = unit.trimmingCharacters(in: .whitespaces)
                    engine.setAddress(a, for: visit)
                    dismiss()
                }
                .disabled(number.isEmpty || street.isEmpty)
            }
        }
        .scrollContentBackground(.hidden)
    }

    private var searchView: some View {
        List {
            TextField("Search address", text: $query)
                .textInputAutocapitalization(.words)
                .onChange(of: query) { _, q in
                    search.update(query: q, near: CLLocationCoordinate2D(latitude: visit.latitude, longitude: visit.longitude))
                }
            ForEach(search.results, id: \.self) { r in
                Button {
                    Task {
                        if let found = await search.resolve(r) {
                            engine.setAddress(found.0, for: visit, coordinate: found.1)
                            dismiss()
                        }
                    }
                } label: {
                    VStack(alignment: .leading) {
                        Text(r.title).foregroundStyle(.white)
                        Text(r.subtitle).font(.caption).foregroundStyle(Theme.textSecondary)
                    }
                }
            }
        }
        .scrollContentBackground(.hidden)
    }
}

/// Tap the house on the map to look up its address.
struct MapAddressPicker: View {
    let visit: Visit
    var onPick: (PostalAddress, CLLocationCoordinate2D) -> Void
    @Environment(CanvassEngine.self) private var engine
    @State private var position: MapCameraPosition
    @State private var picked: CLLocationCoordinate2D?
    @State private var pickedAddress: PostalAddress?
    @State private var looking = false

    init(visit: Visit, onPick: @escaping (PostalAddress, CLLocationCoordinate2D) -> Void) {
        self.visit = visit
        self.onPick = onPick
        let c = CLLocationCoordinate2D(latitude: visit.latitude, longitude: visit.longitude)
        _position = State(initialValue: .camera(MapCamera(centerCoordinate: c, distance: 180)))
    }

    var body: some View {
        VStack(spacing: 0) {
            MapReader { proxy in
                Map(position: $position) {
                    Annotation("Stop", coordinate: CLLocationCoordinate2D(latitude: visit.latitude, longitude: visit.longitude)) {
                        Circle().fill(Theme.accent.opacity(0.3)).frame(width: 40, height: 40)
                            .overlay(Circle().fill(Theme.accent).frame(width: 10, height: 10))
                    }
                    if let p = picked {
                        Marker("Selected", coordinate: p).tint(Theme.success)
                    }
                    UserAnnotation()
                }
                .mapStyle(.hybrid(elevation: .flat, pointsOfInterest: .excludingAll))
                .onTapGesture { point in
                    guard let coord = proxy.convert(point, from: .local) else { return }
                    picked = coord
                    pickedAddress = nil
                    looking = true
                    Task {
                        pickedAddress = try? await engine.resolver.address(at: GeoPoint(latitude: coord.latitude, longitude: coord.longitude))
                        looking = false
                    }
                }
            }
            VStack(spacing: 8) {
                if looking {
                    ProgressView("Looking up…")
                } else if let a = pickedAddress, let c = picked {
                    Text(a.line1).font(.headline)
                    Button("Use this house") { onPick(a, c) }
                        .buttonStyle(.borderedProminent)
                        .frame(maxWidth: .infinity)
                } else {
                    Text(picked == nil ? "Tap the roof of the house you visited." : "No address found there. Try the centre of the roof.")
                        .font(.subheadline).foregroundStyle(Theme.textSecondary)
                }
            }
            .padding()
            .frame(maxWidth: .infinity)
            .background(Theme.surface)
        }
    }
}
