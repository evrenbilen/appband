import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from contextlib import closing
from pathlib import Path

from appband.db import init_schema, open_session, insert_interface_sample, insert_process_sample, insert_connection
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

    def test_current_returns_active_session(self):
        status, body = self._get("/api/current")
        self.assertEqual(status, 200)
        self.assertEqual(body["session"]["ssid"], "Office")
        self.assertIn("bytes_in_60s", body)
        self.assertIn("bytes_out_60s", body)

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
