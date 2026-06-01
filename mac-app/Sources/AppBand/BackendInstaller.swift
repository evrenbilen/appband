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
        let upToDate = installedVersion == bundledVersion

        // Re-copy when the bundled version changes, so updating AppBand.app
        // actually replaces the old backend (not just on first install).
        if plistInstalled && backendCopied && upToDate { return }

        // 1. Locate the backend bundled in the .app
        guard let resourceURL = Bundle.main.resourceURL else { throw InstallerError.resourcesMissing }
        let bundledBackend = resourceURL.appendingPathComponent("backend")
        guard fm.fileExists(atPath: bundledBackend.path) else { throw InstallerError.resourcesMissing }

        // 2. Copy backend tree → ~/Library/Application Support/AppBand/backend/
        try fm.createDirectory(at: targetDir.deletingLastPathComponent(), withIntermediateDirectories: true)
        if fm.fileExists(atPath: targetDir.path) {
            try fm.removeItem(at: targetDir)
        }
        try fm.copyItem(at: bundledBackend, to: targetDir)

        // 3. Run scripts/install.sh
        let installScript = targetDir.appendingPathComponent("scripts/install.sh")
        // Ensure executable
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

        // Record the installed version so the next launch only re-copies when
        // the bundled version changes.
        try? bundledVersion.write(to: versionMarker, atomically: true, encoding: .utf8)
    }
}
