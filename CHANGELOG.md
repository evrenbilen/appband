# Changelog

All notable changes to AppBand are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

Work on the `feat/*` branches, not yet released. Highlights:

### Security & privacy
- Validate the `Host`/`Origin` header (DNS-rebinding / cross-origin defense) and
  send a strict Content-Security-Policy + `nosniff`/`no-referrer` on every response.
- Self-host Chart.js (no CDN at runtime); clamp a non-loopback `bind_host` to
  loopback; create the DB `0600`.

### Added
- Exact live per-app view: `/api/current` returns `top_apps` (last 60s) and a
  `coverage` ratio; the dashboard LIVE panel and the menu-bar popover show it.
- `minute` time-series granularity (per-minute buckets for short ranges).
- Per-network (SSID / link-type) filter across `/api/timeseries`, `/api/by-process`,
  `/api/by-domain` — wiring the previously-dead dashboard network selector.
- `/api/by-port` port/protocol breakdown; `/api/health` (collector heartbeat);
  `/api/version`.
- Menu-bar app: Restart Services, Start-at-Login (SMAppService), in-app Uninstall,
  surfaced install failures, and a connecting/online/offline state.
- A visible "approximate" badge + explainer on the estimated panels.
- GitHub Actions CI (unittest + `swift build` + Playwright e2e); a Playwright
  dashboard e2e suite; single-sourced version (`appband.__version__`).

### Fixed
- DB-corruption quarantine-and-recreate (breaks the launchd crash loop), without
  nuking a healthy-but-locked DB.
- Hourly WAL checkpoint, `RotatingFileHandler`, close orphaned sessions on startup,
  distinguish a missing tool from a transient failure, quiet client disconnects.
- Classify VPN/tunnel sessions as `vpn` (were mislabeled `ethernet`); strip IPv6
  zone ids and stop mangling bare IPv6 addresses in the lsof parser.
- Build-time version injection into `Info.plist`; the About sheet reads the real
  version; updating the app re-copies the bundled backend.

## [0.1.4] — 2026-06-01
### Added
- Branded DMG background with a drag hint and a Gatekeeper note.
- Dashboard / popover / menu-bar screenshots in the README.

## [0.1.3] — 2026-06-01
### Fixed
- Menu bar reworked to `NSStatusItem` + `NSPopover` (fixes click flicker).

## [0.1.2] — 2026-06-01
### Added
- Visible inline `↓/↑ Mbps` in the menu bar and a redesigned popover.

## [0.1.1] — 2026-06-01
### Added
- App icon, `build-dmg.sh`, and the Gatekeeper-bypass documentation.

## [0.1.0] — 2026-06-01
First public release.
### Added
- Collector daemon (session / interface / process / connection threads) sharing a
  SQLite WAL DB with a localhost JSON API + web dashboard (5 panels, Chart.js).
- `DeltaTracker` cumulative-counter sampling; async reverse-DNS cache; retention
  (purge + vacuum); LaunchAgent install/uninstall/status/vacuum scripts.
- Internet-vs-LAN scope split; i18n (EN default + TR); native menu-bar wrapper app.
### Fixed
- `nettop -m route` for interface bytes (per-interface counters stall on iPhone
  hotspot); exclude loopback; per-thread / per-request SQLite connections;
  Wi-Fi detection via `ipconfig getsummary` on recent macOS.

[Unreleased]: https://github.com/evrenbilen/appband/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/evrenbilen/appband/releases/tag/v0.1.4
[0.1.3]: https://github.com/evrenbilen/appband/releases/tag/v0.1.3
[0.1.2]: https://github.com/evrenbilen/appband/releases/tag/v0.1.2
[0.1.1]: https://github.com/evrenbilen/appband/releases/tag/v0.1.1
[0.1.0]: https://github.com/evrenbilen/appband/releases/tag/v0.1.0
