import SwiftUI
import SmartKnockCore

enum Theme {
    static let background = Color(hex: "#111317")
    static let surface = Color(hex: "#1B1E25")
    static let surfaceRaised = Color(hex: "#252A33")
    static let stroke = Color.white.opacity(0.08)
    static let accent = Color(hex: "#2E9BFF")      // electric blue
    static let accentDim = Color(hex: "#2E9BFF").opacity(0.18)
    static let textPrimary = Color.white
    static let textSecondary = Color(hex: "#A3AAB8")
    static let warning = Color(hex: "#F5B83D")
    static let danger = Color(hex: "#EF4444")
    static let success = Color(hex: "#22C55E")
}

extension Color {
    init(hex: String) {
        let cleaned = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        var value: UInt64 = 0
        Scanner(string: cleaned).scanHexInt64(&value)
        let r = Double((value >> 16) & 0xFF) / 255
        let g = Double((value >> 8) & 0xFF) / 255
        let b = Double(value & 0xFF) / 255
        self.init(.sRGB, red: r, green: g, blue: b, opacity: 1)
    }
}

extension Outcome {
    var color: Color { Color(hex: hexColor) }
}

extension AddressConfidence {
    var color: Color {
        switch self {
        case .unresolved: return Theme.textSecondary
        case .low: return Theme.danger
        case .medium: return Theme.warning
        case .high: return Theme.success
        case .confirmed: return Theme.accent
        }
    }

    var symbol: String {
        switch self {
        case .unresolved: return "questionmark.circle"
        case .low: return "exclamationmark.triangle.fill"
        case .medium: return "circle.lefthalf.filled"
        case .high: return "checkmark.circle.fill"
        case .confirmed: return "checkmark.seal.fill"
        }
    }
}
