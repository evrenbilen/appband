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
