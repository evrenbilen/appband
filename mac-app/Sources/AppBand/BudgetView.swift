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
