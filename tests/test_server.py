import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from contextlib import closing
from pathlib import Path

from appband.db import init_schema, open_session, insert_interface_sample, insert_process_sample, insert_connection, record_heartbeat, upsert_dns
from appband.server import build_handler, NetmonServer


class ServerTest(unittest.TestCase):
    def setUp(self):
        # Use an on-disk temp DB so the per-request connections opened by the
        # server can access the same data (`:memory:` is not sharable across
        # connections).
        fd, db_file = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_file = db_file
        self.db_path = Path(db_file)

        # Seed the DB via a setup connection, then close it before the server
        # starts so WAL mode doesn't conflict.
        setup_conn = sqlite3.connect(db_file)
        init_schema(setup_conn)
        sid = open_session(setup_conn, 1000, "en0", "wifi", "Office", None, "192.168.1.42")
        for ts in range(1000, 1060):
            insert_interface_sample(setup_conn, ts=ts, session_id=sid, bytes_in=100, bytes_out=20)
        setup_conn.commit()
        setup_conn.close()

        handler = build_handler(self.db_path)
        self.server = NetmonServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        # Remove temp DB and any WAL/SHM sidecar files.
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.db_file + suffix)
            except FileNotFoundError:
                pass

    def _get(self, path: str) -> tuple[int, dict]:
        with closing(urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=2)) as resp:
            return resp.status, json.loads(resp.read())

    def _raw_get(self, path: str, headers: dict | None = None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
        with closing(urllib.request.urlopen(req, timeout=2)) as resp:
            return resp.status, resp.headers, resp.read()

    def test_current_returns_active_session(self):
        status, body = self._get("/api/current")
        self.assertEqual(status, 200)
        self.assertEqual(body["session"]["ssid"], "Office")
        self.assertIn("bytes_in_60s", body)
        self.assertIn("bytes_out_60s", body)

    def test_current_includes_exact_top_apps(self):
        # The headline live view: top apps by exact process_samples bytes over
        # the last 60s, ranked by total, no approximation.
        now = int(time.time())
        setup = sqlite3.connect(self.db_file)
        init_schema(setup)
        sid = setup.execute("SELECT id FROM sessions WHERE ended_at IS NULL LIMIT 1").fetchone()[0]
        insert_process_sample(setup, ts=now - 5, session_id=sid, process_name="Safari", pid=1, bytes_in=900, bytes_out=100)
        insert_process_sample(setup, ts=now - 5, session_id=sid, process_name="Mail", pid=2, bytes_in=40, bytes_out=10)
        setup.commit()
        setup.close()
        status, body = self._get("/api/current")
        self.assertEqual(status, 200)
        self.assertIn("top_apps", body)
        self.assertEqual(body["top_apps"][0]["process_name"], "Safari")
        self.assertEqual(body["top_apps"][0]["bytes_in"], 900)
        self.assertEqual(body["top_apps"][0]["bytes_out"], 100)
        names = [a["process_name"] for a in body["top_apps"]]
        self.assertEqual(names, ["Safari", "Mail"])  # ranked by total desc

    def test_current_includes_coverage(self):
        # Coverage = how much of the exact interface total we attributed to
        # processes, so users understand why per-app sums < the headline total.
        now = int(time.time())
        setup = sqlite3.connect(self.db_file)
        init_schema(setup)
        sid = setup.execute("SELECT id FROM sessions WHERE ended_at IS NULL LIMIT 1").fetchone()[0]
        insert_interface_sample(setup, ts=now - 5, session_id=sid, bytes_in=600, bytes_out=400)  # total 1000
        insert_process_sample(setup, ts=now - 5, session_id=sid, process_name="Safari", pid=1, bytes_in=500, bytes_out=300)  # total 800
        setup.commit()
        setup.close()
        status, body = self._get("/api/current")
        self.assertEqual(status, 200)
        self.assertIn("coverage", body)
        self.assertEqual(body["coverage"]["total_bytes"], 1000)
        self.assertEqual(body["coverage"]["attributed_bytes"], 800)
        self.assertEqual(body["coverage"]["pct"], 80)

    def test_sessions_lists_with_default_range(self):
        status, body = self._get("/api/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["sessions"]), 1)
        self.assertEqual(body["sessions"][0]["ssid"], "Office")

    def test_unknown_route_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/nonexistent")
        self.assertEqual(ctx.exception.code, 404)

    def test_timeseries(self):
        status, body = self._get("/api/timeseries?from=0&to=10000&granularity=hour")
        self.assertEqual(status, 200)
        self.assertIn("timeseries", body)

    def test_by_network(self):
        status, body = self._get("/api/by-network?from=0&to=10000")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(body["rows"][0]["ssid"], "Office")

    def test_by_process_empty(self):
        status, body = self._get("/api/by-process?from=0&to=10000")
        self.assertEqual(status, 200)
        self.assertEqual(body["rows"], [])

    def test_by_domain_empty(self):
        status, body = self._get("/api/by-domain?from=0&to=10000")
        self.assertEqual(status, 200)
        self.assertEqual(body["rows"], [])

    def test_by_process_scope_internet_excludes_lan_only(self):
        # Add process samples and connections with mixed scopes via a second setup connection.
        # Use ts=500 so it falls in range from=0&to=10000.
        setup_conn = sqlite3.connect(self.db_file)
        init_schema(setup_conn)
        # Re-fetch the session id (created in setUp)
        row = setup_conn.execute("SELECT id FROM sessions WHERE ended_at IS NULL LIMIT 1").fetchone()
        sid = row[0]
        # ProcA: internet traffic
        insert_process_sample(setup_conn, ts=500, session_id=sid, process_name="ProcA", pid=100, bytes_in=1000, bytes_out=200)
        insert_connection(setup_conn, ts=500, session_id=sid, process_name="ProcA", remote_ip="8.8.8.8", remote_port=443, protocol="tcp", scope="internet")
        # ProcB: LAN-only traffic
        insert_process_sample(setup_conn, ts=500, session_id=sid, process_name="ProcB", pid=200, bytes_in=500, bytes_out=100)
        insert_connection(setup_conn, ts=500, session_id=sid, process_name="ProcB", remote_ip="192.168.1.1", remote_port=80, protocol="tcp", scope="lan")
        setup_conn.commit()
        setup_conn.close()

        status, body = self._get("/api/by-process?scope=internet&from=0&to=10000")
        self.assertEqual(status, 200)
        names = {r["process_name"] for r in body["rows"]}
        self.assertIn("ProcA", names)
        self.assertNotIn("ProcB", names)

    def test_by_process_scope_lan_excludes_internet_only(self):
        setup_conn = sqlite3.connect(self.db_file)
        init_schema(setup_conn)
        row = setup_conn.execute("SELECT id FROM sessions WHERE ended_at IS NULL LIMIT 1").fetchone()
        sid = row[0]
        insert_process_sample(setup_conn, ts=600, session_id=sid, process_name="ProcC", pid=300, bytes_in=2000, bytes_out=400)
        insert_connection(setup_conn, ts=600, session_id=sid, process_name="ProcC", remote_ip="1.2.3.4", remote_port=443, protocol="tcp", scope="internet")
        insert_process_sample(setup_conn, ts=600, session_id=sid, process_name="ProcD", pid=400, bytes_in=800, bytes_out=150)
        insert_connection(setup_conn, ts=600, session_id=sid, process_name="ProcD", remote_ip="10.0.0.1", remote_port=22, protocol="tcp", scope="lan")
        setup_conn.commit()
        setup_conn.close()

        status, body = self._get("/api/by-process?scope=lan&from=0&to=10000")
        self.assertEqual(status, 200)
        names = {r["process_name"] for r in body["rows"]}
        self.assertIn("ProcD", names)
        self.assertNotIn("ProcC", names)

    # ── Security: DNS-rebinding / cross-origin defense ──────────────────────
    def test_rejects_non_loopback_host_header(self):
        # DNS-rebinding: an attacker page rebinds evil.com -> 127.0.0.1, so the
        # browser connects locally but sends Host: evil.com. Must be refused.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._raw_get("/api/current", {"Host": "evil.com"})
        self.assertEqual(ctx.exception.code, 403)

    def test_rejects_cross_origin_request(self):
        # A page on another origin fetching the local API sends its Origin.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._raw_get("/api/current", {"Origin": "http://evil.com"})
        self.assertEqual(ctx.exception.code, 403)

    def test_allows_loopback_host_and_origin(self):
        status, _, _ = self._raw_get("/api/current", {"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(status, 200)

    def test_security_headers_on_static(self):
        status, headers, _ = self._raw_get("/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'none'", headers.get("Content-Security-Policy", ""))
        self.assertIn("script-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")

    def test_security_headers_on_api(self):
        _, headers, _ = self._raw_get("/api/current")
        self.assertIn("default-src 'none'", headers.get("Content-Security-Policy", ""))
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_api_version(self):
        import appband
        status, body = self._get("/api/version")
        self.assertEqual(status, 200)
        self.assertRegex(body["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(body["version"], appband.__version__)

    def _seed_health(self, **pollers):
        setup = sqlite3.connect(self.db_file)
        init_schema(setup)
        for poller, ts in pollers.items():
            record_heartbeat(setup, poller, ts)
        setup.commit()
        setup.close()

    def test_api_health_ok_when_recent(self):
        now = int(time.time())
        self._seed_health(session=now - 3, iface=now - 4, proc=now - 6, conn=now - 20)
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertIn("iface", body["pollers"])
        self.assertEqual(body["missing"], [])

    def test_api_health_degraded_when_a_poller_is_missing(self):
        # A present+fresh fast poller must not mask dead slow pollers.
        now = int(time.time())
        self._seed_health(session=now - 3, iface=now - 4)  # proc + conn never reported
        _, body = self._get("/api/health")
        self.assertEqual(body["status"], "degraded")
        self.assertIn("proc", body["missing"])
        self.assertIn("conn", body["missing"])

    def test_api_health_degraded_when_stale(self):
        self._seed_health(iface=int(time.time()) - 9999)
        _, body = self._get("/api/health")
        self.assertEqual(body["status"], "degraded")

    def test_api_health_down_when_no_heartbeats(self):
        _, body = self._get("/api/health")
        self.assertEqual(body["status"], "down")

    def test_client_disconnect_does_not_break_server(self):
        # A client that hangs up mid-response must not take the server down or
        # spew tracebacks; subsequent requests still succeed.
        import socket
        s = socket.create_connection(("127.0.0.1", self.port), timeout=2)
        s.sendall(b"GET /api/current HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        s.close()  # disconnect without reading the response
        status, _ = self._get("/api/current")
        self.assertEqual(status, 200)

    def test_chartjs_is_self_hosted(self):
        status, headers, body = self._raw_get("/static/vendor/chart.umd.min.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get("Content-Type", ""))
        self.assertGreater(len(body), 1000)

    def test_dashboard_loads_no_external_scripts(self):
        # A locally-served, CDN-free dashboard is required by both the
        # localhost-only spirit and the strict script-src 'self' CSP.
        _, _, body = self._raw_get("/")
        html = body.decode("utf-8")
        self.assertNotIn("cdn.jsdelivr.net", html)
        self.assertIn("/static/vendor/chart.umd.min.js", html)

    def _seed_two_networks(self):
        setup = sqlite3.connect(self.db_file)
        init_schema(setup)
        office = open_session(setup, 1000, "en0", "wifi", "Office", None, "1.1.1.1")
        guest = open_session(setup, 1000, "en1", "wifi", "Guest", None, "2.2.2.2")
        insert_process_sample(setup, ts=1000, session_id=office, process_name="Safari", pid=1, bytes_in=1000, bytes_out=200)
        insert_connection(setup, ts=1000, session_id=office, process_name="Safari", remote_ip="8.8.8.8", remote_port=443, protocol="tcp", scope="internet")
        insert_process_sample(setup, ts=1000, session_id=guest, process_name="Mail", pid=2, bytes_in=500, bytes_out=100)
        insert_connection(setup, ts=1000, session_id=guest, process_name="Mail", remote_ip="9.9.9.9", remote_port=443, protocol="tcp", scope="internet")
        upsert_dns(setup, ip="8.8.8.8", hostname="google.com", resolved_at=1000)
        upsert_dns(setup, ip="9.9.9.9", hostname="quad9.net", resolved_at=1000)
        setup.commit()
        setup.close()

    def test_by_process_ssid_filter(self):
        self._seed_two_networks()
        _, body = self._get("/api/by-process?from=0&to=10000&scope=internet&ssid=Office")
        names = {r["process_name"] for r in body["rows"]}
        self.assertIn("Safari", names)
        self.assertNotIn("Mail", names)

    def test_by_process_scope_all_ssid_filter(self):
        self._seed_two_networks()
        _, body = self._get("/api/by-process?from=0&to=10000&scope=all&ssid=Guest")
        names = {r["process_name"] for r in body["rows"]}
        self.assertIn("Mail", names)
        self.assertNotIn("Safari", names)

    def test_by_domain_ssid_filter(self):
        self._seed_two_networks()
        _, body = self._get("/api/by-domain?from=0&to=10000&scope=internet&ssid=Office")
        hosts = {r["host"] for r in body["rows"]}
        self.assertIn("google.com", hosts)
        self.assertNotIn("quad9.net", hosts)

    def test_timeseries_ssid_filter_via_api(self):
        # setUp seeds Office interface_samples; Guest (added here) has none, so
        # the ssid param must scope the route's result.
        self._seed_two_networks()
        _, office = self._get("/api/timeseries?from=0&to=10000&granularity=hour&ssid=Office")
        _, guest = self._get("/api/timeseries?from=0&to=10000&granularity=hour&ssid=Guest")
        self.assertGreaterEqual(len(office["timeseries"]), 1)
        self.assertEqual(guest["timeseries"], [])

    def test_by_domain_splits_bytes_equally_across_hosts(self):
        # Load-bearing approximation contract: a process's bytes are split
        # equally across the distinct hosts it touched in the same 5-min bucket.
        setup = sqlite3.connect(self.db_file)
        init_schema(setup)
        sid = setup.execute("SELECT id FROM sessions WHERE ended_at IS NULL LIMIT 1").fetchone()[0]
        insert_process_sample(setup, ts=500, session_id=sid, process_name="P", pid=1, bytes_in=1000, bytes_out=200)
        insert_connection(setup, ts=500, session_id=sid, process_name="P", remote_ip="1.1.1.1", remote_port=443, protocol="tcp", scope="internet")
        insert_connection(setup, ts=500, session_id=sid, process_name="P", remote_ip="2.2.2.2", remote_port=443, protocol="tcp", scope="internet")
        upsert_dns(setup, ip="1.1.1.1", hostname="a.com", resolved_at=500)
        upsert_dns(setup, ip="2.2.2.2", hostname="b.com", resolved_at=500)
        setup.commit()
        setup.close()
        _, body = self._get("/api/by-domain?from=0&to=10000&scope=internet")
        by = {r["host"]: r for r in body["rows"]}
        self.assertEqual(by["a.com"]["bytes_in"], 500)
        self.assertEqual(by["b.com"]["bytes_in"], 500)
        self.assertEqual(by["a.com"]["bytes_out"], 100)
        self.assertEqual(by["b.com"]["bytes_out"], 100)

    def test_by_process_distributes_by_scope_ratio(self):
        # 1000 bytes; 1 internet + 1 lan connection in the bucket → the internet
        # view gets 1000 * (1/2) = 500.
        setup = sqlite3.connect(self.db_file)
        init_schema(setup)
        sid = setup.execute("SELECT id FROM sessions WHERE ended_at IS NULL LIMIT 1").fetchone()[0]
        insert_process_sample(setup, ts=600, session_id=sid, process_name="Q", pid=2, bytes_in=1000, bytes_out=0)
        insert_connection(setup, ts=600, session_id=sid, process_name="Q", remote_ip="8.8.8.8", remote_port=443, protocol="tcp", scope="internet")
        insert_connection(setup, ts=600, session_id=sid, process_name="Q", remote_ip="192.168.1.1", remote_port=80, protocol="tcp", scope="lan")
        setup.commit()
        setup.close()
        _, body = self._get("/api/by-process?from=0&to=10000&scope=internet")
        q = next(r for r in body["rows"] if r["process_name"] == "Q")
        self.assertEqual(q["bytes_in"], 500)

    def test_api_gaps(self):
        from appband.db import record_gap
        setup = sqlite3.connect(self.db_file)
        init_schema(setup)
        record_gap(setup, 1000, 2000)
        setup.commit()
        setup.close()
        status, body = self._get("/api/gaps?from=0&to=10000")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["gaps"]), 1)
        self.assertEqual(body["gaps"][0]["start"], 1000)
        self.assertEqual(body["gaps"][0]["end"], 2000)

    def test_by_port_groups_and_labels(self):
        setup = sqlite3.connect(self.db_file)
        init_schema(setup)
        sid = setup.execute("SELECT id FROM sessions WHERE ended_at IS NULL LIMIT 1").fetchone()[0]
        for ip in ("1.1.1.1", "2.2.2.2"):
            insert_connection(setup, ts=500, session_id=sid, process_name="P", remote_ip=ip, remote_port=443, protocol="tcp", scope="internet")
        insert_connection(setup, ts=500, session_id=sid, process_name="P", remote_ip="8.8.8.8", remote_port=53, protocol="udp", scope="internet")
        setup.commit()
        setup.close()
        _, body = self._get("/api/by-port?from=0&to=10000")
        rows = {r["port"]: r for r in body["rows"]}
        self.assertEqual(rows[443]["count"], 2)
        self.assertEqual(rows[443]["service"], "HTTPS")
        self.assertEqual(rows[53]["service"], "DNS")

    def test_by_process_scope_all_returns_all(self):
        setup_conn = sqlite3.connect(self.db_file)
        init_schema(setup_conn)
        row = setup_conn.execute("SELECT id FROM sessions WHERE ended_at IS NULL LIMIT 1").fetchone()
        sid = row[0]
        insert_process_sample(setup_conn, ts=700, session_id=sid, process_name="ProcE", pid=500, bytes_in=3000, bytes_out=600)
        setup_conn.commit()
        setup_conn.close()

        status, body = self._get("/api/by-process?scope=all&from=0&to=10000")
        self.assertEqual(status, 200)
        names = {r["process_name"] for r in body["rows"]}
        self.assertIn("ProcE", names)


if __name__ == "__main__":
    unittest.main()
