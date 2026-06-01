import Foundation
import Combine

@MainActor
final class NetworkMonitor: ObservableObject {
    struct Session {
        let linkType: String
        let ssid: String?
    }

    @Published var menuBarTitle: String = "↓ — ↑ —"
    @Published var session: Session? = nil

    private var timer: Timer?

    init() {
        // First tick immediately, then every 5s.
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
            let mbpsIn  = bIn  * 8.0 / 60.0 / 1_000_000.0
            let mbpsOut = bOut * 8.0 / 60.0 / 1_000_000.0

            self.menuBarTitle = String(format: "↓ %.1f  ↑ %.1f", mbpsIn, mbpsOut)

            if let s = json["session"] as? [String: Any] {
                let lt   = (s["link_type"] as? String) ?? "—"
                let ssid = s["ssid"] as? String
                self.session = Session(linkType: lt, ssid: ssid)
            } else {
                self.session = nil
            }
        } catch {
            self.menuBarTitle = "⚠ offline"
            self.session = nil
        }
    }
}
