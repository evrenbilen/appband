# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**AppBand** — a per-app bandwidth & network monitor for macOS. The git directory is `netmon`, but the product, Python package, and all LaunchAgent labels are `appband` / `dev.appband.*`. Two parts:

- **`appband/`** — Python 3 stdlib-only backend (collector daemon + HTTP server + web dashboard).
- **`mac-app/`** — a native SwiftUI menu-bar app that bundles, installs, and drives the backend, and shows live throughput.

## Planning & docs (read these before non-trivial work)

- **`TODO.md`** — the prioritized backlog: epics + sub-tasks across four tiers (`P0` now → `P3` later), each tagged with effort (S/M/L), impact, and the files it touches. This is the source of truth for *what to work on next* and *in what order*. When you finish a sub-task, check it off (`- [x]`); when you add work, slot it under the right epic/tier. The current first priority is **EPIC P0-A: local-surface security hardening** (Host/Origin gate, self-host Chart.js + CSP, clamp `bind_host`) — it is a prerequisite for any new sensitive endpoint.
- **`docs/ARCHITECTURE.md`** — the design-rationale doc: current capabilities and *how & why* they are built this way (two-process / shared-SQLite / no-IPC model, the collector's thread-local connections, the cumulative→delta conversion, the approximation model, the schema/migration approach, the Mac app). Read it to understand intent before changing behavior; update it when an architectural decision changes.

## Hard constraints (these are non-negotiable, from CONTRIBUTING.md)

- **No third-party Python dependencies.** stdlib only — never add anything that needs `pip install`. This is a deliberate design choice; a feature needing a dep should be discussed in an issue first.
- **macOS-only.** Backend shells out to macOS tools (`nettop`, `lsof`, `route`, `ipconfig`, `ifconfig`). No Linux/Windows support.
- **Localhost-only.** The server binds `127.0.0.1`. Never introduce a network-facing surface.
- Every module starts with `from __future__ import annotations`; Python 3.10+ type hints.

## Commands

```bash
# Tests — stdlib unittest only, NO pytest
python3 -m unittest discover tests -v
python3 -m unittest tests.test_delta                       # single module
python3 -m unittest tests.test_delta.DeltaTrackerTest.test_independent_keys   # single test

# Run a daemon directly (PYTHONPATH must point at repo root)
PYTHONPATH=. python3 -m appband.collector
PYTHONPATH=. python3 -m appband.server     # dashboard at http://127.0.0.1:8765/

# Install / manage as LaunchAgents (dev loop)
./scripts/install.sh        # render plist templates, bootstrap + start both agents, open dashboard
./scripts/status.sh         # launchctl state + DB stats + recent log
./scripts/uninstall.sh      # stop agents, keep DB   (--purge also deletes DB)
./scripts/vacuum.sh         # compact the SQLite DB

# Mac app
cd mac-app && ./build.sh                # → AppBand.app (Swift release + bundled backend, ad-hoc signed)
cd mac-app && ./build-dmg.sh <version>  # → AppBand-<version>.dmg
```

Runtime data lives outside the repo: DB at `~/Library/Application Support/appband/appband.db` (SQLite WAL), logs at `~/Library/Logs/appband/{collector,server}.log`. Config defaults live in `appband/config.py` and can be overridden by a JSON file passed to `load_config`.

## Architecture

Two LaunchAgent processes (`dev.appband.collector`, `dev.appband.server`) share one SQLite DB. They communicate only through that DB — there is no IPC.

### Collector (`appband/collector.py`) — the heart of the system

A multi-threaded daemon. Each worker runs on its own cadence and **opens its own thread-local `sqlite3.Connection`** via `_conn(state)` (WAL allows concurrent writers). Threads:

- **session** (2s) — `SessionWatcher` + `collect_snapshot`: detects the active network identity and opens/closes `sessions` rows. `state.active_session_id` is the shared handoff; every other writer skips inserting while it's `None`.
- **iface** (5s) — `nettop -m route`: total bytes per route (chosen over per-interface counters to dodge a kernel bug that stalls counters on iPhone-hotspot tethering).
- **proc** (10s) — `nettop`: per-process bytes.
- **conn** (30s) — `lsof -i`: active outbound connections (process → remote IP), each remote IP enqueued for reverse-DNS.
- **retention** (daily) — `purge_old` + `vacuum`.
- **dns** — a separate thread running an asyncio loop with its **own** connection; `DnsResolver` consumes IPs off a queue fed thread-safely via `loop.call_soon_threadsafe`.

### Cumulative-counter → delta conversion (`appband/delta.py`)

`nettop` reports cumulative byte counters. `DeltaTracker.update(key, value, now)` returns the per-interval delta, or `None` on first sight or a discontinuity (counter reset, or a delta exceeding `discontinuity_threshold_bps` — e.g. sleep/wake, route churn). `None` means "re-anchor, skip this tick" — this is why gaps never produce huge spikes. `evict_missing` ages out keys (processes/routes that vanished) after N misses.

### Server (`appband/server.py`)

Localhost `ThreadingHTTPServer`. Opens a **fresh read connection per request**. Serves the static dashboard from `appband/web/` and a JSON API: `/api/current` (incl. exact `top_apps` + `coverage`), `/api/sessions`, `/api/timeseries` (`granularity` minute/hour/day), `/api/by-network`, `/api/by-process`, `/api/by-domain`, `/api/by-port`, `/api/health`, `/api/gaps`, `/api/version`. The analytics endpoints take an optional `ssid`/`link_type` network filter (JOIN sessions). **Security (P0-A):** every request's `Host`/`Origin` must be loopback (else 403 — DNS-rebinding defense); a strict CSP + self-hosted Chart.js (`/static/vendor/`); `load_config` clamps a non-loopback `bind_host`; the DB is `0600`.

### The approximation model (important when touching `_by_process` / `_by_domain`)

There is **no per-connection byte accounting** — `nettop` gives bytes-per-process, `lsof` gives which hosts a process talked to, but not bytes-per-host. So the by-domain and by-process-by-scope queries **distribute** each process's bytes across the hostnames/scope it touched within the same **5-minute bucket** (`BUCKET = 300`). Results are flagged `"approximate": true`. `scope` (`internet` vs `lan`, set per-connection) weights this split. Don't present these numbers as exact; the README's "Caveats" section documents this contract to users.

### Schema & migrations (`appband/db.py`)

Tables: `sessions`, `interface_samples`, `process_samples`, `connections`, `dns_cache`, `collector_health` (per-poller heartbeat → `/api/health`), `gaps` (sleep/wake suspension windows → `/api/gaps`). `init_schema` runs `CREATE TABLE IF NOT EXISTS` + enables WAL/foreign-keys. There is **no migration framework** — schema changes are additive only, via the `_ensure_column` helper (see the `connections.scope` example) or a new `CREATE TABLE/INDEX IF NOT EXISTS`. Bumping columns in `SCHEMA` won't alter existing DBs; add an `_ensure_column` call. `connect()` self-heals a corrupt DB (quick_check → quarantine + recreate) and applies WAL-safe perf pragmas (`apply_perf_pragmas`).

### Parsers (`appband/parsers/`)

Pure functions, one per command (`nettop`, `lsof`, `netstat`, `network_info`). They take raw command text and return plain dicts — no I/O. `network_info.classify_link_type` maps a snapshot to `wifi` / `iphone-hotspot` / `usb-tether` / `ethernet`. Real-world command output is quirky (see the docstrings in `nettop.py`); when changing a parser, add a fixture under `tests/fixtures/` and assert against it.

### Mac app (`mac-app/`)

SwiftUI menu-bar app (`NSStatusItem` + `NSPopover`, no main window). On first launch `BackendInstaller` copies the Python backend out of `AppBand.app/Contents/Resources/backend/` into `~/Library/Application Support/AppBand/backend/` and runs `scripts/install.sh` (idempotent). `NetworkMonitor` polls `/api/current` every 5s to drive the menu-bar throughput label and popover. The app version lives in `mac-app/Sources/AppBand/Info.plist` (`CFBundleShortVersionString`) and is echoed in the README download link — keep them in sync on release. The bundle is **ad-hoc signed, not notarized** (Gatekeeper bypass documented in the README).

## Testing conventions

- `unittest` only. Mock the **subprocess boundary** (`appband...._run`, `socket.gethostbyaddr`), never internal logic — parsers and DB code are exercised directly.
- Tests that touch the collector use a **real temp DB file**, not `:memory:`, because `_conn()` opens connections by path from multiple threads.
- Tests live next to the behavior they verify (`tests/test_<module>.py`); command-output fixtures live in `tests/fixtures/`.
- The web dashboard has **Playwright e2e** under `e2e/` (Node, dev-only — does NOT affect the stdlib-only backend): `cd e2e && npm install && npx playwright install chromium && npm test`. Run it for any frontend change. CI (`.github/workflows/ci.yml`) runs unittest + `swift build` + e2e; `release.yml` builds/DMGs/SHA-256 on a `v*` tag.
