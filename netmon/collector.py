"""netmon collector daemon: orchestrates pollers and writes to SQLite."""
from __future__ import annotations

import asyncio
import logging
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from netmon.config import Config, load_config
from netmon.db import (
    connect,
    insert_connection,
    insert_interface_sample,
    insert_process_sample,
)
from netmon.delta import DeltaTracker
from netmon.dns_cache import DnsResolver
from netmon.parsers.lsof import parse_lsof_connections
from netmon.parsers.netstat import parse_netstat_ibn
from netmon.parsers.nettop import parse_nettop
from netmon.retention import purge_old, vacuum
from netmon.session_watcher import SessionWatcher, collect_snapshot

log = logging.getLogger("netmon.collector")


@dataclass
class CollectorState:
    conn: object
    iface_tracker: DeltaTracker
    proc_in_tracker: DeltaTracker
    proc_out_tracker: DeltaTracker
    active_interface: str | None
    active_session_id: int | None
    dns_enqueue: Callable[[str], None]


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
    text = _run(["/usr/sbin/netstat", "-ibn"])
    stats = parse_netstat_ibn(text)
    iface = state.active_interface
    if not iface or iface not in stats:
        return
    s = stats[iface]
    delta_in = state.iface_tracker.update(iface + ":in", s["bytes_in"], now)
    delta_out = state.iface_tracker.update(iface + ":out", s["bytes_out"], now)
    if delta_in is None or delta_out is None:
        return
    if state.active_session_id is None:
        return
    insert_interface_sample(
        state.conn,
        ts=now,
        session_id=state.active_session_id,
        bytes_in=delta_in,
        bytes_out=delta_out,
    )


def run_process_tick(state: CollectorState, now: int) -> None:
    text = _run(["/usr/bin/nettop", "-P", "-x", "-L", "1", "-J", "bytes_in,bytes_out"])
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
            state.conn,
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
            state.conn,
            ts=now,
            session_id=state.active_session_id,
            process_name=r["process_name"],
            remote_ip=r["remote_ip"],
            remote_port=r["remote_port"],
            protocol=r["protocol"],
        )
        state.dns_enqueue(r["remote_ip"])


def _setup_logging(cfg: Config) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(cfg.log_dir / "collector.log")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(threadName)s %(message)s")
    )
    root = logging.getLogger("netmon")
    root.addHandler(handler)
    root.setLevel(cfg.log_level)


def main(config_path: Path | None = None) -> int:
    cfg = load_config(config_path)
    _setup_logging(cfg)
    log.info("netmon collector starting")

    conn = connect(cfg.db_path)
    watcher = SessionWatcher(conn)
    state = CollectorState(
        conn=conn,
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
    resolver = DnsResolver(
        conn=conn,
        timeout=cfg.dns_lookup_timeout_sec,
        concurrency=cfg.dns_concurrency,
    )

    def _enqueue(ip: str) -> None:
        loop.call_soon_threadsafe(resolver.queue.put_nowait, ip)

    state.dns_enqueue = _enqueue

    def _loop_runner():
        asyncio.set_event_loop(loop)
        loop.create_task(resolver.run_forever())
        loop.run_forever()

    threading.Thread(target=_loop_runner, name="dns", daemon=True).start()

    def _loop(interval: int, fn, name: str):
        last_run = 0
        while not stop.is_set():
            now = int(time.time())
            if now - last_run >= interval:
                try:
                    fn(state, now)
                except Exception:  # noqa: BLE001
                    log.exception("%s tick failed", name)
                last_run = now
            stop.wait(0.5)

    def _session_loop():
        last_run = 0
        while not stop.is_set():
            now = int(time.time())
            if now - last_run >= cfg.session_poll_sec:
                try:
                    snap = collect_snapshot()
                    sid = watcher.tick(snap, now)
                    state.active_session_id = sid
                    state.active_interface = snap.interface if snap else None
                except Exception:  # noqa: BLE001
                    log.exception("session tick failed")
                last_run = now
            stop.wait(0.5)

    def _retention_loop():
        last_run = 0
        while not stop.is_set():
            now = int(time.time())
            if now - last_run >= 86400:
                try:
                    purge_old(
                        conn,
                        now=now,
                        sample_retention_sec=cfg.retention_days * 86400,
                        dns_retention_sec=cfg.dns_cache_retention_days * 86400,
                    )
                    vacuum(conn)
                except Exception:  # noqa: BLE001
                    log.exception("retention tick failed")
                last_run = now
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

    if state.active_session_id is not None:
        from netmon.db import close_session
        close_session(conn, state.active_session_id, ended_at=int(time.time()))

    # Cancel all pending tasks in the DNS loop before stopping it
    def _cancel_and_stop():
        for task in asyncio.all_tasks(loop):
            task.cancel()
        loop.stop()

    loop.call_soon_threadsafe(_cancel_and_stop)
    conn.close()
    log.info("netmon collector exited cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
