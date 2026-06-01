import Foundation
import Combine
import UserNotifications

@MainActor
final class NetworkMonitor: ObservableObject {
    struct Session {
        let linkType: String
        let ssid: String?
        let ipAddress: String?
    }

    struct TopApp: Identifiable {
        let id = UUID()
        let name: String
        let bytes: Double   // exact total (in + out) over the last 60s
    }

    // A single missed poll during startup/restart is "connecting", not the
    // alarming "offline" — only sustained failure (>= 2) means the backend is down.
    enum ConnState { case connecting, online, offline }

    @Published var menuBarTitle: String = "↓ — ↑ —"
    @Published var mbpsIn: Double = 0
    @Published var mbpsOut: Double = 0
    @Published var session: Session? = nil
    @Published var topApps: [TopApp] = []
    @Published var state: ConnState = .connecting

    private var timer: Timer?
    private var failureCount = 0
    private var isRestarting = false
    private var lastLinkType: String?
    private static let meteredTypes: Set<String> = ["iphone-hotspot", "usb-tether"]

    init() {
        Task { await refresh() }
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { await self?.refresh() }
        }
    }

    deinit { timer?.invalidate() }

    private func refresh() async {
        guard let url = URL(string: "http://127.0.0.1:8765/api/current") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

            let bIn  = (json["bytes_in_60s"]  as? NSNumber)?.doubleValue ?? 0
            let bOut = (json["bytes_out_60s"] as? NSNumber)?.doubleValue ?? 0
            let mIn  = bIn  * 8.0 / 60.0 / 1_000_000.0
            let mOut = bOut * 8.0 / 60.0 / 1_000_000.0

            self.mbpsIn = mIn
            self.mbpsOut = mOut
            self.menuBarTitle = String(format: "↓ %.1f ↑ %.1f", mIn, mOut)
            self.failureCount = 0
            self.state = .online

            if let s = json["session"] as? [String: Any] {
                self.session = Session(
                    linkType:  (s["link_type"] as? String) ?? "—",
                    ssid:      s["ssid"] as? String,
                    ipAddress: s["ip_address"] as? String
                )
            } else {
                self.session = nil
            }
            self.checkMeteredTransition(self.session?.linkType)

            // Exact per-app usage over the last 60s (no approximation).
            if let apps = json["top_apps"] as? [[String: Any]] {
                self.topApps = apps.compactMap { a in
                    guard let name = a["process_name"] as? String else { return nil }
                    let bi = (a["bytes_in"]  as? NSNumber)?.doubleValue ?? 0
                    let bo = (a["bytes_out"] as? NSNumber)?.doubleValue ?? 0
                    return TopApp(name: name, bytes: bi + bo)
                }
            } else {
                self.topApps = []
            }
        } catch {
            self.failureCount += 1
            self.state = self.failureCount >= 2 ? .offline : .connecting
            self.menuBarTitle = self.state == .offline ? "⚠ offline" : "↓ … ↑ …"
            self.mbpsIn = 0
            self.mbpsOut = 0
            self.session = nil
            self.topApps = []
        }
    }

    /// Restart the background LaunchAgents (recovery when the backend has died).
    /// kickstart -k re-runs an already-bootstrapped service.
    func restartServices() {
        guard !isRestarting else { return }   // ignore rapid double-clicks
        isRestarting = true
        let uid = getuid()
        for label in ["dev.appband.collector", "dev.appband.server"] {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            p.arguments = ["kickstart", "-k", "gui/\(uid)/\(label)"]
            try? p.run()
        }
        self.failureCount = 0
        self.state = .connecting
        // Give the agents ~2s to bootstrap before polling, so a normal restart
        // doesn't flicker CONNECTING -> OFFLINE before the backend is back up.
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            await refresh()
            isRestarting = false
        }
    }

    /// Notify once when the active network transitions INTO a metered link
    /// (iPhone hotspot / USB tether) from a non-metered one — the README's
    /// headline use case. No alert on launch or while staying on the link.
    private func checkMeteredTransition(_ newType: String?) {
        defer { lastLinkType = newType }
        guard let nt = newType, Self.meteredTypes.contains(nt),
              let lt = lastLinkType, !Self.meteredTypes.contains(lt) else { return }
        let content = UNMutableNotificationContent()
        content.title = "Metered network"
        content.body = nt == "iphone-hotspot"
            ? "You're on an iPhone hotspot — AppBand is tracking your data use."
            : "You're on a USB tether — AppBand is tracking your data use."
        let req = UNNotificationRequest(identifier: "appband.metered", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
    }
}
