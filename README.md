# AppBand

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

```bash
git clone https://github.com/<you>/appband ~/Development/appband
cd ~/Development/appband
./scripts/install.sh
```

The dashboard opens automatically at `http://127.0.0.1:8765/`.

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
