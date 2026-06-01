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

    static func installIfNeeded() throws {
        let fm = FileManager.default
        let plistInstalled = fm.fileExists(atPath: collectorPlist.path)
        let backendCopied = fm.fileExists(atPath: targetDir.appendingPathComponent("appband/collector.py").path)

        if plistInstalled && backendCopied { return }  // already installed

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
    }
}
