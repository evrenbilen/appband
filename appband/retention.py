"""Periodic cleanup: delete old samples and VACUUM the DB."""
from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger("appband.retention")


def purge_old(
    conn: sqlite3.Connection,
    now: int,
    sample_retention_sec: int,
    dns_retention_sec: int,
) -> None:
    sample_cutoff = now - sample_retention_sec
    dns_cutoff = now - dns_retention_sec

    cur = conn.execute("DELETE FROM interface_samples WHERE ts < ?", (sample_cutoff,))
    iface_deleted = cur.rowcount
    cur = conn.execute("DELETE FROM process_samples WHERE ts < ?", (sample_cutoff,))
    proc_deleted = cur.rowcount
    cur = conn.execute("DELETE FROM connections WHERE ts < ?", (sample_cutoff,))
    conn_deleted = cur.rowcount
    cur = conn.execute(
        "DELETE FROM sessions WHERE ended_at IS NOT NULL AND ended_at < ?",
        (sample_cutoff,),
    )
    sess_deleted = cur.rowcount
    cur = conn.execute("DELETE FROM dns_cache WHERE resolved_at < ?", (dns_cutoff,))
    dns_deleted = cur.rowcount

    log.info(
        "purge: iface=%d proc=%d conn=%d sess=%d dns=%d",
        iface_deleted, proc_deleted, conn_deleted, sess_deleted, dns_deleted,
    )


def vacuum(conn: sqlite3.Connection) -> None:
    conn.execute("VACUUM")


def wal_checkpoint(conn: sqlite3.Connection):
    """Checkpoint the WAL into the main DB and truncate it. Cheap maintenance
    the design lacked: between daily VACUUMs the WAL grew unbounded under the
    four writer threads. Returns the PRAGMA row (busy, log, checkpointed)."""
    return conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
