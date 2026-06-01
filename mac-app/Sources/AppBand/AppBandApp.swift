import SwiftUI

@main
struct AppBandApp: App {
    @StateObject private var monitor = NetworkMonitor()
    @State private var installError: String? = nil

    init() {
        // First-run install (idempotent)
        do {
            try BackendInstaller.installIfNeeded()
        } catch {
            // Defer surfacing — render in About sheet
        }
    }

    var body: some Scene {
        MenuBarExtra {
            VStack(alignment: .leading, spacing: 4) {
                Text("AppBand").font(.headline)
                if let session = monitor.session {
                    Text("\(session.linkType) · \(session.ssid ?? "—")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Divider()
                Button("Open Dashboard") { openDashboard() }
                Button("About AppBand") { showAbout() }
                Divider()
                Button("Quit AppBand Menu Bar") {
                    NSApplication.shared.terminate(nil)
                }
            }
            .padding(8)
            .frame(minWidth: 220)
        } label: {
            Label {
                Text(monitor.menuBarTitle)
                    .monospacedDigit()
            } icon: {
                Image(systemName: "antenna.radiowaves.left.and.right")
            }
        }
    }

    private func openDashboard() {
        if let url = URL(string: "http://127.0.0.1:8765/") {
            NSWorkspace.shared.open(url)
        }
    }

    private func showAbout() {
        let alert = NSAlert()
        alert.messageText = "AppBand"
        alert.informativeText = """
        Per-App Bandwidth & Network Monitor for macOS

        The menu bar app is a small native wrapper. The data collection and dashboard
        run as background LaunchAgents:

          • dev.appband.collector
          • dev.appband.server

        Quitting the menu bar app does NOT stop the background services.
        To uninstall completely, open Terminal and run:

          ~/Library/Application\\ Support/AppBand/backend/scripts/uninstall.sh

        github.com/evrenbilen/appband
        """
        alert.alertStyle = .informational
        alert.runModal()
    }
}
