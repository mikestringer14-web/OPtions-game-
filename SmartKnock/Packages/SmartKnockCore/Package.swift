// swift-tools-version: 5.9
import PackageDescription

// SmartKnockCore holds all platform-independent logic (stop detection,
// address ranking, lead summaries, exports, stats). It has no UIKit,
// CoreLocation or SwiftData dependency so it can be unit tested anywhere.
let package = Package(
    name: "SmartKnockCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "SmartKnockCore", targets: ["SmartKnockCore"])
    ],
    targets: [
        .target(name: "SmartKnockCore"),
        .testTarget(name: "SmartKnockCoreTests", dependencies: ["SmartKnockCore"])
    ]
)
