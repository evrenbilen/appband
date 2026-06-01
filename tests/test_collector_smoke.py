import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from appband.collector import CollectorState, _thread_local, run_connection_tick, run_interface_tick, run_process_tick
from appband.db import init_schema, open_session
from appband.delta import DeltaTracker


class CollectorTickTest(unittest.TestCase):
    def setUp(self):
        # Use a real temp file so _conn() can open it via path (not :memory:).
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)

        # Run schema migration and seed a session via a setup connection.
        setup = sqlite3.connect(str(self.db_path))
        init_schema(setup)
        self.sid = open_session(
            setup, 1000, "en0", "wifi", "Office", None, "192.168.1.42"
        )
        setup.commit()
        setup.close()

        self.state = CollectorState(
            db_path=self.db_path,
            iface_tracker=DeltaTracker(max_delta_per_sec=10**9),
            proc_in_tracker=DeltaTracker(max_delta_per_sec=10**9),
            proc_out_tracker=DeltaTracker(max_delta_per_sec=10**9),
            active_interface="en0",
            active_session_id=self.sid,
            dns_enqueue=lambda ip: None,
        )

    def tearDown(self):
        # Close the thread-local connection if the test used it, then remove the file.
        if hasattr(_thread_local, "conn"):
            _thread_local.conn.close()
            del _thread_local.conn
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _check(self, sql):
        """Open a fresh read connection to inspect results."""
        conn = sqlite3.connect(str(self.db_path))
        result = conn.execute(sql).fetchone()
        conn.close()
        return result

    def test_interface_tick_records_delta(self):
        sample1 = [
            {"process_name": "dst1", "pid": 1, "bytes_in": 700, "bytes_out": 100},
            {"process_name": "dst2", "pid": 2, "bytes_in": 300, "bytes_out": 100},
        ]
        sample2 = [
            {"process_name": "dst1", "pid": 1, "bytes_in": 1100, "bytes_out": 200},
            {"process_name": "dst2", "pid": 2, "bytes_in": 400, "bytes_out": 100},
        ]
        with patch("appband.collector.parse_nettop", return_value=sample1), \
             patch("appband.collector._run", return_value="dummy"):
            run_interface_tick(self.state, now=1000)
            self.assertEqual(self._check("SELECT COUNT(*) FROM interface_samples")[0], 0)

        with patch("appband.collector.parse_nettop", return_value=sample2), \
             patch("appband.collector._run", return_value="dummy"):
            run_interface_tick(self.state, now=1005)
            row = self._check("SELECT bytes_in, bytes_out FROM interface_samples")
            # sum1 = 1000/200, sum2 = 1500/300 → delta = 500/100
            self.assertEqual(row, (500, 100))

    def test_skips_when_no_active_session(self):
        self.state.active_session_id = None
        sample = [{"process_name": "p", "pid": 1, "bytes_in": 1000, "bytes_out": 200}]
        with patch("appband.collector.parse_nettop", return_value=sample), \
             patch("appband.collector._run", return_value="dummy"):
            run_interface_tick(self.state, now=1000)
            run_interface_tick(self.state, now=1005)
            self.assertEqual(self._check("SELECT COUNT(*) FROM interface_samples")[0], 0)

    def test_process_tick_records_delta(self):
        sample1 = [{"process_name": "Chrome", "pid": 42, "bytes_in": 1000, "bytes_out": 100}]
        sample2 = [{"process_name": "Chrome", "pid": 42, "bytes_in": 1500, "bytes_out": 200}]
        with patch("appband.collector.parse_nettop", return_value=sample1), \
             patch("appband.collector._run", return_value=""):
            run_process_tick(self.state, now=1000)
        with patch("appband.collector.parse_nettop", return_value=sample2), \
             patch("appband.collector._run", return_value=""):
            run_process_tick(self.state, now=1010)
        row = self._check("SELECT process_name, bytes_in, bytes_out FROM process_samples")
        self.assertEqual(row, ("Chrome", 500, 100))

    def test_connection_tick_records_and_enqueues(self):
        enqueued = []
        self.state.dns_enqueue = enqueued.append
        rows = [
            {"process_name": "Chrome", "pid": 42, "remote_ip": "1.2.3.4", "remote_port": 443, "protocol": "tcp", "scope": "internet"},
            {"process_name": "zoom.us", "pid": 88, "remote_ip": "5.6.7.8", "remote_port": 8801, "protocol": "udp", "scope": "internet"},
        ]
        with patch("appband.collector.parse_lsof_connections", return_value=rows), \
             patch("appband.collector._run", return_value=""):
            run_connection_tick(self.state, now=1000)
        self.assertEqual(self._check("SELECT COUNT(*) FROM connections")[0], 2)
        self.assertEqual(set(enqueued), {"1.2.3.4", "5.6.7.8"})


class SetupLoggingTest(unittest.TestCase):
    def test_uses_rotating_file_handler(self):
        # Long-lived LaunchAgents must not grow their log file unbounded.
        import logging
        from logging.handlers import RotatingFileHandler

        from appband.collector import _setup_logging
        from appband.config import Config

        root = logging.getLogger("appband")
        saved = root.handlers[:]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                _setup_logging(Config(log_dir=Path(tmp)))
                self.assertTrue(
                    any(isinstance(h, RotatingFileHandler) for h in root.handlers)
                )
        finally:
            for h in root.handlers[:]:
                if h not in saved:
                    h.close()
                    root.removeHandler(h)


if __name__ == "__main__":
    unittest.main()
