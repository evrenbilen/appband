"""appband HTTP server: localhost-only JSON API + static dashboard."""
from __future__ import annotations

import ipaddress
import json
import logging
import logging.handlers
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from appband import __version__
from appband.config import load_config

log = logging.getLogger("appband.server")
WEB_ROOT = Path(__file__).parent / "web"

# The frequent collector pollers that must ALL be reporting for a healthy
# status — a present+fresh fast poller must not mask a dead slow one.
EXPECTED_POLLERS = ("session", "iface", "proc", "conn")
# A poller is stale after ~4 missed cycles of the slowest (conn = 30s) poller.
HEARTBEAT_STALE_SEC = 120


def _is_loopback_name(name: str | None) -> bool:
    """True if a hostname refers to the local machine (127.0.0.0/8, ::1, localhost)."""
    if not name:
        return False
    if name.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _qint(qs: dict, key: str, default: int) -> int:
    val = qs.get(key, [None])[0]
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


class NetmonServer(ThreadingHTTPServer):
    daemon_threads = True


def build_handler(db_path: Path) -> type:
    """Return a handler class that opens a fresh DB connection per request."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # suppress noisy stderr; file log captures activity

        # Locked-down CSP: the dashboard makes zero external requests (Chart.js
        # is self-hosted under /static/vendor/). 'unsafe-inline' is needed only
        # for style attributes in the markup; scripts are 'self' only.
        _CSP = (
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )

        def _security_headers(self) -> None:
            self.send_header("Content-Security-Policy", self._CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")

        def _json(self, payload, status=200):
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self._security_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, msg):
            self._json({"error": msg}, status=status)

        def _static(self, filename: str):
            path = WEB_ROOT / filename
            if not path.exists() or not path.is_file():
                self._error(404, "not found")
                return
            data = path.read_bytes()
            ext = path.suffix.lower()
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
            }.get(ext, "application/octet-stream")
            self.send_response(200)
            self._security_headers()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            # DNS-rebinding / cross-origin defense. Binding 127.0.0.1 does not
            # stop a malicious page the user has open from rebinding its domain
            # to 127.0.0.1 and reading this unauthenticated API. Require the
            # Host (and any Origin) to resolve to loopback.
            host_name = urlparse("//" + (self.headers.get("Host") or "")).hostname
            if not _is_loopback_name(host_name):
                self._error(403, "forbidden: non-loopback Host header")
                return
            origin = self.headers.get("Origin")
            if origin is not None and not _is_loopback_name(urlparse(origin).hostname):
                self._error(403, "forbidden: cross-origin request")
                return

            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            path = parsed.path

            if path == "/":
                self._static("index.html")
                return
            if path.startswith("/static/"):
                self._static(path[len("/static/"):])
                return
            if path == "/api/version":
                self._json({"version": __version__})
                return

            now = int(time.time())
            from_ts = _qint(qs, "from", now - 86400)
            to_ts = _qint(qs, "to", now)

            conn = sqlite3.connect(str(db_path), timeout=10.0, check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                if path == "/api/current":
                    self._json(self._current(conn, now))
                elif path == "/api/health":
                    self._json(self._health(conn, now))
                elif path == "/api/sessions":
                    self._json({"sessions": self._sessions(conn, from_ts, to_ts)})
                elif path == "/api/timeseries":
                    from appband.db import query_timeseries
                    gran = qs.get("granularity", ["hour"])[0]
                    self._json({"timeseries": query_timeseries(conn, from_ts, to_ts, gran)})
                elif path == "/api/by-network":
                    self._json({"rows": self._by_network(conn, from_ts, to_ts)})
                elif path == "/api/by-process":
                    limit = _qint(qs, "limit", 20)
                    scope = qs.get("scope", ["internet"])[0]
                    self._json({"rows": self._by_process(conn, from_ts, to_ts, limit, scope)})
                elif path == "/api/by-domain":
                    limit = _qint(qs, "limit", 50)
                    scope = qs.get("scope", ["internet"])[0]
                    self._json({"rows": self._by_domain(conn, from_ts, to_ts, limit, scope)})
                else:
                    self._error(404, "not found")
            except Exception as e:  # noqa: BLE001
                log.exception("handler error")
                self._error(500, str(e))
            finally:
                conn.close()

        def _health(self, conn: sqlite3.Connection, now: int) -> dict:
            from appband.db import get_health
            raw = get_health(conn)
            # Age (seconds) since each poller last reported success.
            pollers = {p: now - ts for p, ts in raw.items()}
            missing = [p for p in EXPECTED_POLLERS if p not in raw]
            if not raw:
                status = "down"                       # collector never ran / dead
            elif missing or max(pollers.values()) > HEARTBEAT_STALE_SEC:
                status = "degraded"                   # a poller is missing or stale
            else:
                status = "ok"
            return {"status": status, "pollers": pollers, "missing": missing}

        def _current(self, conn: sqlite3.Connection, now: int) -> dict:
            cur = conn.execute(
                "SELECT id, started_at, interface, link_type, ssid, ip_address "
                "FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC, id DESC LIMIT 1"
            )
            row = cur.fetchone()
            session = None
            if row:
                session = dict(zip(
                    ["id", "started_at", "interface", "link_type", "ssid", "ip_address"],
                    row,
                ))
            cur = conn.execute(
                "SELECT COALESCE(SUM(bytes_in), 0), COALESCE(SUM(bytes_out), 0) "
                "FROM interface_samples WHERE ts >= ?",
                (now - 60,),
            )
            bi, bo = cur.fetchone()
            # Exact (not approximate) per-app usage over the last 60s — the live
            # "what is eating my bandwidth right now" view. process_samples bytes
            # are exact; this needs no scope distribution.
            cur = conn.execute(
                "SELECT process_name, COALESCE(SUM(bytes_in), 0), COALESCE(SUM(bytes_out), 0) "
                "FROM process_samples WHERE ts >= ? "
                "GROUP BY process_name "
                "ORDER BY SUM(bytes_in) + SUM(bytes_out) DESC LIMIT 5",
                (now - 60,),
            )
            top_apps = [
                {"process_name": r[0], "bytes_in": r[1], "bytes_out": r[2]}
                for r in cur.fetchall()
            ]
            # Coverage: how much of the exact interface total we attributed to
            # processes. nettop's per-process external bytes never sum to the
            # route total (kernel/system traffic, sampling gaps), so surface the
            # gap instead of letting users conclude the per-app numbers "lie".
            cur = conn.execute(
                "SELECT COALESCE(SUM(bytes_in), 0) + COALESCE(SUM(bytes_out), 0) "
                "FROM process_samples WHERE ts >= ?",
                (now - 60,),
            )
            attributed = cur.fetchone()[0]
            total = (bi or 0) + (bo or 0)
            coverage = {
                "total_bytes": total,
                "attributed_bytes": attributed,
                "pct": round(attributed / total * 100) if total > 0 else None,
            }
            return {
                "session": session,
                "bytes_in_60s": bi,
                "bytes_out_60s": bo,
                "top_apps": top_apps,
                "coverage": coverage,
            }

        def _sessions(self, conn: sqlite3.Connection, from_ts: int, to_ts: int) -> list[dict]:
            cur = conn.execute(
                "SELECT id, started_at, ended_at, interface, link_type, ssid, ip_address "
                "FROM sessions WHERE started_at < ? AND (ended_at IS NULL OR ended_at >= ?) "
                "ORDER BY started_at DESC",
                (to_ts, from_ts),
            )
            keys = ["id", "started_at", "ended_at", "interface", "link_type", "ssid", "ip_address"]
            return [dict(zip(keys, r)) for r in cur.fetchall()]

        def _by_network(self, conn: sqlite3.Connection, from_ts: int, to_ts: int) -> list[dict]:
            cur = conn.execute(
                """
                SELECT s.link_type, COALESCE(s.ssid, ''),
                       SUM(i.bytes_in), SUM(i.bytes_out)
                  FROM interface_samples i
                  JOIN sessions s ON s.id = i.session_id
                 WHERE i.ts >= ? AND i.ts < ?
                 GROUP BY s.link_type, s.ssid
                 ORDER BY SUM(i.bytes_in) + SUM(i.bytes_out) DESC
                """,
                (from_ts, to_ts),
            )
            return [
                {"link_type": r[0], "ssid": r[1] or None, "bytes_in": r[2] or 0, "bytes_out": r[3] or 0}
                for r in cur.fetchall()
            ]

        def _by_process(self, conn: sqlite3.Connection, from_ts: int, to_ts: int, limit: int, scope: str = "internet") -> list[dict]:
            if scope == "all":
                cur = conn.execute(
                    """
                    SELECT process_name, SUM(bytes_in), SUM(bytes_out)
                      FROM process_samples
                     WHERE ts >= ? AND ts < ?
                     GROUP BY process_name
                     ORDER BY SUM(bytes_in) + SUM(bytes_out) DESC
                     LIMIT ?
                    """,
                    (from_ts, to_ts, limit),
                )
                return [{"process_name": r[0], "bytes_in": r[1] or 0, "bytes_out": r[2] or 0, "approximate": False} for r in cur.fetchall()]

            BUCKET = 300
            cur = conn.execute(
                f"""
                WITH proc_buckets AS (
                  SELECT process_name, (ts / {BUCKET}) * {BUCKET} AS bucket,
                         SUM(bytes_in) AS bin, SUM(bytes_out) AS bout
                    FROM process_samples
                   WHERE ts >= ? AND ts < ?
                   GROUP BY process_name, bucket
                ),
                conn_buckets AS (
                  SELECT process_name, (ts / {BUCKET}) * {BUCKET} AS bucket,
                         SUM(CASE WHEN scope = ? THEN 1 ELSE 0 END) AS matching,
                         SUM(CASE WHEN scope IS NOT NULL THEN 1 ELSE 0 END) AS total
                    FROM connections
                   WHERE ts >= ? AND ts < ?
                   GROUP BY process_name, bucket
                ),
                shares AS (
                  SELECT process_name, bucket,
                         CASE WHEN total > 0 THEN (matching * 1.0 / total) ELSE 0 END AS share
                    FROM conn_buckets
                )
                SELECT pb.process_name,
                       CAST(SUM(pb.bin  * COALESCE(s.share, 0)) AS INTEGER) AS bytes_in,
                       CAST(SUM(pb.bout * COALESCE(s.share, 0)) AS INTEGER) AS bytes_out
                  FROM proc_buckets pb
             LEFT JOIN shares s USING (process_name, bucket)
                 GROUP BY pb.process_name
                HAVING SUM(pb.bin * COALESCE(s.share, 0)) + SUM(pb.bout * COALESCE(s.share, 0)) > 0
                 ORDER BY bytes_in + bytes_out DESC
                 LIMIT ?
                """,
                (from_ts, to_ts, scope, from_ts, to_ts, limit),
            )
            return [{"process_name": r[0], "bytes_in": r[1] or 0, "bytes_out": r[2] or 0, "approximate": True} for r in cur.fetchall()]

        def _by_domain(self, conn: sqlite3.Connection, from_ts: int, to_ts: int, limit: int, scope: str = "internet") -> list[dict]:
            # Distribute each (process, time-bucket) process_samples bytes
            # equally across the distinct remote hostnames the process touched
            # in that bucket. Buckets are 5-minute windows.
            BUCKET = 300
            if scope == "all":
                scope_clause = ""
                scope_params: tuple = ()
            else:
                scope_clause = " AND c.scope = ?"
                scope_params = (scope,)
            cur = conn.execute(
                f"""
                WITH proc_buckets AS (
                  SELECT process_name,
                         (ts / {BUCKET}) * {BUCKET} AS bucket,
                         SUM(bytes_in)  AS bin,
                         SUM(bytes_out) AS bout
                    FROM process_samples
                   WHERE ts >= ? AND ts < ?
                   GROUP BY process_name, bucket
                ),
                conn_buckets AS (
                  SELECT c.process_name,
                         (c.ts / {BUCKET}) * {BUCKET} AS bucket,
                         COALESCE(d.hostname, c.remote_ip) AS host
                    FROM connections c
               LEFT JOIN dns_cache d ON d.ip = c.remote_ip
                   WHERE c.ts >= ? AND c.ts < ?{scope_clause}
                   GROUP BY c.process_name, bucket, host
                ),
                counts AS (
                  SELECT process_name, bucket, COUNT(*) AS host_count
                    FROM conn_buckets
                   GROUP BY process_name, bucket
                )
                SELECT cb.host,
                       SUM(pb.bin  / counts.host_count) AS bytes_in,
                       SUM(pb.bout / counts.host_count) AS bytes_out
                  FROM conn_buckets cb
                  JOIN proc_buckets pb USING (process_name, bucket)
                  JOIN counts       USING (process_name, bucket)
                 GROUP BY cb.host
                 ORDER BY bytes_in + bytes_out DESC
                 LIMIT ?
                """,
                (from_ts, to_ts, from_ts, to_ts, *scope_params, limit),
            )
            return [
                {"host": r[0], "bytes_in": int(r[1] or 0), "bytes_out": int(r[2] or 0), "approximate": True}
                for r in cur.fetchall()
            ]

    return Handler


def main(config_path: Path | None = None) -> int:
    cfg = load_config(config_path)
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        cfg.log_dir / "server.log", maxBytes=5_000_000, backupCount=3
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("appband")
    root.addHandler(handler)
    root.setLevel(cfg.log_level)
    log.info("appband server starting on %s:%d", cfg.bind_host, cfg.port)

    server = NetmonServer((cfg.bind_host, cfg.port), build_handler(cfg.db_path))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("interrupt")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
