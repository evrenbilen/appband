import Foundation
import Combine

@MainActor
final class NetworkMonitor: ObservableObject {
    struct Session {
        let linkType: String
        let ssid: String?
        let ipAddress: String?
    }

    @Published var menuBarTitle: String = "↓ — ↑ —"
    @Published var mbpsIn: Double = 0
    @Published var mbpsOut: Double = 0
    @Published var session: Session? = nil
    @Published var isOnline: Bool = false

    private var timer: Timer?

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
            self.isOnline = true

            if let s = json["session"] as? [String: Any] {
                self.session = Session(
                    linkType:  (s["link_type"] as? String) ?? "—",
                    ssid:      s["ssid"] as? String,
                    ipAddress: s["ip_address"] as? String
                )
            } else {
                self.session = nil
            }
        } catch {
            self.menuBarTitle = "⚠ offline"
            self.mbpsIn = 0
            self.mbpsOut = 0
            self.isOnline = false
            self.session = nil
        }
    }
}
