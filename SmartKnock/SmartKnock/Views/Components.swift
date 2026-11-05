import SwiftUI
import SmartKnockCore

/// The nine outcome buttons. No Answer spans the full width and is tallest
/// because it is used most. Sized for a thumb while walking.
struct OutcomePad: View {
    var highlighted: Outcome?
    var onSelect: (Outcome) -> Void

    private let columns = [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]

    var body: some View {
        VStack(spacing: 10) {
            OutcomeButton(outcome: .noAnswer, isHighlighted: highlighted == .noAnswer, height: 84, onTap: onSelect)
            LazyVGrid(columns: columns, spacing: 10) {
                ForEach(Outcome.padOrder.filter { $0 != .noAnswer }) { o in
                    OutcomeButton(outcome: o, isHighlighted: highlighted == o, height: 64, onTap: onSelect)
                }
            }
        }
    }
}

struct OutcomeButton: View {
    let outcome: Outcome
    var isHighlighted = false
    var height: CGFloat = 64
    let onTap: (Outcome) -> Void

    var body: some View {
        Button {
            onTap(outcome)
        } label: {
            HStack(spacing: 10) {
                Image(systemName: outcome.symbol)
                    .font(.system(size: height > 70 ? 26 : 20, weight: .bold))
                Text(outcome.title.uppercased())
                    .font(.system(size: height > 70 ? 22 : 16, weight: .heavy))
                    .minimumScaleFactor(0.7)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 14)
            .frame(maxWidth: .infinity, minHeight: height)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(outcome.color.opacity(isHighlighted ? 1 : 0.85))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(.white.opacity(isHighlighted ? 0.9 : 0), lineWidth: 3)
            )
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel(outcome.title)
        .accessibilityHint(outcome.detail)
    }
}

struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .brightness(configuration.isPressed ? -0.08 : 0)
    }
}

struct ConfidenceBadge: View {
    let confidence: AddressConfidence
    var compact = false

    var body: some View {
        Label(compact ? "" : confidence.title, systemImage: confidence.symbol)
            .labelStyle(.titleAndIcon)
            .font(.caption.weight(.semibold))
            .foregroundStyle(confidence.color)
            .padding(.horizontal, compact ? 6 : 8)
            .padding(.vertical, 4)
            .background(Capsule().fill(confidence.color.opacity(0.15)))
    }
}

struct OutcomeChip: View {
    let outcome: Outcome?

    var body: some View {
        Text(outcome?.title ?? "Not logged")
            .font(.caption.weight(.bold))
            .foregroundStyle(.white)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Capsule().fill(outcome?.color ?? Theme.surfaceRaised))
    }
}

struct StatTile: View {
    let title: String
    let value: String
    var tint: Color = Theme.accent
    var symbol: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                if let symbol { Image(systemName: symbol).foregroundStyle(tint) }
                Text(title).font(.caption).foregroundStyle(Theme.textSecondary)
            }
            Text(value)
                .font(.system(size: 26, weight: .bold, design: .rounded))
                .foregroundStyle(Theme.textPrimary)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 14).fill(Theme.surface))
    }
}

struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 10) { content }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 16).fill(Theme.surface))
    }
}

/// GPS accuracy pill, honest about when houses cannot be told apart.
struct GPSIndicator: View {
    let accuracy: Double?

    var body: some View {
        let (label, color): (String, Color) = {
            guard let a = accuracy, a >= 0 else { return ("No GPS", Theme.textSecondary) }
            if a <= 8 { return (String(format: "GPS ±%.0fm", a), Theme.success) }
            if a <= 15 { return (String(format: "GPS ±%.0fm", a), Theme.warning) }
            return (String(format: "GPS ±%.0fm weak", a), Theme.danger)
        }()
        Label(label, systemImage: "location.fill")
            .font(.caption.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Capsule().fill(color.opacity(0.15)))
    }
}

extension Double {
    var kmString: String { String(format: "%.2f km", self / 1000) }
    var durationString: String {
        let mins = Int(self / 60)
        return "\(mins / 60)h \(String(format: "%02d", mins % 60))m"
    }
}
