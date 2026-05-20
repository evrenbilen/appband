"""Parse network identity output: route, networksetup, ifconfig.

Provides four focused parsers used by session_watcher.
"""
from __future__ import annotations

import re

_HOTSPOT_PATTERNS = (
    re.compile(r"\biphone\b", re.IGNORECASE),
    re.compile(r"\bandroid\b", re.IGNORECASE),
    re.compile(r"\bsamsung\b", re.IGNORECASE),
    re.compile(r"\bgalaxy\b", re.IGNORECASE),
)


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


def classify_link_type(interface: str, ssid: str | None, media: str | None) -> str:
    """Map (interface, ssid, media) -> link_type tag."""
    if ssid:
        for pat in _HOTSPOT_PATTERNS:
            if pat.search(ssid):
                return "iphone-hotspot"
        return "wifi"
    if media and "USB" in media:
        return "usb-tether"
    return "ethernet"
