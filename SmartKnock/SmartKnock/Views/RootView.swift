import SwiftUI
import SwiftData

struct RootView: View {
    @Environment(AppRouter.self) private var router
    @Environment(CanvassEngine.self) private var engine
    @AppStorage("onboarded") private var onboarded = false

    var body: some View {
        @Bindable var router = router
        TabView(selection: $router.tab) {
            CanvassView()
                .tabItem { Label("Canvass", systemImage: "figure.walk") }
                .tag(AppRouter.Tab.canvass)
            VisitMapView()
                .tabItem { Label("Map", systemImage: "map.fill") }
                .tag(AppRouter.Tab.map)
            HistoryView()
                .tabItem { Label("History", systemImage: "list.bullet.rectangle") }
                .tag(AppRouter.Tab.history)
            DashboardView()
                .tabItem { Label("Stats", systemImage: "chart.bar.fill") }
                .tag(AppRouter.Tab.dashboard)
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape.fill") }
                .tag(AppRouter.Tab.settings)
        }
        .background(Theme.background)
        .sheet(item: idBinding(\.loggerVisitID)) { item in
            LoggerSheet(visitID: item.id)
        }
        .sheet(item: idBinding(\.leadVisitID)) { item in
            LeadEntryView(visitID: item.id)
        }
        .sheet(item: idBinding(\.followUpVisitID)) { item in
            FollowUpSheet(visitID: item.id)
                .presentationDetents([.medium])
        }
        .sheet(item: idBinding(\.detailVisitID)) { item in
            NavigationStack { VisitDetailView(visitID: item.id) }
        }
        .fullScreenCover(isPresented: Binding(get: { !onboarded }, set: { onboarded = !$0 })) {
            OnboardingView { onboarded = true }
        }
    }

    /// Adapts an optional UUID on the router to `sheet(item:)`.
    private func idBinding(_ keyPath: ReferenceWritableKeyPath<AppRouter, UUID?>) -> Binding<IdentifiedUUID?> {
        Binding(
            get: { router[keyPath: keyPath].map(IdentifiedUUID.init) },
            set: { router[keyPath: keyPath] = $0?.id }
        )
    }
}

struct IdentifiedUUID: Identifiable, Hashable {
    let id: UUID
}
