import SwiftUI
import AppKit
import Combine
import UserNotifications

@main
struct AppBandApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        // No windows — menubar-only app.
        Settings { EmptyView() }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
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

        // 2. The shared network monitor (+ ask once for notification permission,
        //    used for the metered-network alert). The delegate is required so a
        //    menu-bar (LSUIElement) app shows banners while running, not silent
        //    queueing to Notification Center.
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
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

    // Show metered-network alerts as banners even though the menu-bar app is
    // never the foreground "active" app.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
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
        // Run off the main thread so the UI doesn't freeze while uninstall.sh
        // boots out the agents; quit on the main thread once it completes.
        DispatchQueue.global().async {
            var launched = true
            do {
                try proc.run()
                proc.waitUntilExit()
            } catch {
                launched = false
            }
            let ok = launched && proc.terminationStatus == 0
            DispatchQueue.main.async {
                guard ok else {
                    // Uninstall did NOT complete — the background services (KeepAlive)
                    // are likely still running. Quitting now would look "uninstalled"
                    // while collection silently continues, so surface it and stay open.
                    let alert = NSAlert()
                    alert.messageText = "Uninstall didn't complete"
                    alert.informativeText = (launched
                        ? "The uninstall script exited with status \(proc.terminationStatus). "
                        : "Couldn't launch the uninstall script. ")
                        + "The background services may still be running — finish manually:\n\n  "
                        + script.path
                    alert.alertStyle = .warning
                    NSApp.activate(ignoringOtherApps: true)
                    alert.runModal()
                    return
                }
                NSApplication.shared.terminate(nil)
            }
        }
    }
}
