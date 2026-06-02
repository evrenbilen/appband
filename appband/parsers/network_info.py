"""Parse network identity output: route, networksetup, ifconfig.

Provides four focused parsers used by session_watcher.
"""
from __future__ import annotations

import ipaddress
import re

_HOTSPOT_PATTERNS = (
    re.compile(r"\biphone\b", re.IGNORECASE),
    re.compile(r"\bandroid\b", re.IGNORECASE),
    re.compile(r"\bsamsung\b", re.IGNORECASE),
    re.compile(r"\bgalaxy\b", re.IGNORECASE),
)

# iPhone Personal Hotspot always hands its clients an address in 172.20.10.0/28
# (gateway .1, clients .2-.14) — over WiFi, USB, or Bluetooth alike. This is a
# fixed Apple range and the only reliable hotspot signal on modern macOS, where
# `ipconfig getsummary` redacts the SSID from the headless collector daemon
# (no Location Services grant), so the name-pattern heuristic can't fire.
_IPHONE_HOTSPOT_NET = ipaddress.ip_network("172.20.10.0/28")


def _is_iphone_hotspot_ip(ip: str | None) -> bool:
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip) in _IPHONE_HOTSPOT_NET
    except ValueError:
        return False


def parse_default_interface(text: str) -> str | None:
    """Extract `interface:` line from `route -n get default`."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("interface:"):
            return line.split(":", 1)[1].strip()
    return None


def parse_airport_ssid(text: str) -> str | None:
    """Extract SSID from `networksetup -getairportnetwork <iface>`."""
    text = text.strip()
    if "not associated" in text.lower():
        return None
    prefix = "Current Wi-Fi Network: "
    if text.startswith(prefix):
        return text[len(prefix):].strip() or None
    return None


def parse_ifconfig(text: str) -> dict:
    """Extract inet/ether/media/status from `ifconfig <iface>` output."""
    result = {"ip_address": None, "mac": None, "media": None, "status": None}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("ether "):
            result["mac"] = line.split()[1]
        elif line.startswith("inet ") and not line.startswith("inet6"):
            result["ip_address"] = line.split()[1]
        elif line.startswith("media:"):
            result["media"] = line.split(":", 1)[1].strip()
        elif line.startswith("status:"):
            result["status"] = line.split(":", 1)[1].strip()
    return result


def parse_ipconfig_summary(text: str) -> dict:
    """Extract SSID + InterfaceType from `ipconfig getsummary <iface>` output.

    macOS Sonoma+ exposes the real SSID here. `networksetup -getairportnetwork`
    is unreliable on modern macOS (returns "not associated" even when up).
    """
    result = {"ssid": None, "interface_type": None}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("SSID : "):
            value = s[len("SSID : "):].strip()
            if value and value.lower() != "<redacted>":
                result["ssid"] = value
        elif s.startswith("InterfaceType : "):
            result["interface_type"] = s[len("InterfaceType : "):].strip()
    return result


def classify_link_type(
    interface: str,
    ssid: str | None,
    media: str | None,
    interface_type: str | None = None,
    ip_address: str | None = None,
) -> str:
    """Map (interface, ssid, media, interface_type, ip_address) -> link_type tag."""
    # A VPN/tunnel default route (utun/ipsec/ppp) takes precedence: traffic
    # goes through the tunnel regardless of the underlying physical link.
    if interface.startswith(("utun", "ipsec", "ppp")):
        return "vpn"
    # iPhone Personal Hotspot's fixed 172.20.10.0/28 range is the reliable
    # signal on modern macOS, where the SSID is redacted from the daemon (so the
    # name-pattern check below can't catch it). More specific than wifi/USB.
    if _is_iphone_hotspot_ip(ip_address):
        return "iphone-hotspot"
    is_wifi = bool(interface_type and "wifi" in interface_type.lower())
    if is_wifi or ssid:
        if ssid:
            for pat in _HOTSPOT_PATTERNS:
                if pat.search(ssid):
                    return "iphone-hotspot"
        return "wifi"
    if media and "USB" in media:
        return "usb-tether"
    return "ethernet"
