import Foundation

enum InstallerError: Error {
    case resourcesMissing
    case installFailed(String)
}

struct BackendInstaller {
    /// `~/Library/Application Support/AppBand/backend/`
    static var targetDir: URL {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        return appSupport.appendingPathComponent("AppBand").appendingPathComponent("backend")
    }

    /// `~/Library/LaunchAgents/dev.appband.collector.plist`
    static var collectorPlist: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library").appendingPathComponent("LaunchAgents")
            .appendingPathComponent("dev.appband.collector.plist")
    }

    /// `~/Library/Application Support/AppBand/.version` — records the backend
    /// version last copied out of the app bundle.
    static var versionMarker: URL {
        targetDir.deletingLastPathComponent().appendingPathComponent(".version")
    }

    /// This app bundle's version (CFBundleShortVersionString).
    static var bundledVersion: String {
        (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? ""
    }

    static func installIfNeeded() throws {
        let fm = FileManager.default
        let plistInstalled = fm.fileExists(atPath: collectorPlist.path)
        let backendCopied = fm.fileExists(atPath: targetDir.appendingPathComponent("appband/collector.py").path)
        let installedVersion = (try? String(contentsOf: versionMarker, encoding: .utf8))?
            .trimmingCharacters(in: .whitespacesAndNewlines)

        if plistInstalled && backendCopied {
            // Re-copy only when the bundled version changes, so an app update
            // replaces the old backend. An empty bundled version means an
            // un-built dev run — don't churn the existing install over it.
            if bundledVersion.isEmpty || installedVersion == bundledVersion { return }
        }

        // 1. Locate the backend bundled in the .app
        guard let resourceURL = Bundle.main.resourceURL else { throw InstallerError.resourcesMissing }
        let bundledBackend = resourceURL.appendingPathComponent("backend")
        guard fm.fileExists(atPath: bundledBackend.path) else { throw InstallerError.resourcesMissing }

        let appDir = targetDir.deletingLastPathComponent()
        try fm.createDirectory(at: appDir, withIntermediateDirectories: true)

        // 2. Stage the new backend alongside the old one. The live directory is
        //    only touched once a complete copy exists, so a failed/interrupted
        //    copy never leaves the running backend half-deleted.
        let staging = appDir.appendingPathComponent("backend.new")
        if fm.fileExists(atPath: staging.path) { try fm.removeItem(at: staging) }
        try fm.copyItem(at: bundledBackend, to: staging)

        // 3. Stop the agents BEFORE replacing their working directory. They have
        //    KeepAlive=true and may hold open handles in the old backend, so
        //    removing it underneath them would race. Best-effort (ignore
        //    "not loaded"); install.sh re-bootstraps them in step 5.
        if plistInstalled { bootoutAgents() }

        // 4. Swap: drop the old tree, move the fully-staged copy into place.
        if fm.fileExists(atPath: targetDir.path) { try fm.removeItem(at: targetDir) }
        try fm.moveItem(at: staging, to: targetDir)

        // 5. Make scripts executable + run install.sh (re-bootstraps the agents).
        let installScript = targetDir.appendingPathComponent("scripts/install.sh")
        try? fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: installScript.path)
        for binName in ["uninstall.sh", "status.sh", "vacuum.sh"] {
            let p = targetDir.appendingPathComponent("scripts/\(binName)").path
            try? fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: p)
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/bash")
        proc.arguments = [installScript.path]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe
        try proc.run()
        proc.waitUntilExit()

        if proc.terminationStatus != 0 {
            let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            throw InstallerError.installFailed(out)
        }

        // 6. Record the installed version. Best-effort: a missing marker only
        //    triggers another (now safe — staged + bootout) re-copy next launch.
        try? bundledVersion.write(to: versionMarker, atomically: true, encoding: .utf8)
    }

    /// Stop the background agents so their working directory can be replaced.
    private static func bootoutAgents() {
        let uid = getuid()
        for label in ["dev.appband.collector", "dev.appband.server"] {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            p.arguments = ["bootout", "gui/\(uid)/\(label)"]
            try? p.run()
            p.waitUntilExit()
        }
    }
}
