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
    @Published var budget: BudgetStatus? = nil

    private var timer: Timer?
    private var failureCount = 0
    private var isRestarting = false
    private var lastLinkType: String?
    private var budgetTick = 0
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
            // Budget moves slowly — poll /api/budget ~every 60s (every 12th 5s
            // tick), and once on the first refresh.
            budgetTick += 1
            if budgetTick % 12 == 1 { await refreshBudget() }
        } catch {
            self.failureCount += 1
            self.state = self.failureCount >= 2 ? .offline : .connecting
            self.menuBarTitle = self.state == .offline ? "⚠ offline" : "↓ … ↑ …"
            self.mbpsIn = 0
            self.mbpsOut = 0
            self.session = nil
            self.topApps = []
            if self.failureCount >= 2 { self.budget = nil }   // only clear when truly offline, not on a transient blip
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

    /// Fetch budget status from the backend if a budget is configured. Config
    /// lives in UserDefaults (app-owned); scope "net" caps the CURRENT network.
    private func refreshBudget() async {
        let d = UserDefaults.standard
        guard d.bool(forKey: BudgetDefaults.enabled) else { self.budget = nil; return }
        let cap = d.integer(forKey: BudgetDefaults.capBytes)
        guard cap > 0 else { self.budget = nil; return }
        let period = d.string(forKey: BudgetDefaults.period) ?? "month"
        let scope = d.string(forKey: BudgetDefaults.scope) ?? "all"

        var comps = URLComponents(string: "http://127.0.0.1:8765/api/budget")!
        var items = [
            URLQueryItem(name: "cap", value: String(cap)),
            URLQueryItem(name: "period", value: period),
            URLQueryItem(name: "scope", value: scope),
        ]
        if scope == "net" {                      // cap the network we're on now
            if let ssid = session?.ssid, !ssid.isEmpty {
                items.append(URLQueryItem(name: "ssid", value: ssid))
            } else if let lt = session?.linkType {
                items.append(URLQueryItem(name: "link_type", value: lt))
            } else {
                self.budget = nil; return        // no current network to scope to
            }
        }
        comps.queryItems = items
        guard let url = comps.url else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            guard let j = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let cb = (j["cap_bytes"] as? NSNumber)?.doubleValue,
                  let ub = (j["used_bytes"] as? NSNumber)?.doubleValue,
                  let pct = (j["pct"] as? NSNumber)?.doubleValue else { return }
            let status = BudgetStatus(usedBytes: ub, capBytes: cb, pct: pct,
                                      over: (j["over"] as? Bool) ?? (ub >= cb),
                                      period: (j["period"] as? String) ?? period)
            self.budget = status
            checkBudgetThresholds(status, period: period)
        } catch {
            // Leave the last value; a transient miss shouldn't blank the bar.
        }
    }

    /// Notify as usage crosses 80% then 100%. Dedup state is a single
    /// UserDefaults key per period ("<bucket>:<highest threshold already fired
    /// this bucket>"), so storage stays bounded (no unbounded key growth) while
    /// still firing 80 then 100 as usage climbs within one rolling window.
    private func checkBudgetThresholds(_ s: BudgetStatus, period: String) {
        let crossed = s.pct >= 100 ? 100 : (s.pct >= 80 ? 80 : 0)
        guard crossed > 0 else { return }
        let window = Double(["hour": 3600, "day": 86400, "week": 604800, "month": 2592000][period] ?? 2592000)
        let bucket = Int(Date().timeIntervalSince1970 / window)

        let d = UserDefaults.standard
        let key = "budget.notified.\(period)"
        // Stored as "<bucket>:<highest threshold already notified this bucket>".
        var lastBucket = -1, lastThreshold = 0
        if let parts = d.string(forKey: key)?.split(separator: ":"), parts.count == 2 {
            lastBucket = Int(parts[0]) ?? -1
            lastThreshold = Int(parts[1]) ?? 0
        }
        let alreadyFired = (bucket == lastBucket) ? lastThreshold : 0
        guard crossed > alreadyFired else { return }   // nothing new to announce

        d.set("\(bucket):\(crossed)", forKey: key)
        let content = UNMutableNotificationContent()
        content.title = crossed >= 100 ? "Data budget exceeded" : "Data budget 80% used"
        let usedGB = s.usedBytes / 1_073_741_824
        let capGB = s.capBytes / 1_073_741_824
        content.body = String(format: "You've used %.1f of %.1f GB this %@.", usedGB, capGB, period)
        let req = UNNotificationRequest(identifier: "\(key).\(bucket).\(crossed)", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
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
