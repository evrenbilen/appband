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

from netmon.db import init_schema, open_session, insert_interface_sample
from netmon.server import build_handler, NetmonServer


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


if __name__ == "__main__":
    unittest.main()
