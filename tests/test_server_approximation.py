"""Known-value characterization tests for the by-process / by-domain
approximation math.

There is no per-connection byte accounting (see CLAUDE.md "approximation
model"). `/api/by-process` (scoped) and `/api/by-domain` *distribute* each
process's measured bytes within a 5-minute bucket. These tests pin the exact
arithmetic with hand-computed byte values so a future change to the SQL can't
silently shift the numbers users see.

Two models are deliberately asserted side by side because they differ — this is
intentional documentation of current behavior, not an endorsement:

  * by-process (scope=internet) scales bytes by the *connection-scope fraction*
    matching/total — so 900 bytes over 2-of-3 internet connections → 600.
  * by-domain (scope=internet) splits the *full* process bytes equally across
    the in-scope hosts only — the out-of-scope share is over-attributed to the
    in-scope hosts, NOT dropped. So 1000 bytes over 2 internet hosts → 500 each
    even when a third (LAN) host also saw traffic.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from contextlib import closing
from pathlib import Path

from appband.db import (
    init_schema,
    open_session,
    insert_process_sample,
    insert_connection,
    upsert_dns,
)
from appband.server import build_handler, NetmonServer

# One 5-minute bucket: 300000 // 300 * 300 == 300000. All samples land inside
# [FROM, TO) so the queries see exactly one bucket.
B0 = 300_000
FROM = 300_000
TO = 300_300


class ApproximationTest(unittest.TestCase):
    def setUp(self):
        fd, db_file = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_file = db_file
        self.db_path = Path(db_file)

        conn = sqlite3.connect(db_file)
        init_schema(conn)
        self.sid = open_session(conn, 0, "en0", "wifi", "Office", None, "10.0.0.2")
        conn.commit()
        conn.close()

        handler = build_handler(self.db_path)
        self.server = NetmonServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()  # close the listening socket (no ResourceWarning)
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.db_file + suffix)
            except FileNotFoundError:
                pass

    # ── seeding helpers ──────────────────────────────────────────────────────
    def _seed(self, rows_fn):
        conn = sqlite3.connect(self.db_file)
        rows_fn(conn)
        conn.commit()
        conn.close()

    def _get(self, path: str) -> dict:
        url = f"http://127.0.0.1:{self.port}{path}"
        with closing(urllib.request.urlopen(url, timeout=2)) as resp:
            return json.loads(resp.read())

    def _by_process(self, scope: str) -> dict:
        rows = self._get(f"/api/by-process?from={FROM}&to={TO}&limit=50&scope={scope}")["rows"]
        return {r["process_name"]: r for r in rows}

    def _by_domain(self, scope: str) -> dict:
        rows = self._get(f"/api/by-domain?from={FROM}&to={TO}&limit=50&scope={scope}")["rows"]
        return {r["host"]: r for r in rows}

    # ── by-process: scope-fraction scaling ──────────────────────────────────
    def test_by_process_scope_all_is_exact_and_not_approximate(self):
        # scope=all bypasses distribution entirely: raw process_samples sums.
        def seed(c):
            insert_process_sample(c, ts=B0, session_id=self.sid, process_name="Safari", pid=1, bytes_in=900, bytes_out=300)
            insert_connection(c, ts=B0, session_id=self.sid, process_name="Safari", remote_ip="1.1.1.1", remote_port=443, protocol="tcp", scope="internet")
        self._seed(seed)

        row = self._by_process("all")["Safari"]
        self.assertEqual(row["bytes_in"], 900)
        self.assertEqual(row["bytes_out"], 300)
        self.assertFalse(row["approximate"])

    def test_by_process_internet_scales_by_connection_scope_fraction(self):
        # 2 of 3 connections are internet → share 2/3. 900*2/3=600, 300*2/3=200.
        def seed(c):
            insert_process_sample(c, ts=B0, session_id=self.sid, process_name="Safari", pid=1, bytes_in=900, bytes_out=300)
            insert_connection(c, ts=B0, session_id=self.sid, process_name="Safari", remote_ip="1.1.1.1", remote_port=443, protocol="tcp", scope="internet")
            insert_connection(c, ts=B0 + 1, session_id=self.sid, process_name="Safari", remote_ip="2.2.2.2", remote_port=443, protocol="tcp", scope="internet")
            insert_connection(c, ts=B0 + 2, session_id=self.sid, process_name="Safari", remote_ip="192.168.0.9", remote_port=445, protocol="tcp", scope="lan")
        self._seed(seed)

        row = self._by_process("internet")["Safari"]
        self.assertEqual(row["bytes_in"], 600)
        self.assertEqual(row["bytes_out"], 200)
        self.assertTrue(row["approximate"])

    def test_by_process_lan_scales_by_connection_scope_fraction(self):
        # 1 of 3 connections is lan → share 1/3. 900/3=300, 300/3=100.
        def seed(c):
            insert_process_sample(c, ts=B0, session_id=self.sid, process_name="Safari", pid=1, bytes_in=900, bytes_out=300)
            insert_connection(c, ts=B0, session_id=self.sid, process_name="Safari", remote_ip="1.1.1.1", remote_port=443, protocol="tcp", scope="internet")
            insert_connection(c, ts=B0 + 1, session_id=self.sid, process_name="Safari", remote_ip="2.2.2.2", remote_port=443, protocol="tcp", scope="internet")
            insert_connection(c, ts=B0 + 2, session_id=self.sid, process_name="Safari", remote_ip="192.168.0.9", remote_port=445, protocol="tcp", scope="lan")
        self._seed(seed)

        row = self._by_process("lan")["Safari"]
        self.assertEqual(row["bytes_in"], 300)
        self.assertEqual(row["bytes_out"], 100)

    # ── by-domain: equal split across hosts ──────────────────────────────────
    def test_by_domain_distributes_process_bytes_equally_across_hosts(self):
        # 1000 in / 400 out split across 2 resolved internet hosts → 500/200 each.
        def seed(c):
            insert_process_sample(c, ts=B0, session_id=self.sid, process_name="Safari", pid=1, bytes_in=1000, bytes_out=400)
            insert_connection(c, ts=B0, session_id=self.sid, process_name="Safari", remote_ip="1.1.1.1", remote_port=443, protocol="tcp", scope="internet")
            insert_connection(c, ts=B0 + 1, session_id=self.sid, process_name="Safari", remote_ip="2.2.2.2", remote_port=443, protocol="tcp", scope="internet")
            upsert_dns(c, "1.1.1.1", "alpha.example", B0)
            upsert_dns(c, "2.2.2.2", "beta.example", B0)
        self._seed(seed)

        rows = self._by_domain("internet")
        self.assertEqual(set(rows), {"alpha.example", "beta.example"})
        self.assertEqual(rows["alpha.example"]["bytes_in"], 500)
        self.assertEqual(rows["alpha.example"]["bytes_out"], 200)
        self.assertEqual(rows["beta.example"]["bytes_in"], 500)
        self.assertEqual(rows["beta.example"]["bytes_out"], 200)
        self.assertTrue(rows["alpha.example"]["approximate"])

    def test_by_domain_uses_resolved_hostname_else_raw_ip(self):
        # One IP is resolved → hostname; the other has no dns_cache row → raw IP.
        def seed(c):
            insert_process_sample(c, ts=B0, session_id=self.sid, process_name="Mail", pid=2, bytes_in=200, bytes_out=80)
            insert_connection(c, ts=B0, session_id=self.sid, process_name="Mail", remote_ip="1.1.1.1", remote_port=993, protocol="tcp", scope="internet")
            insert_connection(c, ts=B0 + 1, session_id=self.sid, process_name="Mail", remote_ip="8.8.8.8", remote_port=993, protocol="tcp", scope="internet")
            upsert_dns(c, "1.1.1.1", "imap.example", B0)
        self._seed(seed)

        rows = self._by_domain("internet")
        self.assertEqual(set(rows), {"imap.example", "8.8.8.8"})
        self.assertEqual(rows["imap.example"]["bytes_in"], 100)  # 200 / 2 hosts
        self.assertEqual(rows["8.8.8.8"]["bytes_in"], 100)

    def test_by_domain_excludes_out_of_scope_hosts_but_keeps_full_bytes(self):
        # Documents the model difference vs by-process: with a LAN host present,
        # scope=internet still distributes the FULL 1000 bytes across the two
        # internet hosts (500 each) — the LAN host is dropped, not its byte share.
        def seed(c):
            insert_process_sample(c, ts=B0, session_id=self.sid, process_name="Safari", pid=1, bytes_in=1000, bytes_out=0)
            insert_connection(c, ts=B0, session_id=self.sid, process_name="Safari", remote_ip="1.1.1.1", remote_port=443, protocol="tcp", scope="internet")
            insert_connection(c, ts=B0 + 1, session_id=self.sid, process_name="Safari", remote_ip="2.2.2.2", remote_port=443, protocol="tcp", scope="internet")
            insert_connection(c, ts=B0 + 2, session_id=self.sid, process_name="Safari", remote_ip="192.168.0.9", remote_port=445, protocol="tcp", scope="lan")
            upsert_dns(c, "1.1.1.1", "alpha.example", B0)
            upsert_dns(c, "2.2.2.2", "beta.example", B0)
            upsert_dns(c, "192.168.0.9", "nas.local", B0)
        self._seed(seed)

        rows = self._by_domain("internet")
        self.assertNotIn("nas.local", rows)
        self.assertEqual(rows["alpha.example"]["bytes_in"], 500)
        self.assertEqual(rows["beta.example"]["bytes_in"], 500)
        # Full process bytes are attributed to the in-scope hosts (not scaled down).
        total_in = sum(r["bytes_in"] for r in rows.values())
        self.assertEqual(total_in, 1000)


if __name__ == "__main__":
    unittest.main()
