import SwiftUI

/// UserDefaults keys shared between the config form (@AppStorage) and
/// NetworkMonitor (reads UserDefaults.standard). App-owned config — the
/// backend stores nothing.
enum BudgetDefaults {
    static let enabled = "budget.enabled"
    static let capBytes = "budget.capBytes"   // Int (bytes)
    static let period = "budget.period"       // "hour" | "day" | "week" | "month"
    static let scope = "budget.scope"         // "all" | "metered" | "net"
}

/// One evaluation of /api/budget, for the popover progress UI.
struct BudgetStatus {
    let usedBytes: Double
    let capBytes: Double
    let pct: Double          // 0…(can exceed 100)
    let over: Bool
    let period: String
}

/// The "DATA BUDGET" block in the popover: a progress bar when active, plus an
/// expandable config form (@AppStorage-backed → persists to UserDefaults).
struct BudgetSection: View {
    @ObservedObject var monitor: NetworkMonitor

    @AppStorage(BudgetDefaults.enabled) private var enabled = false
    @AppStorage(BudgetDefaults.capBytes) private var capBytes = 10_737_418_240   // 10 GB
    @AppStorage(BudgetDefaults.period) private var period = "month"
    @AppStorage(BudgetDefaults.scope) private var scope = "all"

    @State private var expanded = false
    @State private var capGBText = ""

    private let periods = ["hour", "day", "week", "month"]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("DATA BUDGET")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.tertiary)
                    .kerning(0.6)
                Spacer()
                Button(expanded ? "Done" : (enabled ? "Edit" : "Set…")) {
                    capGBText = String(format: "%g", Double(capBytes) / 1_073_741_824)
                    expanded.toggle()
                }
                .buttonStyle(.plain)
                .font(.system(size: 11))
                .foregroundStyle(Color.accentColor)
            }

            if enabled, let b = monitor.budget {
                progressBar(b)
            } else if enabled {
                Text("Waiting for usage…").font(.system(size: 11)).foregroundStyle(.secondary)
            }

            if expanded { configForm }
        }
    }

    private func progressBar(_ b: BudgetStatus) -> some View {
        let frac = min(b.pct / 100.0, 1.0)
        let tint: Color = b.over ? .red : (b.pct >= 80 ? .orange : .green)
        return VStack(alignment: .leading, spacing: 3) {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.secondary.opacity(0.2))
                    Capsule().fill(tint).frame(width: max(2, geo.size.width * frac))
                }
            }
            .frame(height: 6)
            Text(String(format: "%@ / %@ · %.0f%% · %@",
                        bytesLabel(b.usedBytes), bytesLabel(b.capBytes), b.pct, b.period))
                .font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
        }
    }

    private var configForm: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle("Enabled", isOn: $enabled).font(.system(size: 12))
            HStack {
                Text("Cap (GB)").font(.system(size: 12))
                Spacer()
                TextField("10", text: $capGBText)
                    .frame(width: 64).multilineTextAlignment(.trailing)
                    .textFieldStyle(.roundedBorder)
                    .onChange(of: capGBText) { new in   // single-param form (macOS 13 target)
                        if let gb = Double(new), gb > 0 { capBytes = Int(gb * 1_073_741_824) }
                    }
            }
            Picker("Period", selection: $period) {
                ForEach(periods, id: \.self) { Text($0.capitalized).tag($0) }
            }.font(.system(size: 12))
            Picker("Scope", selection: $scope) {
                Text("All networks").tag("all")
                Text("Metered only").tag("metered")
                Text("This network").tag("net")
            }.font(.system(size: 12))
        }
        .padding(.top, 4)
    }

    private func bytesLabel(_ n: Double) -> String {
        let units = ["B", "KB", "MB", "GB", "TB"]
        var v = n; var i = 0
        while v >= 1024 && i < units.count - 1 { v /= 1024; i += 1 }
        return i >= 2 ? String(format: "%.1f %@", v, units[i]) : String(format: "%.0f %@", v, units[i])
    }
}
