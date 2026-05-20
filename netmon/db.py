"""SQLite schema and connection helpers for netmon."""
from __future__ import annotations

import sqlite3
from pathlib import Path

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
  protocol      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conn_ts ON connections(ts);
CREATE INDEX IF NOT EXISTS idx_conn_ip ON connections(remote_ip);

CREATE TABLE IF NOT EXISTS dns_cache (
  ip           TEXT PRIMARY KEY,
  hostname     TEXT,
  resolved_at  INTEGER NOT NULL
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables, indexes, and enable WAL on a fresh or existing DB."""
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection to the netmon DB and ensure schema exists."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=10.0)
    init_schema(conn)
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
) -> None:
    conn.execute(
        "INSERT INTO connections (ts, session_id, process_name, remote_ip, remote_port, protocol) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ts, session_id, process_name, remote_ip, remote_port, protocol),
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


def query_timeseries(
    conn: sqlite3.Connection,
    from_ts: int,
    to_ts: int,
    granularity: str = "hour",
) -> list[dict]:
    """Aggregate interface_samples into time buckets."""
    bucket = 3600 if granularity == "hour" else 86400
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
