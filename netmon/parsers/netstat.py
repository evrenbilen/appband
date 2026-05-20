"""Parse `netstat -ibn` output.

We only care about the per-link row (Network column starts with "<Link#"),
since that row carries the cumulative interface byte counters. Other rows
are per-address aliases and would double-count.

Column layout on macOS (observed):
  With MAC address (11 parts):
    [0] Name  [1] Mtu  [2] Network  [3] Address
    [4] Ipkts [5] Ierrs [6] Ibytes
    [7] Opkts [8] Oerrs [9] Obytes [10] Coll
  Without MAC address (10 parts, e.g. lo0, utun*):
    [0] Name  [1] Mtu  [2] Network
    [3] Ipkts [4] Ierrs [5] Ibytes
    [6] Opkts [7] Oerrs [8] Obytes [9] Coll
"""
from __future__ import annotations


def parse_netstat_ibn(text: str) -> dict[str, dict[str, int]]:
    """Return {iface_name: {'bytes_in': int, 'bytes_out': int}}."""
    result: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("Name"):
            continue
        parts = line.split()
        if len(parts) < 10:
            continue
        name = parts[0]
        network = parts[2]
        if not network.startswith("<Link#"):
            continue
        # Address present  => 11 parts, Ibytes at index 6, Obytes at index 9
        # Address absent   => 10 parts, Ibytes at index 5, Obytes at index 8
        if len(parts) >= 11:
            try:
                ibytes = int(parts[6])
                obytes = int(parts[9])
            except ValueError:
                # fallback: try 10-col layout
                ibytes = int(parts[5])
                obytes = int(parts[8])
        else:
            ibytes = int(parts[5])
            obytes = int(parts[8])
        result[name] = {"bytes_in": ibytes, "bytes_out": obytes}
    return result
