import sqlite3
import unittest
from unittest.mock import patch

from netmon.collector import CollectorState, run_interface_tick, run_process_tick, run_connection_tick
from netmon.db import init_schema, open_session
from netmon.delta import DeltaTracker


class CollectorTickTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        init_schema(self.conn)
        self.sid = open_session(
            self.conn, 1000, "en0", "wifi", "Office", None, "192.168.1.42"
        )
        self.state = CollectorState(
            conn=self.conn,
            iface_tracker=DeltaTracker(max_delta_per_sec=10**9),
            proc_in_tracker=DeltaTracker(max_delta_per_sec=10**9),
            proc_out_tracker=DeltaTracker(max_delta_per_sec=10**9),
            active_interface="en0",
            active_session_id=self.sid,
            dns_enqueue=lambda ip: None,
        )

    def test_interface_tick_records_delta(self):
        with patch(
            "netmon.collector.parse_netstat_ibn",
            return_value={"en0": {"bytes_in": 1000, "bytes_out": 200}},
        ), patch("netmon.collector._run", return_value=""):
            run_interface_tick(self.state, now=1000)
            self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interface_samples").fetchone()[0], 0)

        with patch(
            "netmon.collector.parse_netstat_ibn",
            return_value={"en0": {"bytes_in": 1500, "bytes_out": 300}},
        ), patch("netmon.collector._run", return_value=""):
            run_interface_tick(self.state, now=1005)
            row = self.conn.execute(
                "SELECT bytes_in, bytes_out FROM interface_samples"
            ).fetchone()
            self.assertEqual(row, (500, 100))

    def test_skips_when_no_active_session(self):
        self.state.active_session_id = None
        with patch(
            "netmon.collector.parse_netstat_ibn",
            return_value={"en0": {"bytes_in": 1000, "bytes_out": 200}},
        ), patch("netmon.collector._run", return_value=""):
            run_interface_tick(self.state, now=1000)
            run_interface_tick(self.state, now=1005)
            self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interface_samples").fetchone()[0], 0)

    def test_process_tick_records_delta(self):
        sample1 = [{"process_name": "Chrome", "pid": 42, "bytes_in": 1000, "bytes_out": 100}]
        sample2 = [{"process_name": "Chrome", "pid": 42, "bytes_in": 1500, "bytes_out": 200}]
        with patch("netmon.collector.parse_nettop", return_value=sample1), \
             patch("netmon.collector._run", return_value=""):
            run_process_tick(self.state, now=1000)
        with patch("netmon.collector.parse_nettop", return_value=sample2), \
             patch("netmon.collector._run", return_value=""):
            run_process_tick(self.state, now=1010)
        row = self.conn.execute(
            "SELECT process_name, bytes_in, bytes_out FROM process_samples"
        ).fetchone()
        self.assertEqual(row, ("Chrome", 500, 100))

    def test_connection_tick_records_and_enqueues(self):
        enqueued = []
        self.state.dns_enqueue = enqueued.append
        rows = [
            {"process_name": "Chrome", "pid": 42, "remote_ip": "1.2.3.4", "remote_port": 443, "protocol": "tcp", "scope": "internet"},
            {"process_name": "zoom.us", "pid": 88, "remote_ip": "5.6.7.8", "remote_port": 8801, "protocol": "udp", "scope": "internet"},
        ]
        with patch("netmon.collector.parse_lsof_connections", return_value=rows), \
             patch("netmon.collector._run", return_value=""):
            run_connection_tick(self.state, now=1000)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM connections").fetchone()[0], 2)
        self.assertEqual(set(enqueued), {"1.2.3.4", "5.6.7.8"})


if __name__ == "__main__":
    unittest.main()
