"""SQLite schema and connection helpers for appband."""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("appband.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id          INTEGER PRIMARY KEY,
  started_at  INTEGER NOT NULL,
  ended_at    INTEGER,
  interface   TEXT NOT NULL,
  link_type   TEXT NOT NULL,
  ssid        TEXT,
  bssid       TEXT,
  ip_address  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);

CREATE TABLE IF NOT EXISTS interface_samples (
  id          INTEGER PRIMARY KEY,
  ts          INTEGER NOT NULL,
  session_id  INTEGER NOT NULL REFERENCES sessions(id),
  bytes_in    INTEGER NOT NULL,
  bytes_out   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_iface_ts ON interface_samples(ts);
CREATE INDEX IF NOT EXISTS idx_iface_session ON interface_samples(session_id);

CREATE TABLE IF NOT EXISTS process_samples (
  id            INTEGER PRIMARY KEY,
  ts            INTEGER NOT NULL,
  session_id    INTEGER NOT NULL REFERENCES sessions(id),
  process_name  TEXT NOT NULL,
  pid           INTEGER,
  bytes_in      INTEGER NOT NULL,
  bytes_out     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proc_ts ON process_samples(ts);
CREATE INDEX IF NOT EXISTS idx_proc_name_ts ON process_samples(process_name, ts);

CREATE TABLE IF NOT EXISTS connections (
  id            INTEGER PRIMARY KEY,
  ts            INTEGER NOT NULL,
  session_id    INTEGER NOT NULL REFERENCES sessions(id),
  process_name  TEXT NOT NULL,
  remote_ip     TEXT NOT NULL,
  remote_port   INTEGER,
  protocol      TEXT NOT NULL,
  scope         TEXT
);
CREATE INDEX IF NOT EXISTS idx_conn_ts ON connections(ts);
CREATE INDEX IF NOT EXISTS idx_conn_ip ON connections(remote_ip);

CREATE TABLE IF NOT EXISTS dns_cache (
  ip           TEXT PRIMARY KEY,
  hostname     TEXT,
  resolved_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS collector_health (
  poller       TEXT PRIMARY KEY,
  last_ok_ts   INTEGER NOT NULL
);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    if column not in {r[1] for r in cur.fetchall()}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables, indexes, and enable WAL on a fresh or existing DB."""
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    _ensure_column(conn, "connections", "scope", "TEXT")
    conn.commit()


def _open(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path), isolation_level=None, timeout=10.0, check_same_thread=False)


def _quarantine_corrupt_db(db_path: Path, error: Exception) -> None:
    """Rename a corrupt DB and its WAL/SHM sidecars aside so a fresh one can be
    created — otherwise a corrupt file crash-loops the KeepAlive collector."""
    ts = int(time.time())
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            try:
                p.rename(Path(f"{db_path}.corrupt-{ts}{suffix}"))
            except OSError:
                pass
    log.error("quarantined corrupt DB %s (%s); starting fresh", db_path, error)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the appband DB, ensure schema, and self-heal a corrupt file."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open(db_path)
    try:
        # quick_check is fast and raises (DatabaseError) or returns non-"ok" on
        # a malformed/non-SQLite *main* file. A 0-byte file is a valid empty DB
        # ("ok") and is just initialized below.
        # Limitation: quick_check reads only the main file, so a corrupt -wal/
        # -shm sidecar on an otherwise-healthy DB is not caught here — and can't
        # be auto-quarantined safely, since it can surface as OperationalError,
        # indistinguishable from normal multi-process write contention (which
        # must NOT be quarantined). WAL corruption that does raise DatabaseError
        # IS quarantined (the sidecars are renamed too).
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("quick_check failed")
        init_schema(conn)
    except sqlite3.OperationalError:
        # Transient — e.g. "database is locked" (OperationalError subclasses
        # DatabaseError). NOT corruption: let it propagate so launchd retries,
        # rather than quarantining a healthy DB and losing data.
        conn.close()
        raise
    except sqlite3.DatabaseError as e:
        conn.close()
        _quarantine_corrupt_db(db_path, e)
        conn = _open(db_path)
        init_schema(conn)
    # The DB is a longitudinal record of network behavior — restrict it to the
    # owner so other local users can't read it at rest. (Not encrypted.)
    try:
        os.chmod(db_path, 0o600)
    except OSError as e:
        log.warning("could not chmod %s to 0600: %s", db_path, e)
    return conn


def open_session(
    conn: sqlite3.Connection,
    started_at: int,
    interface: str,
    link_type: str,
    ssid: str | None,
    bssid: str | None,
    ip_address: str | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO sessions (started_at, interface, link_type, ssid, bssid, ip_address) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (started_at, interface, link_type, ssid, bssid, ip_address),
    )
    return cur.lastrowid


def close_session(conn: sqlite3.Connection, session_id: int, ended_at: int) -> None:
    conn.execute(
        "UPDATE sessions SET ended_at = ? WHERE id = ?", (ended_at, session_id)
    )


def get_active_session(conn: sqlite3.Connection) -> dict | None:
    cur = conn.execute(
        "SELECT id, started_at, ended_at, interface, link_type, ssid, bssid, ip_address "
        "FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if row is None:
        return None
    keys = ["id", "started_at", "ended_at", "interface", "link_type", "ssid", "bssid", "ip_address"]
    return dict(zip(keys, row))


def insert_interface_sample(
    conn: sqlite3.Connection,
    ts: int,
    session_id: int,
    bytes_in: int,
    bytes_out: int,
) -> None:
    conn.execute(
        "INSERT INTO interface_samples (ts, session_id, bytes_in, bytes_out) VALUES (?, ?, ?, ?)",
        (ts, session_id, bytes_in, bytes_out),
    )


def insert_process_sample(
    conn: sqlite3.Connection,
    ts: int,
    session_id: int,
    process_name: str,
    pid: int | None,
    bytes_in: int,
    bytes_out: int,
) -> None:
    conn.execute(
        "INSERT INTO process_samples (ts, session_id, process_name, pid, bytes_in, bytes_out) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ts, session_id, process_name, pid, bytes_in, bytes_out),
    )


def insert_connection(
    conn: sqlite3.Connection,
    ts: int,
    session_id: int,
    process_name: str,
    remote_ip: str,
    remote_port: int | None,
    protocol: str,
    scope: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO connections (ts, session_id, process_name, remote_ip, remote_port, protocol, scope) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts, session_id, process_name, remote_ip, remote_port, protocol, scope),
    )


def upsert_dns(
    conn: sqlite3.Connection,
    ip: str,
    hostname: str | None,
    resolved_at: int,
) -> None:
    conn.execute(
        "INSERT INTO dns_cache (ip, hostname, resolved_at) VALUES (?, ?, ?) "
        "ON CONFLICT(ip) DO UPDATE SET hostname = excluded.hostname, resolved_at = excluded.resolved_at",
        (ip, hostname, resolved_at),
    )


def get_dns_hostname(conn: sqlite3.Connection, ip: str) -> str | None:
    cur = conn.execute("SELECT hostname FROM dns_cache WHERE ip = ?", (ip,))
    row = cur.fetchone()
    if row is None:
        return None
    return row[0]


def record_heartbeat(conn: sqlite3.Connection, poller: str, ts: int) -> None:
    """Record a poller's last-successful-tick time (the collector's only
    liveness signal — the two daemons share no IPC but this DB)."""
    conn.execute(
        "INSERT INTO collector_health (poller, last_ok_ts) VALUES (?, ?) "
        "ON CONFLICT(poller) DO UPDATE SET last_ok_ts = excluded.last_ok_ts",
        (poller, ts),
    )


def get_health(conn: sqlite3.Connection) -> dict:
    """Return {poller: last_ok_ts} for all recorded pollers."""
    cur = conn.execute("SELECT poller, last_ok_ts FROM collector_health")
    return {r[0]: r[1] for r in cur.fetchall()}


def query_timeseries(
    conn: sqlite3.Connection,
    from_ts: int,
    to_ts: int,
    granularity: str = "hour",
) -> list[dict]:
    """Aggregate interface_samples into time buckets (minute / hour / day)."""
    bucket = {"minute": 60, "hour": 3600, "day": 86400}.get(granularity, 3600)
    cur = conn.execute(
        f"""
        SELECT (ts / {bucket}) * {bucket} AS bucket,
               SUM(bytes_in)  AS bytes_in,
               SUM(bytes_out) AS bytes_out
          FROM interface_samples
         WHERE ts >= ? AND ts < ?
         GROUP BY bucket
         ORDER BY bucket
        """,
        (from_ts, to_ts),
    )
    return [
        {"ts": row[0], "bytes_in": row[1] or 0, "bytes_out": row[2] or 0}
        for row in cur.fetchall()
    ]
