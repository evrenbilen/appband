"""Parse `lsof -i -nP -P` output.

We keep rows whose NAME column contains "->", indicating an outbound
connection with a remote endpoint. LISTEN-only rows (no arrow) are
dropped. Loopback (127.0.0.0/8, ::1) and link-local (169.254.0.0/16,
fe80::/10) destinations are dropped.

macOS lsof column layout (space-delimited, 9 columns before NAME):
  COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME

The DEVICE value is a hex address that never contains spaces, so a
simple split() reliably yields NAME at index 8 onward.
"""
from __future__ import annotations


def _classify_scope(ip: str) -> str:
    """Return 'internet' or 'lan' for a non-loopback/non-linklocal IP."""
    # IPv4 RFC1918
    if ip.startswith("10."):
        return "lan"
    if ip.startswith("192.168."):
        return "lan"
    if ip.startswith("172."):
        # 172.16.0.0/12 -> 172.16.x.x through 172.31.x.x
        try:
            second = int(ip.split(".")[1])
        except (ValueError, IndexError):
            return "internet"
        if 16 <= second <= 31:
            return "lan"
    # IPv6 unique-local fc00::/7
    if ip.lower().startswith("fc") or ip.lower().startswith("fd"):
        return "lan"
    return "internet"


def _is_excluded(ip: str) -> bool:
    if ip.startswith("127.") or ip == "::1":
        return True
    if ip.startswith("169.254."):
        return True
    if ip.lower().startswith("fe80"):
        return True
    return False


def _strip_zone(ip: str) -> str:
    """Drop an IPv6 zone id ('fe80::1%en0' -> 'fe80::1') so the bare address is
    what gets stored, classified, and reverse-resolved."""
    return ip.split("%", 1)[0]


def _split_endpoint(token: str) -> tuple[str, int | None]:
    """Parse an lsof endpoint into (ip, port).

    macOS lsof brackets IPv6 when a port is present ('[2606:4700::1]:443');
    IPv4 is 'host:port'. A bare, unbracketed IPv6 has multiple colons and no
    port (lsof would have bracketed it otherwise), so it must NOT be split on
    the last colon. IPv6 zone ids ('%en0') are stripped.
    """
    if token.startswith("["):
        end = token.index("]")
        ip = _strip_zone(token[1:end])
        rest = token[end + 1:]
        if rest.startswith(":"):
            try:
                return ip, int(rest[1:])
            except ValueError:
                return ip, None
        return ip, None
    # A single colon is host:port; multiple colons is a bare IPv6 address.
    if token.count(":") == 1:
        ip, _, port = token.rpartition(":")
        try:
            return _strip_zone(ip), int(port)
        except ValueError:
            return _strip_zone(ip), None
    return _strip_zone(token), None


def parse_lsof_connections(text: str) -> list[dict]:
    """Return a list of dicts with process/pid/remote_ip/remote_port/protocol."""
    rows: list[dict] = []
    for line in text.splitlines():
        if not line or line.startswith("COMMAND"):
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        proto = parts[7].lower()
        if proto not in ("tcp", "udp"):
            continue
        name_field = " ".join(parts[8:])
        # strip trailing state like "(ESTABLISHED)"
        if "(" in name_field:
            name_field = name_field[: name_field.index("(")].strip()
        if "->" not in name_field:
            continue
        local, _, remote = name_field.partition("->")
        remote_ip, remote_port = _split_endpoint(remote.strip())
        if _is_excluded(remote_ip):
            continue
        process_name = parts[0]
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        rows.append(
            {
                "process_name": process_name,
                "pid": pid,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "protocol": proto,
                "scope": _classify_scope(remote_ip),
            }
        )
    return rows
