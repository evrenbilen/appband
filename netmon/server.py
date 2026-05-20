"""netmon HTTP server: localhost-only JSON API + static dashboard."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from netmon.config import load_config

log = logging.getLogger("netmon.server")
WEB_ROOT = Path(__file__).parent / "web"


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

        def _json(self, payload, status=200):
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
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
            }.get(ext, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            path = parsed.path

            if path == "/":
                self._static("index.html")
                return
            if path.startswith("/static/"):
                self._static(path[len("/static/"):])
                return

            now = int(time.time())
            from_ts = _qint(qs, "from", now - 86400)
            to_ts = _qint(qs, "to", now)

            conn = sqlite3.connect(str(db_path), timeout=10.0, check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                if path == "/api/current":
                    self._json(self._current(conn, now))
                elif path == "/api/sessions":
                    self._json({"sessions": self._sessions(conn, from_ts, to_ts)})
                elif path == "/api/timeseries":
                    from netmon.db import query_timeseries
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

        def _current(self, conn: sqlite3.Connection, now: int) -> dict:
            cur = conn.execute(
                "SELECT id, started_at, interface, link_type, ssid, ip_address "
                "FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
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
            return {"session": session, "bytes_in_60s": bi, "bytes_out_60s": bo}

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
    handler = logging.FileHandler(cfg.log_dir / "server.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("netmon")
    root.addHandler(handler)
    root.setLevel(cfg.log_level)
    log.info("netmon server starting on %s:%d", cfg.bind_host, cfg.port)

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
