# AppBand — Architecture

AppBand is a per-app bandwidth & network monitor for macOS. This document describes **what it
does today**, **how each capability is implemented**, and — most importantly — **why it is built
that way**. It is the design rationale that does not fit in inline comments.

> The git directory is `netmon`, but the product, the Python package, and every LaunchAgent label
> are `appband` / `dev.appband.*`.

---

## 1. Design philosophy — three hard constraints

Every architectural decision below follows from three non-negotiable constraints
(see `CONTRIBUTING.md`). They are stated first because they explain the "why" for almost
everything else.

| Constraint | What it means | Why |
|---|---|---|
| **No third-party Python deps** | stdlib only; nothing that needs `pip install` | A monitoring tool people run continuously should have zero supply-chain surface and install with nothing but the system `python3`. It also forces simple, inspectable code. |
| **macOS-only** | Backend shells out to `nettop`, `lsof`, `route`, `ipconfig`, `ifconfig` | These tools already expose the kernel's network accounting. Reusing them avoids a packet-capture entitlement, kernel extension, or root privileges. |
| **Localhost-only** | The HTTP server binds `127.0.0.1` | The product's premise is local privacy. Data never leaves the machine; the dashboard is reachable only from the same host. |

Two corollaries that shape the code:

- **stdlib-only ⇒ the database *is* the architecture.** With no message broker, no Redis, no
  framework, SQLite (built into Python) becomes both the datastore and the only IPC channel.
- **No root ⇒ no per-byte packet capture.** This is the single most important limitation and
  the reason the "approximation model" (§7) exists.

---

## 2. Process model — two daemons, one database, no IPC

```
                 ┌─────────────────────────────────────────────┐
   macOS         │  ~/Library/Application Support/appband/      │
   LaunchAgents  │            appband.db  (SQLite, WAL)         │
                 └───────────────▲───────────────▲──────────────┘
                                 │ write          │ read
        ┌────────────────────────┴───┐      ┌─────┴───────────────────────┐
        │  dev.appband.collector     │      │  dev.appband.server         │
        │  (appband.collector)       │      │  (appband.server)           │
        │  multi-threaded poller     │      │  ThreadingHTTPServer        │
        │  nettop / lsof / route…    │      │  JSON API + static dashboard│
        └────────────────────────────┘      └─────────────▲───────────────┘
                                                           │ HTTP /api/* (127.0.0.1:8765)
                                             ┌─────────────┴───────────────┐
                                             │  mac-app  (AppBand.app)      │
                                             │  NSStatusItem + NSPopover    │
                                             │  polls /api/current every 5s │
                                             └──────────────────────────────┘
```

Two independent `launchd` user agents run forever (`RunAtLoad` + `KeepAlive`):

- **`dev.appband.collector`** — writes samples.
- **`dev.appband.server`** — reads samples and serves the dashboard.

**They never talk to each other directly.** The only channel between them is the shared SQLite
database. There is no socket, no pipe, no shared memory.

**Why two processes instead of one?** Separation of failure domains and cadence. A crash or a
slow `VACUUM` in the collector must not take down the dashboard, and vice-versa. SQLite in WAL
mode supports one writer + many concurrent readers across processes, so the split is free.

**Why DB-as-IPC?** It is the only persistence layer the stdlib-only rule allows, and it doubles
as durable storage. Any state the server needs (current session, throughput, history) is already
in the tables the collector writes — so no separate IPC protocol is needed.

The LaunchAgent plists are rendered from templates in `launchd/*.plist.template` by
`scripts/install.sh` (it `sed`-substitutes `__PROJECT_ROOT__` / `__LOG_DIR__`, then
`launchctl bootstrap`s the result).

---

## 3. The collector — `appband/collector.py`

The heart of the system: a multi-threaded daemon where **each worker runs on its own cadence and
opens its own thread-local `sqlite3.Connection`** via `_conn(state)`.

| Thread | Cadence | Command | Writes |
|---|---|---|---|
| `session` | 2 s | `route`, `ipconfig`, `ifconfig` | opens/closes `sessions` rows |
| `iface` | 5 s | `nettop -m route` | `interface_samples` (total bytes/route) |
| `proc` | 10 s | `nettop` | `process_samples` (bytes/process) |
| `conn` | 30 s | `lsof -i` | `connections` (process → remote IP) |
| `retain` | daily | — | `purge_old` + `vacuum` |
| `dns` | event-driven | `socket.gethostbyaddr` | `dns_cache` |

### Why thread-local connections?

`sqlite3` connection objects are not safe to share across threads. WAL mode, however, allows
**multiple concurrent writers** (serialized by SQLite, but each from its own connection). So each
worker thread lazily opens its own connection on first use:

```python
def _conn(state):
    if not hasattr(_thread_local, "conn"):
        c = sqlite3.connect(str(state.db_path), isolation_level=None, timeout=10.0,
                            check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        ...
```

`isolation_level=None` = autocommit (each `INSERT` is durable immediately, matching the
"continuous append" workload). `timeout=10.0` lets a writer wait out a transient lock instead of
erroring.

### The `active_session_id` handoff

`state.active_session_id` is the one piece of shared mutable state. The `session` thread sets it;
**every other writer skips inserting while it is `None`.** This guarantees every sample row has a
valid `session_id` foreign key — a sample collected during a network transition (no active
session) is simply dropped rather than orphaned.

### The DNS thread is special

Reverse-DNS is I/O-bound and can block for seconds. It runs in its **own thread with its own
asyncio event loop and its own dedicated connection**, so DNS latency never competes with the
hot-path writer threads. IPs are handed to it thread-safely:

```python
loop.call_soon_threadsafe(resolver.queue.put_nowait, ip)
```

### Error containment

Each tick is wrapped in `try/except` that logs and continues; a single bad `nettop` run never
kills a thread. `_run()` swallows `SubprocessError`/`OSError` and returns `""`, which every parser
treats as "no rows this tick." (Hardening this — distinguishing a *missing* tool from a transient
timeout — is on the backlog.)

### Shutdown

`SIGTERM`/`SIGINT` set a `threading.Event`; threads observe it on their `stop.wait(...)` and exit.
The active session is closed with a fresh short-lived connection, and the DNS loop's pending tasks
are cancelled before `loop.stop()`.

---

## 4. Cumulative-counter → delta conversion — `appband/delta.py`

`nettop` reports **cumulative** byte counters (monotonically increasing totals), but the dashboard
wants **per-interval deltas**. `DeltaTracker.update(key, value, now)` converts them:

- First time a key is seen → returns `None` (anchor only, no delta yet).
- New value **lower** than the anchor → counter reset → re-anchor, return `None`.
- Delta exceeding `discontinuity_threshold_bps` (default 100 MB/s) → treat as a discontinuity
  (sleep/wake, route churn) → re-anchor, return `None`.
- Otherwise → return the non-negative delta.

**Why `None` instead of 0 on a discontinuity?** Returning `None` means "re-anchor, skip this tick."
This is the mechanism that prevents a multi-hour sleep/wake gap from producing a single enormous
fake spike. The cost: the gap itself is currently *silent* (indistinguishable downstream from
idle) — recording explicit gaps is on the backlog.

`evict_missing()` ages out keys for processes/routes that have vanished, after N consecutive
misses, so the tracker's memory doesn't grow unbounded.

---

## 5. Session detection — `appband/session_watcher.py`

A "session" is a contiguous period on one network **identity**: `(interface, link_type, ssid,
bssid)`. `collect_snapshot()` runs `route -n get default` → `ipconfig getsummary` → `ifconfig`,
then `classify_link_type()` maps the result to one of `wifi` / `iphone-hotspot` / `usb-tether` /
`ethernet`.

`SessionWatcher.tick()` reconciles the live snapshot against the DB:

- snapshot `None` (offline) → close the open session.
- identity unchanged → keep the current session id.
- identity changed → close the old session, open a new one.

**Why track sessions at all?** It lets the dashboard answer "how much did I use *on this
network*" (e.g. a metered hotspot vs. home Wi-Fi) and attributes every byte to a known network
context. On restart, the watcher recovers the still-open session from the DB so a collector
restart doesn't fragment a session.

---

## 6. The server — `appband/server.py`

A localhost `ThreadingHTTPServer` that **opens a fresh read connection per request** (simple,
stateless, and safe under WAL's many-readers model). It serves:

- the static dashboard from `appband/web/` (via `_static`), and
- a JSON API: `/api/current`, `/api/sessions`, `/api/timeseries`, `/api/by-network`,
  `/api/by-process`, `/api/by-domain`.

**Why a fresh connection per request?** No connection pool to manage (stdlib has none), no
thread-affinity concerns, and request volume is tiny (a single local dashboard polling every few
seconds). Correctness beats micro-optimization here.

---

## 7. The approximation model — the most important thing to understand

There is **no per-connection byte accounting**, and this is a direct consequence of the no-root /
no-packet-capture constraint:

- `nettop` gives **bytes per process** — but not per destination.
- `lsof -i` gives **which hosts a process is connected to** — but not how many bytes to each.

So AppBand cannot say "Safari sent 2 GB *to youtube.com*" from first principles. Instead, the
`/api/by-domain` and scoped `/api/by-process` queries **distribute** each process's bytes across
the hostnames / scope it touched within the same **5-minute bucket** (`BUCKET = 300`):

- *by-domain*: a process's bytes in a bucket are split **equally** across the distinct hosts it
  talked to in that bucket.
- *by-process (scoped)*: bytes are weighted by the ratio of `internet` vs `lan` connections
  (`scope`) the process had in that bucket.

These results are flagged `"approximate": true`. **The aggregate (`interface_samples`) and the
unscoped per-process (`scope=all`) numbers are exact** (`approximate: false`) — only the
attribution-to-host step is an estimate.

**Why 5-minute buckets?** A bucket large enough to almost always contain at least one `conn` tick
(30 s cadence) and several `proc` ticks (10 s), so the join has data to distribute, but small
enough that a process isn't credited to a host it talked to hours earlier.

> Design guidance: lead the UX with the exact surfaces (totals, per-app, per-network); present
> by-domain as a clearly-labeled estimate. Never present the approximate numbers as exact — the
> README's "Caveats" section documents this contract to users.

---

## 8. DNS resolution & cache — `appband/dns_cache.py`

An async reverse-DNS resolver backed by the `dns_cache` table. It bounds concurrency with a
semaphore, times out individual lookups, and caches results persistently with a retry policy:
**failures retried after 24 h, successes after 90 days.** This keeps the by-domain panel readable
(hostnames instead of bare IPs) without hammering DNS or re-resolving stable IPs.

---

## 9. Schema & migrations — `appband/db.py`

Tables: `sessions`, `interface_samples`, `process_samples`, `connections`, `dns_cache`.
`init_schema` runs `CREATE TABLE IF NOT EXISTS …`, enables WAL + foreign keys.

**There is no migration framework.** Schema changes are **additive only**, applied via the
`_ensure_column` helper:

```python
_ensure_column(conn, "connections", "scope", "TEXT")   # ALTER TABLE … ADD COLUMN if absent
```

**Why no migrations?** stdlib-only and a single-file local DB make a full migration tool
overkill. The trade-off is a real footgun: **bumping a column in the `SCHEMA` string does not
alter existing databases** — you must add a matching `_ensure_column` call. New tables are safe
(the `IF NOT EXISTS` create handles them); changed columns are not.

---

## 10. Parsers — `appband/parsers/`

Pure functions, one module per command (`nettop`, `lsof`, `netstat`, `network_info`). They take
raw command text and return plain dicts — **no I/O, no DB, no subprocess.** This is what makes the
system testable: the only mocked boundary is `_run` (the subprocess call) and
`socket.gethostbyaddr`; everything downstream is exercised with real strings.

Real command output is quirky (e.g. `nettop` process names contain dots, so name/pid is split on
the *last* dot; trailing empty columns; two distinct real-world output formats — see the docstring
in `nettop.py`). The convention: when you change a parser, capture a fixture under
`tests/fixtures/` and assert against it.

**Why `nettop -m route` for interface totals instead of per-interface counters?** Per-interface
byte counters can **stall** on iPhone Personal Hotspot tethering due to a kernel bug. Summing
per-route totals via `nettop -m route` dodges that, at the cost of occasionally lost ticks when
routes churn (handled by `DeltaTracker` as a re-anchor).

---

## 11. Retention — `appband/retention.py`

A daily thread runs `purge_old` (deletes `interface_samples`/`process_samples`/`connections`
older than `retention_days` = 30; `dns_cache` older than `dns_cache_retention_days` = 90; and
*ended* sessions older than the sample cutoff) followed by `VACUUM`.

Known sharp edges (on the backlog): the daily blocking `VACUUM` contends with the per-request read
connections, the WAL is never explicitly checkpointed between runs, and a session left with
`ended_at IS NULL` (unclean shutdown) is never purged — silently retaining its samples past 30
days.

---

## 12. The Mac app — `mac-app/`

A native SwiftUI **menu-bar-only** app (`NSStatusItem` + `NSPopover`, `LSUIElement`, no main
window). Its job is to bundle, install, and drive the Python backend, and to show live throughput.

- **`BackendInstaller`** — on first launch, copies the bundled Python backend out of
  `AppBand.app/Contents/Resources/backend/` into `~/Library/Application Support/AppBand/backend/`
  and runs `scripts/install.sh` from there. Idempotent: it checks whether the plist and
  `collector.py` already exist. *(Caveat: it short-circuits on mere existence, so updating the app
  does not currently re-copy a newer backend — see backlog.)*
- **`NetworkMonitor`** — an `ObservableObject` that polls `http://127.0.0.1:8765/api/current`
  every 5 s to drive the menu-bar `↓/↑ Mbps` label and the popover.
- **`AppBandApp` / `AppDelegate`** — wires the status item, popover, and a 1 Hz title timer.

**Build & signing.** `mac-app/build.sh` builds a universal Swift release binary, assembles the
`.app`, bundles the backend into `Resources/`, and **ad-hoc signs** it (`codesign --sign -`). It is
**not notarized** — notarization needs a paid Apple Developer account. `build-dmg.sh <version>`
packages a DMG. Because the app is ad-hoc signed, first launch triggers Gatekeeper; the README
documents the bypass.

**Version coupling.** The version lives in `Info.plist` (`CFBundleShortVersionString`) and is
echoed in the README download link — currently hand-synced (and already drifted: the About sheet
hardcodes an older string). Single-sourcing this is on the backlog.

---

## 13. Testing conventions

`unittest` only — **no pytest.** Mock the **subprocess boundary** (`appband.*._run`,
`socket.gethostbyaddr`), never internal logic — parsers and DB code are exercised directly. Tests
that touch the collector use a **real temp DB file** (not `:memory:`), because `_conn()` opens
connections by path from multiple threads and an in-memory DB would not be shared across them.
Fixtures of real command output live under `tests/fixtures/`.

```bash
python3 -m unittest discover tests -v
```

---

## 14. Data & log locations (outside the repo)

- DB: `~/Library/Application Support/appband/appband.db` (+ `-wal`, `-shm`)
- Logs: `~/Library/Logs/appband/{collector,server}.log`
- Config defaults: `appband/config.py` (overridable by a JSON file passed to `load_config`)

---

*See `TODO.md` for the prioritized backlog of improvements to everything described here.*
