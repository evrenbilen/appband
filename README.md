# netmon

macOS network usage monitor. Logs when/where/what/how-much/to-where, with a local web dashboard. Stdlib Python 3 only — no `pip install`.

## What it tracks

- Active network (interface + SSID/hotspot name + link type: wifi / iphone-hotspot / usb-tether / ethernet)
- Bytes in/out per 5 seconds (interface level)
- Bytes in/out per process per 10 seconds (via `nettop`)
- Active outbound connections per 30 seconds (via `lsof`), with reverse-DNS caching
- 30 days of history, auto-purged

## Install

```bash
git clone <this-repo> ~/Development/Personal/netmon
cd ~/Development/Personal/netmon
./scripts/install.sh
```

Opens http://127.0.0.1:8765/ in your default browser.

## Uninstall

```bash
./scripts/uninstall.sh           # keep data
./scripts/uninstall.sh --purge   # also delete DB
```

## Status

```bash
./scripts/status.sh
```

## Storage

- DB:   `~/Library/Application Support/netmon/netmon.db` (SQLite, WAL)
- Logs: `~/Library/Logs/netmon/{collector,server}.log`

## Tests

```bash
python3 -m unittest discover tests -v
```

## Caveats

- Domain-level numbers are **approximate**. `lsof` reports active connections, not bytes-per-connection. The dashboard distributes per-process bytes across the hostnames that process was talking to in the same 5-minute window. Treat the domain panel as "where the traffic probably went," not as exact accounting.
- No packet capture (`tcpdump`) is used. VPN tunnels appear as a single endpoint.
- macOS sleep/wake can produce sample gaps; counters are reset on discontinuity to avoid spikes.
