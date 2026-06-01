import SwiftUI
import AppKit
import Combine

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
    private var cancellables = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 1. First-run installer (idempotent)
        do {
            try BackendInstaller.installIfNeeded()
        } catch {
            // Surface the failure instead of leaving the menu bar "offline"
            // forever with no cause shown.
            let detail: String
            if case let InstallerError.installFailed(out) = error, !out.isEmpty {
                detail = out
            } else {
                detail = String(describing: error)
            }
            let alert = NSAlert()
            alert.messageText = "AppBand backend failed to install"
            alert.informativeText = detail
            alert.alertStyle = .warning
            alert.runModal()
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
            showAbout:     { [weak self] in self?.showAbout() },
            showUninstall: { [weak self] in self?.showUninstall() }
        ))
        popover.contentViewController = host

        // 5. Update the menubar title only when it actually changes (the monitor
        //    recomputes it every 5s) — no need for a 1Hz polling timer.
        monitor.$menuBarTitle
            .receive(on: RunLoop.main)
            .sink { [weak self] title in self?.statusItem.button?.title = title }
            .store(in: &cancellables)
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

    fileprivate func showUninstall() {
        popover.performClose(nil)
        let alert = NSAlert()
        alert.messageText = "Uninstall AppBand?"
        alert.informativeText = "This stops and removes the background services. "
            + "Your collected database is kept unless you also choose to delete it."
        alert.addButton(withTitle: "Uninstall")
        alert.addButton(withTitle: "Cancel")
        alert.showsSuppressionButton = true
        alert.suppressionButton?.title = "Also delete collected data"
        alert.alertStyle = .warning
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }

        let purge = alert.suppressionButton?.state == .on
        let script = BackendInstaller.targetDir.appendingPathComponent("scripts/uninstall.sh")
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/bash")
        proc.arguments = purge ? [script.path, "--purge"] : [script.path]
        try? proc.run()
        proc.waitUntilExit()
        NSApplication.shared.terminate(nil)
    }
}
