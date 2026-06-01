import SwiftUI
import AppKit
import ServiceManagement

struct LivePopover: View {
    @ObservedObject var monitor: NetworkMonitor
    let openDashboard: () -> Void
    let showAbout: () -> Void
    let showUninstall: () -> Void

    @State private var launchAtLogin = (SMAppService.mainApp.status == .enabled)

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            liveHeader
            statsRow
            if let s = monitor.session {
                networkChip(s)
            }
            if !monitor.topApps.isEmpty {
                Divider()
                topAppsSection
            }
            if monitor.state == .offline {
                Divider()
                menuRow(title: "Restart Services", systemImage: "arrow.clockwise", shortcut: nil) {
                    monitor.restartServices()
                }
            }
            Divider()
            menuRow(title: "Open Dashboard", systemImage: "safari", shortcut: "D", action: openDashboard)
            loginItemRow
            menuRow(title: "About AppBand", systemImage: "info.circle", shortcut: nil, action: showAbout)
            Divider()
            menuRow(title: "Uninstall AppBand…", systemImage: "trash", shortcut: nil, action: showUninstall)
            menuRow(title: "Quit Menu Bar", systemImage: "power", shortcut: "Q") {
                NSApplication.shared.terminate(nil)
            }
        }
        .padding(14)
        .frame(width: 300)
        .onAppear {
            // Re-sync in case the login item was changed in System Settings
            // while the popover was closed.
            launchAtLogin = (SMAppService.mainApp.status == .enabled)
        }
    }

    // ─── Subviews ───────────────────────────────────────────────────────────

    private var liveHeader: some View {
        HStack(spacing: 6) {
            PulseDot(color: stateColor)
            Text(stateLabel)
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(.secondary)
                .kerning(0.6)
            Spacer()
        }
    }

    private var stateColor: Color {
        switch monitor.state {
        case .online:     return .green
        case .connecting: return .yellow
        case .offline:    return .gray
        }
    }

    private var stateLabel: String {
        switch monitor.state {
        case .online:     return "LIVE"
        case .connecting: return "CONNECTING…"
        case .offline:    return "OFFLINE"
        }
    }

    private var statsRow: some View {
        HStack(alignment: .top, spacing: 18) {
            statColumn(label: "Download",
                       icon: "arrow.down",
                       value: monitor.mbpsIn,
                       tint: Color(red: 0.04, green: 0.52, blue: 1.0))
            Rectangle()
                .fill(Color.secondary.opacity(0.25))
                .frame(width: 1, height: 42)
            statColumn(label: "Upload",
                       icon: "arrow.up",
                       value: monitor.mbpsOut,
                       tint: Color(red: 1.0, green: 0.58, blue: 0.0))
            Spacer(minLength: 0)
        }
    }

    private func statColumn(label: String, icon: String, value: Double, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 3) {
                Image(systemName: icon)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(tint)
                Text(label)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(formattedValue(value))
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(tint)
                    .monospacedDigit()
                Text("Mbps")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .padding(.leading, 1)
            }
        }
    }

    private var topAppsSection: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("TOP APPS NOW")
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(.tertiary)
                .kerning(0.6)
            ForEach(monitor.topApps) { app in
                HStack(spacing: 12) {
                    Text(app.name)
                        .font(.system(size: 12))
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer(minLength: 0)
                    Text(formattedBytes(app.bytes))
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
            }
        }
    }

    private func networkChip(_ s: NetworkMonitor.Session) -> some View {
        HStack(spacing: 6) {
            Image(systemName: linkTypeIcon(s.linkType))
                .font(.system(size: 10, weight: .medium))
            Text(networkLabel(for: s))
                .font(.system(size: 11, weight: .medium))
            if let ip = s.ipAddress {
                Text("·")
                    .font(.system(size: 11))
                    .foregroundStyle(.tertiary)
                Text(ip)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }
        }
        .foregroundStyle(.secondary)
        .padding(.vertical, 4)
        .padding(.horizontal, 9)
        .background(Color.secondary.opacity(0.1))
        .clipShape(Capsule())
    }

    private var loginItemRow: some View {
        HoverButton(action: toggleLaunchAtLogin) {
            HStack(spacing: 9) {
                Image(systemName: "arrow.right.to.line.circle")
                    .font(.system(size: 11, weight: .medium))
                    .frame(width: 14)
                Text("Start at Login")
                    .font(.system(size: 13))
                Spacer(minLength: 12)
                Image(systemName: launchAtLogin ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 12))
                    .foregroundStyle(launchAtLogin ? Color.accentColor : Color.secondary)
            }
        }
    }

    private func toggleLaunchAtLogin() {
        do {
            if launchAtLogin {
                try SMAppService.mainApp.unregister()
            } else {
                try SMAppService.mainApp.register()
            }
            launchAtLogin.toggle()
        } catch {
            NSSound.beep()  // best-effort; leave the toggle as-is on failure
        }
    }

    private func menuRow(title: String, systemImage: String, shortcut: String?, action: @escaping () -> Void) -> some View {
        HoverButton(action: action) {
            HStack(spacing: 9) {
                Image(systemName: systemImage)
                    .font(.system(size: 11, weight: .medium))
                    .frame(width: 14)
                Text(title)
                    .font(.system(size: 13))
                Spacer(minLength: 12)
                if let sc = shortcut {
                    Text("⌘\(sc)")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.tertiary)
                        .monospacedDigit()
                }
            }
        }
    }

    // ─── Formatting / labels ────────────────────────────────────────────────

    private func formattedValue(_ v: Double) -> String {
        if v >= 100 { return String(format: "%.0f", v) }
        return String(format: "%.2f", v)
    }

    private func formattedBytes(_ n: Double) -> String {
        let units = ["B", "KB", "MB", "GB", "TB"]
        var v = n
        var i = 0
        while v >= 1024 && i < units.count - 1 { v /= 1024; i += 1 }
        return i >= 2 ? String(format: "%.1f %@", v, units[i]) : String(format: "%.0f %@", v, units[i])
    }

    private func linkTypeIcon(_ lt: String) -> String {
        switch lt {
        case "wifi":           return "wifi"
        case "ethernet":       return "cable.connector"
        case "iphone-hotspot": return "personalhotspot"
        case "usb-tether":     return "cable.connector.horizontal"
        default:               return "network"
        }
    }

    private func networkLabel(for s: NetworkMonitor.Session) -> String {
        if let ssid = s.ssid, !ssid.isEmpty { return ssid }
        switch s.linkType {
        case "wifi":           return "Wi-Fi"
        case "ethernet":       return "Ethernet"
        case "iphone-hotspot": return "iPhone Hotspot"
        case "usb-tether":     return "USB Tether"
        default:               return s.linkType
        }
    }
}

// MARK: - Pulsing dot

struct PulseDot: View {
    let color: Color
    @State private var scale: CGFloat = 1.0

    var body: some View {
        ZStack {
            Circle().fill(color.opacity(0.25))
                .frame(width: 14, height: 14)
                .scaleEffect(scale)
            Circle().fill(color)
                .frame(width: 7, height: 7)
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) {
                scale = 1.6
            }
        }
    }
}

// MARK: - Hover button row

struct HoverButton<Content: View>: View {
    let action: () -> Void
    @ViewBuilder let label: () -> Content
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            label()
                .contentShape(Rectangle())
                .padding(.vertical, 5)
                .padding(.horizontal, 8)
                .background(
                    RoundedRectangle(cornerRadius: 5)
                        .fill(hovering ? Color.accentColor.opacity(0.18) : Color.clear)
                )
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
    }
}
