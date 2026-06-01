"""appband collector daemon: orchestrates pollers and writes to SQLite."""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import signal
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from appband.config import Config, load_config
from appband.db import (
    close_orphan_sessions,
    connect,
    insert_connection,
    insert_interface_sample,
    insert_process_sample,
    record_heartbeat,
)
from appband.delta import DeltaTracker
from appband.dns_cache import DnsResolver
from appband.parsers.lsof import parse_lsof_connections
from appband.parsers.nettop import parse_nettop
from appband.retention import purge_old, vacuum, wal_checkpoint
from appband.session_watcher import SessionWatcher, collect_snapshot

log = logging.getLogger("appband.collector")

# Thread-local storage — each writer thread gets its own sqlite3.Connection.
_thread_local = threading.local()


@dataclass
class CollectorState:
    db_path: Path                        # replaces conn; threads open their own connections
    iface_tracker: DeltaTracker
    proc_in_tracker: DeltaTracker
    proc_out_tracker: DeltaTracker
    active_interface: str | None
    active_session_id: int | None
    dns_enqueue: Callable[[str], None]


def _conn(state: CollectorState) -> sqlite3.Connection:
    """Return this thread's SQLite connection, opening it lazily on first use."""
    if not hasattr(_thread_local, "conn"):
        c = sqlite3.connect(
            str(state.db_path),
            isolation_level=None,
            timeout=10.0,
            check_same_thread=False,
        )
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _thread_local.conn = c
    return _thread_local.conn


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("subprocess failed: %s: %s", cmd, e)
        return ""


def run_interface_tick(state: CollectorState, now: int) -> None:
    text = _run([
        "/usr/bin/nettop", "-P", "-x", "-L", "1",
        "-m", "route", "-t", "external",
        "-J", "bytes_in,bytes_out",
    ])
    if not text:
        return
    rows = parse_nettop(text)
    if not rows:
        return
    # Routes come and go; sum can decrease between polls. DeltaTracker handles
    # this as a counter reset (returns None, re-anchors). Some ticks lost but
    # never negative.
    total_in = sum(r["bytes_in"] for r in rows)
    total_out = sum(r["bytes_out"] for r in rows)
    delta_in = state.iface_tracker.update("external:in", total_in, now)
    delta_out = state.iface_tracker.update("external:out", total_out, now)
    if delta_in is None or delta_out is None:
        return
    if state.active_session_id is None:
        return
    insert_interface_sample(
        _conn(state),
        ts=now,
        session_id=state.active_session_id,
        bytes_in=delta_in,
        bytes_out=delta_out,
    )


def run_process_tick(state: CollectorState, now: int) -> None:
    text = _run(["/usr/bin/nettop", "-P", "-x", "-L", "1", "-t", "external", "-J", "bytes_in,bytes_out"])
    rows = parse_nettop(text)
    present_keys: set[str] = set()
    for r in rows:
        key = f"{r['pid']}:{r['process_name']}"
        present_keys.add(key + ":in")
        present_keys.add(key + ":out")
        delta_in = state.proc_in_tracker.update(key + ":in", r["bytes_in"], now)
        delta_out = state.proc_out_tracker.update(key + ":out", r["bytes_out"], now)
        if delta_in is None or delta_out is None:
            continue
        if state.active_session_id is None:
            continue
        if delta_in == 0 and delta_out == 0:
            continue
        insert_process_sample(
            _conn(state),
            ts=now,
            session_id=state.active_session_id,
            process_name=r["process_name"],
            pid=r["pid"],
            bytes_in=delta_in,
            bytes_out=delta_out,
        )
    state.proc_in_tracker.evict_missing(present_keys, max_misses=3)
    state.proc_out_tracker.evict_missing(present_keys, max_misses=3)


def run_connection_tick(state: CollectorState, now: int) -> None:
    text = _run(["/usr/sbin/lsof", "-i", "-nP", "-P"])
    rows = parse_lsof_connections(text)
    for r in rows:
        if state.active_session_id is None:
            state.dns_enqueue(r["remote_ip"])
            continue
        insert_connection(
            _conn(state),
            ts=now,
            session_id=state.active_session_id,
            process_name=r["process_name"],
            remote_ip=r["remote_ip"],
            remote_port=r["remote_port"],
            protocol=r["protocol"],
            scope=r["scope"],
        )
        state.dns_enqueue(r["remote_ip"])


def _setup_logging(cfg: Config) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        cfg.log_dir / "collector.log", maxBytes=5_000_000, backupCount=3
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(threadName)s %(message)s")
    )
    root = logging.getLogger("appband")
    root.addHandler(handler)
    root.setLevel(cfg.log_level)


def main(config_path: Path | None = None) -> int:
    cfg = load_config(config_path)
    _setup_logging(cfg)
    log.info("appband collector starting")

    # Run schema migration once at startup with a short-lived connection.
    # Each worker thread will open its own connection lazily via _conn().
    # connect() may raise sqlite3.OperationalError if the DB is locked by
    # another process at startup; that's transient and launchd (KeepAlive +
    # ThrottleInterval=10) retries. It only quarantines on real corruption.
    bootstrap = connect(cfg.db_path)
    close_orphan_sessions(bootstrap, int(time.time()))  # reconcile unclean shutdowns
    bootstrap.close()

    state = CollectorState(
        db_path=cfg.db_path,
        iface_tracker=DeltaTracker(max_delta_per_sec=cfg.discontinuity_threshold_bps),
        proc_in_tracker=DeltaTracker(max_delta_per_sec=cfg.discontinuity_threshold_bps),
        proc_out_tracker=DeltaTracker(max_delta_per_sec=cfg.discontinuity_threshold_bps),
        active_interface=None,
        active_session_id=None,
        dns_enqueue=lambda ip: None,
    )

    stop = threading.Event()

    def _stop(*_):
        log.info("stop signal received")
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    loop = asyncio.new_event_loop()

    # The DNS resolver lives entirely in the asyncio thread; it opens its own
    # connection there so it never competes with the writer threads.
    _resolver_ready = threading.Event()
    _resolver_ref: list[DnsResolver] = []

    def _loop_runner():
        asyncio.set_event_loop(loop)
        dns_conn = sqlite3.connect(
            str(cfg.db_path),
            isolation_level=None,
            timeout=10.0,
            check_same_thread=False,
        )
        dns_conn.execute("PRAGMA journal_mode=WAL")
        dns_conn.execute("PRAGMA foreign_keys=ON")
        resolver = DnsResolver(
            conn=dns_conn,
            timeout=cfg.dns_lookup_timeout_sec,
            concurrency=cfg.dns_concurrency,
        )
        _resolver_ref.append(resolver)
        _resolver_ready.set()
        loop.create_task(resolver.run_forever())
        loop.run_forever()
        dns_conn.close()

    threading.Thread(target=_loop_runner, name="dns", daemon=True).start()
    _resolver_ready.wait(timeout=5.0)

    def _enqueue(ip: str) -> None:
        if _resolver_ref:
            loop.call_soon_threadsafe(_resolver_ref[0].queue.put_nowait, ip)

    state.dns_enqueue = _enqueue

    def _loop(interval: int, fn, name: str):
        last_run = 0
        while not stop.is_set():
            now = int(time.time())
            if now - last_run >= interval:
                try:
                    fn(state, now)
                    record_heartbeat(_conn(state), name, now)  # liveness signal
                except Exception:  # noqa: BLE001
                    log.exception("%s tick failed", name)
                last_run = now
            stop.wait(0.5)

    def _session_loop():
        # SessionWatcher uses this thread's own connection (opened lazily by _conn).
        watcher = SessionWatcher(_conn(state))
        last_run = 0
        while not stop.is_set():
            now = int(time.time())
            if now - last_run >= cfg.session_poll_sec:
                try:
                    snap = collect_snapshot()
                    sid = watcher.tick(snap, now)
                    state.active_session_id = sid
                    state.active_interface = snap.interface if snap else None
                    record_heartbeat(_conn(state), "session", now)  # liveness signal
                except Exception:  # noqa: BLE001
                    log.exception("session tick failed")
                last_run = now
            stop.wait(0.5)

    def _retention_loop():
        last_purge = 0
        last_checkpoint = 0
        while not stop.is_set():
            now = int(time.time())
            # Checkpoint the WAL hourly so it can't grow unbounded between the
            # daily purges under the four writer threads.
            if now - last_checkpoint >= 3600:
                try:
                    wal_checkpoint(_conn(state))
                except Exception:  # noqa: BLE001
                    log.exception("wal checkpoint failed")
                last_checkpoint = now
            if now - last_purge >= 86400:
                try:
                    purge_old(
                        _conn(state),
                        now=now,
                        sample_retention_sec=cfg.retention_days * 86400,
                        dns_retention_sec=cfg.dns_cache_retention_days * 86400,
                    )
                    vacuum(_conn(state))
                except Exception:  # noqa: BLE001
                    log.exception("retention tick failed")
                last_purge = now
            stop.wait(60)

    threads = [
        threading.Thread(target=_session_loop, name="session"),
        threading.Thread(target=_loop, args=(cfg.interface_poll_sec, run_interface_tick, "iface"), name="iface"),
        threading.Thread(target=_loop, args=(cfg.process_poll_sec, run_process_tick, "proc"), name="proc"),
        threading.Thread(target=_loop, args=(cfg.connection_poll_sec, run_connection_tick, "conn"), name="conn"),
        threading.Thread(target=_retention_loop, name="retain"),
    ]
    for t in threads:
        t.start()

    stop.wait()
    log.info("shutdown: joining threads")
    for t in threads:
        t.join(timeout=5)

    # Close the active session using a fresh short-lived connection.
    if state.active_session_id is not None:
        from appband.db import close_session
        shutdown_conn = sqlite3.connect(str(cfg.db_path), isolation_level=None, timeout=10.0)
        shutdown_conn.execute("PRAGMA journal_mode=WAL")
        close_session(shutdown_conn, state.active_session_id, ended_at=int(time.time()))
        shutdown_conn.close()

    # Cancel all pending tasks in the DNS loop before stopping it.
    def _cancel_and_stop():
        for task in asyncio.all_tasks(loop):
            task.cancel()
        loop.stop()

    loop.call_soon_threadsafe(_cancel_and_stop)
    log.info("appband collector exited cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
