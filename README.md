# AppBand

**[Download AppBand 0.1.1 (DMG)](https://github.com/evrenbilen/appband/releases/latest)**  ·  macOS 13+  ·  ~500 KB

**Per-App Bandwidth & Network Monitor for macOS**

AppBand is a local, privacy-respecting network usage monitor for macOS. It tracks which app on your machine talked to which destination, over which network, for how many bytes — and shows it on a local web dashboard.

- Zero external dependencies (Python 3 stdlib only — no `pip install`)
- Runs as a user-level LaunchAgent in the background
- All data stays on your Mac in a local SQLite database
- Dashboard at `http://127.0.0.1:8765/` (localhost only)

## What it tracks

- Active network: interface, link type (wifi / iphone-hotspot / usb-tether / ethernet), SSID
- Total bytes per 5 seconds (per network route)
- Bytes per process per 10 seconds (via `nettop`, loopback excluded)
- Active outbound connections per 30 seconds with reverse-DNS caching
- Internet vs LAN traffic distinction
- 30 days of history, auto-purged

## Install

### Download the DMG (easiest)

1. Download **AppBand-0.1.1.dmg** from the [latest release](https://github.com/evrenbilen/appband/releases/latest).
2. Open the DMG and drag **AppBand.app** to **Applications**.
3. **First launch — Gatekeeper bypass.** AppBand is ad-hoc signed but not notarized (that requires a paid Apple Developer Program membership). On macOS 15+ Sequoia, double-clicking the first time shows *"Apple could not verify AppBand is free of malware"* with only **Move to Trash** / **Done** buttons. Use one of these to unblock it:

   - **Terminal one-liner** (recommended — fastest):
     ```bash
     xattr -dr com.apple.quarantine /Applications/AppBand.app
     ```
     Now double-click `AppBand.app` — it opens normally.

   - **System Settings** (no Terminal):
     1. Try to open AppBand (it gets blocked).
     2. Open **System Settings → Privacy & Security**.
     3. Scroll down — you'll see *"AppBand was blocked..."*. Click **Open Anyway**.

4. On launch, AppBand installs the background services into `~/Library/Application Support/AppBand/` and opens the dashboard at http://127.0.0.1:8765/. A small ↓/↑ Mbps indicator appears in your menu bar.

### Install from source

```bash
git clone https://github.com/evrenbilen/appband ~/Development/appband
cd ~/Development/appband
./scripts/install.sh
```

## Status & uninstall

```bash
./scripts/status.sh             # show services + DB stats + recent log
./scripts/uninstall.sh          # stop services, keep DB
./scripts/uninstall.sh --purge  # stop services and delete DB
./scripts/vacuum.sh             # compact DB
```

## Storage

- DB:   `~/Library/Application Support/appband/appband.db` (SQLite WAL)
- Logs: `~/Library/Logs/appband/{collector,server}.log`

## Tests

```bash
python3 -m unittest discover tests -v
```

## Architecture

Two LaunchAgent processes share one SQLite database:

- **Collector** (`appband.collector`): polls `nettop`, `lsof`, `route`, `ipconfig` on cadences of 2/5/10/30 seconds. Writes interface samples, per-process samples, active connections, sessions.
- **Server** (`appband.server`): localhost-only HTTP server, JSON API + static dashboard. Reads from the DB.

DB schema: `sessions`, `interface_samples`, `process_samples`, `connections`, `dns_cache`.

## Caveats

- Domain-level numbers are **approximate**. `lsof` reports active connections, not bytes-per-connection. Per-process bytes are distributed across the hostnames the process talked to in the same 5-minute window. Treat the domain panel as "where the traffic probably went", not exact accounting.
- No packet capture (no `tcpdump`). VPN tunnels appear as a single endpoint.
- macOS sleep/wake can produce sample gaps; counters are reset on discontinuity to avoid spikes.
- iPhone Personal Hotspot: AppBand uses `nettop -m route` to bypass a kernel counter bug that can stall per-interface byte counters on tethered connections.

## Privacy

AppBand binds to `127.0.0.1` only — it cannot be reached from your network. All data stays on disk in `~/Library/Application Support/appband/`. Nothing is uploaded.

## License

MIT — see [LICENSE](./LICENSE).
