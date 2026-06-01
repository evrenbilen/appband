// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "AppBand",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "AppBand",
            path: "Sources/AppBand",
            exclude: ["Info.plist"]
        )
    ]
)
