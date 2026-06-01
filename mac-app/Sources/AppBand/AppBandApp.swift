import SwiftUI
import AppKit

@main
struct AppBandApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        // No windows — menubar-only app.
        Settings { EmptyView() }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var popover: NSPopover!
    private var monitor: NetworkMonitor!
    private var titleTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 1. First-run installer (idempotent)
        do {
            try BackendInstaller.installIfNeeded()
        } catch {
            // Surfaced via About sheet later; deliberately silent here
        }

        // 2. The shared network monitor
        monitor = NetworkMonitor()

        // 3. Status item — variable length so title can grow
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            let img = NSImage(
                systemSymbolName: "antenna.radiowaves.left.and.right",
                accessibilityDescription: "AppBand"
            )
            img?.isTemplate = true  // adapts to light/dark menubar tint
            button.image = img
            button.imagePosition = .imageLeft
            button.imageScaling = .scaleProportionallyDown
            button.title = monitor.menuBarTitle
            button.font = NSFont.menuBarFont(ofSize: 0)
            button.action = #selector(togglePopover(_:))
            button.target = self
            button.sendAction(on: [.leftMouseDown])
        }

        // 4. Popover with SwiftUI content
        popover = NSPopover()
        popover.contentSize = NSSize(width: 300, height: 240)
        popover.behavior = .transient   // closes on outside click
        popover.animates = true
        let host = NSHostingController(rootView: LivePopover(
            monitor: monitor,
            openDashboard: { [weak self] in self?.openDashboard() },
            showAbout:     { [weak self] in self?.showAbout() }
        ))
        popover.contentViewController = host

        // 5. Refresh menubar title once per second (cheap — just reads a published property)
        titleTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            Task { @MainActor in
                self.statusItem.button?.title = self.monitor.menuBarTitle
            }
        }
        RunLoop.main.add(titleTimer!, forMode: .common)
    }

    func applicationWillTerminate(_ notification: Notification) {
        titleTimer?.invalidate()
    }

    @objc private func togglePopover(_ sender: NSStatusBarButton) {
        if popover.isShown {
            popover.performClose(sender)
        } else {
            NSApp.activate(ignoringOtherApps: true)
            popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    fileprivate func openDashboard() {
        if let url = URL(string: "http://127.0.0.1:8765/") {
            NSWorkspace.shared.open(url)
        }
        popover.performClose(nil)
    }

    fileprivate func showAbout() {
        popover.performClose(nil)
        let alert = NSAlert()
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
        alert.messageText = "AppBand \(version)"
        alert.informativeText = """
        Per-App Bandwidth & Network Monitor for macOS.

        The menu bar app is a small native wrapper around two background services:
          • dev.appband.collector
          • dev.appband.server

        Quitting the menu bar app does NOT stop the background services.
        To uninstall completely:

          ~/Library/Application Support/AppBand/backend/scripts/uninstall.sh

        github.com/evrenbilen/appband
        """
        alert.alertStyle = .informational
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }
}
