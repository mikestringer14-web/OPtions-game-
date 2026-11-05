import SwiftUI
import SwiftData
import Charts
import SmartKnockCore

struct DashboardView: View {
    @Environment(\.modelContext) private var context
    @Query(sort: \Visit.createdAt) private var visits: [Visit]
    @Query(sort: \CanvassSession.start) private var sessions: [CanvassSession]
    @State private var shareURL: URL?

    private var records: [VisitRecord] { visits.map(\.record) }
    private var sessionRecords: [SessionRecord] { sessions.map(\.record) }

    private func stats(from start: Date, to end: Date) -> CanvassStats {
        StatsCalculator.stats(visits: records, sessions: sessionRecords, from: start, to: end)
    }

    var body: some View {
        let cal = Calendar.current
        let todayStart = cal.startOfDay(for: Date())
        let tomorrow = cal.date(byAdding: .day, value: 1, to: todayStart)!
        let weekStart = cal.dateInterval(of: .weekOfYear, for: Date())?.start ?? todayStart
        let today = stats(from: todayStart, to: tomorrow)
        let week = stats(from: weekStart, to: tomorrow)
        let allTime = stats(from: .distantPast, to: .distantFuture)
        let daily = StatsCalculator.daily(visits: records, days: 14, endingOn: Date())

        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Button {
                        shareURL = try? ExportService.makeFile(.text, visits: ExportService.visits(on: Date(), context: context),
                                                               day: Date(), context: context, markExported: false)
                    } label: {
                        Label("Daily Summary", systemImage: "square.and.arrow.up")
                            .font(.headline)
                            .frame(maxWidth: .infinity, minHeight: 50)
                    }
                    .buttonStyle(.borderedProminent)

                    sectionTitle("Today")
                    grid([
                        ("Doors", "\(today.doors)", Theme.accent, "door.left.hand.open"),
                        ("Bookings", "\(today.bookings)", Outcome.booking.color, Outcome.booking.symbol),
                        ("Booking %", percent(today.bookingRatePerDoor), Outcome.booking.color, "percent"),
                        ("Per contact", percent(today.bookingRatePerContact), Outcome.booking.color, "person.fill.checkmark"),
                        ("Walked", today.distanceMeters.kmString, Theme.accent, "figure.walk"),
                        ("Time", today.activeSeconds.durationString, Theme.accent, "timer"),
                        ("Doors / hr", String(format: "%.1f", today.doorsPerHour), Theme.accent, "speedometer"),
                        ("No answer", "\(today.count(.noAnswer))", Outcome.noAnswer.color, Outcome.noAnswer.symbol)
                    ])

                    sectionTitle("This week")
                    grid([
                        ("Doors", "\(week.doors)", Theme.accent, "door.left.hand.open"),
                        ("Bookings", "\(week.bookings)", Outcome.booking.color, Outcome.booking.symbol),
                        ("Booking %", percent(week.bookingRatePerDoor), Outcome.booking.color, "percent"),
                        ("Walked", week.distanceMeters.kmString, Theme.accent, "figure.walk")
                    ])

                    sectionTitle("Last 14 days")
                    Chart {
                        ForEach(daily) { d in
                            BarMark(x: .value("Day", d.day, unit: .day), y: .value("Count", d.doors))
                                .foregroundStyle(by: .value("Series", "Doors"))
                                .position(by: .value("Series", "Doors"))
                            BarMark(x: .value("Day", d.day, unit: .day), y: .value("Count", d.bookings))
                                .foregroundStyle(by: .value("Series", "Bookings"))
                                .position(by: .value("Series", "Bookings"))
                        }
                    }
                    .chartForegroundStyleScale(["Doors": Theme.accent, "Bookings": Outcome.booking.color])
                    .chartXAxis { AxisMarks(values: .stride(by: .day, count: 2)) { _ in AxisValueLabel(format: .dateTime.day().month(.abbreviated)) } }
                    .frame(height: 200)
                    .padding(12)
                    .background(RoundedRectangle(cornerRadius: 14).fill(Theme.surface))

                    sectionTitle("Outcomes this week")
                    Chart {
                        ForEach(Outcome.padOrder) { o in
                            BarMark(x: .value("Count", week.count(o)), y: .value("Outcome", o.title))
                                .foregroundStyle(o.color)
                                .annotation(position: .trailing) {
                                    Text("\(week.count(o))").font(.caption).foregroundStyle(Theme.textSecondary)
                                }
                        }
                    }
                    .frame(height: 280)
                    .padding(12)
                    .background(RoundedRectangle(cornerRadius: 14).fill(Theme.surface))

                    sectionTitle("All time")
                    grid([
                        ("Callbacks", "\(allTime.count(.callBack))", Outcome.callBack.color, Outcome.callBack.symbol),
                        ("Future", "\(allTime.count(.future))", Outcome.future.color, Outcome.future.symbol),
                        ("Referrals", "\(allTime.count(.referral))", Outcome.referral.color, Outcome.referral.symbol),
                        ("Prev. customers", "\(allTime.count(.previousCustomer))", Outcome.previousCustomer.color, Outcome.previousCustomer.symbol),
                        ("No soliciting", "\(allTime.count(.noSoliciting))", Outcome.noSoliciting.color, Outcome.noSoliciting.symbol),
                        ("Renters", "\(allTime.count(.renter))", Outcome.renter.color, Outcome.renter.symbol)
                    ])
                }
                .padding(14)
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Performance")
            .sheet(item: Binding(get: { shareURL.map(ShareableURL.init) }, set: { shareURL = $0?.url })) { item in
                ShareSheet(items: [item.url])
            }
        }
    }

    private func sectionTitle(_ s: String) -> some View {
        Text(s).font(.headline).foregroundStyle(Theme.textSecondary).padding(.top, 4)
    }

    private func grid(_ items: [(String, String, Color, String)]) -> some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
            ForEach(items.indices, id: \.self) { i in
                let item = items[i]
                StatTile(title: item.0, value: item.1, tint: item.2, symbol: item.3)
            }
        }
    }

    private func percent(_ v: Double) -> String { String(format: "%.1f%%", v * 100) }
}
