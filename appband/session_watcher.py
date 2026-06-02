"""Detect active network identity and manage session rows."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from appband.db import close_session, get_active_session, open_session
from appband.parsers.network_info import (
    classify_link_type,
    parse_default_interface,
    parse_ifconfig,
    parse_ipconfig_summary,
)

log = logging.getLogger("appband.session")


@dataclass(frozen=True)
class NetworkSnapshot:
    interface: str
    link_type: str
    ssid: str | None
    bssid: str | None
    ip_address: str | None

    def identity(self) -> tuple:
        return (self.interface, self.link_type, self.ssid, self.bssid)


# Tools reported missing (FileNotFoundError) — logged once each, not per tick.
# Persists for the daemon's lifetime; a reinstalled tool isn't noticed until
# restart (acceptable trade-off vs log spam). Mirrors collector._run.
_missing_tools: set[str] = set()


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout
    except FileNotFoundError:
        tool = cmd[0]
        if tool not in _missing_tools:
            _missing_tools.add(tool)
            log.error("required tool not found: %s — is it available on this macOS?", tool)
        return ""
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("subprocess failed: %s: %s", cmd, e)
        return ""


def collect_snapshot() -> NetworkSnapshot | None:
    """Run system commands and build a NetworkSnapshot, or None if offline."""
    iface = parse_default_interface(_run(["/sbin/route", "-n", "get", "default"]))
    if not iface:
        return None
    summary = parse_ipconfig_summary(_run(["/usr/sbin/ipconfig", "getsummary", iface]))
    ifc = parse_ifconfig(_run(["/sbin/ifconfig", iface]))
    link_type = classify_link_type(
        interface=iface,
        ssid=summary["ssid"],
        media=ifc.get("media") or "",
        interface_type=summary["interface_type"],
        ip_address=ifc.get("ip_address"),
    )
    return NetworkSnapshot(
        interface=iface,
        link_type=link_type,
        ssid=summary["ssid"],
        bssid=None,  # BSSID requires system_profiler; skipped for v1
        ip_address=ifc.get("ip_address"),
    )


class SessionWatcher:
    """Owns the current session row; opens/closes as the network changes."""

    def __init__(self, conn):
        self.conn = conn
        self._current_id: int | None = None
        self._current_identity: tuple | None = None
        # Recover state if collector restarts mid-session
        active = get_active_session(conn)
        if active:
            self._current_id = active["id"]
            self._current_identity = (
                active["interface"],
                active["link_type"],
                active["ssid"],
                active["bssid"],
            )

    def tick(self, snapshot: NetworkSnapshot | None, now: int) -> int | None:
        """Reconcile DB state with the current snapshot; return active session_id."""
        if snapshot is None:
            if self._current_id is not None:
                close_session(self.conn, self._current_id, ended_at=now)
                log.info("Session %d closed (offline)", self._current_id)
                self._current_id = None
                self._current_identity = None
            return None

        if snapshot.identity() == self._current_identity:
            return self._current_id

        # Network changed
        if self._current_id is not None:
            close_session(self.conn, self._current_id, ended_at=now)
            log.info("Session %d closed (network change)", self._current_id)

        self._current_id = open_session(
            self.conn,
            started_at=now,
            interface=snapshot.interface,
            link_type=snapshot.link_type,
            ssid=snapshot.ssid,
            bssid=snapshot.bssid,
            ip_address=snapshot.ip_address,
        )
        self._current_identity = snapshot.identity()
        log.info(
            "Session %d opened: iface=%s type=%s ssid=%s",
            self._current_id,
            snapshot.interface,
            snapshot.link_type,
            snapshot.ssid,
        )
        return self._current_id
