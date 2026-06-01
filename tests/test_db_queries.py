import sqlite3
import unittest

from appband.db import (
    init_schema,
    open_session,
    close_session,
    get_active_session,
    insert_interface_sample,
    insert_process_sample,
    insert_connection,
    upsert_dns,
    get_dns_hostname,
    query_timeseries,
)


class DbQueryTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_session_lifecycle(self):
        sid = open_session(
            self.conn,
            started_at=1000,
            interface="en0",
            link_type="wifi",
            ssid="Office",
            bssid=None,
            ip_address="192.168.1.42",
        )
        self.assertGreater(sid, 0)
        active = get_active_session(self.conn)
        self.assertEqual(active["id"], sid)
        self.assertIsNone(active["ended_at"])
        close_session(self.conn, sid, ended_at=2000)
        self.assertIsNone(get_active_session(self.conn))

    def test_insert_samples(self):
        sid = open_session(self.conn, 1000, "en0", "wifi", "Office", None, "192.168.1.42")
        insert_interface_sample(self.conn, ts=1100, session_id=sid, bytes_in=1000, bytes_out=200)
        insert_process_sample(self.conn, ts=1100, session_id=sid, process_name="Chrome", pid=42, bytes_in=900, bytes_out=180)
        insert_connection(self.conn, ts=1100, session_id=sid, process_name="Chrome", remote_ip="1.2.3.4", remote_port=443, protocol="tcp")
        cur = self.conn.execute("SELECT COUNT(*) FROM interface_samples")
        self.assertEqual(cur.fetchone()[0], 1)
        cur = self.conn.execute("SELECT COUNT(*) FROM process_samples")
        self.assertEqual(cur.fetchone()[0], 1)
        cur = self.conn.execute("SELECT COUNT(*) FROM connections")
        self.assertEqual(cur.fetchone()[0], 1)

    def test_dns_cache(self):
        upsert_dns(self.conn, ip="1.2.3.4", hostname="example.com", resolved_at=1000)
        self.assertEqual(get_dns_hostname(self.conn, "1.2.3.4"), "example.com")
        upsert_dns(self.conn, ip="1.2.3.4", hostname="updated.com", resolved_at=2000)
        self.assertEqual(get_dns_hostname(self.conn, "1.2.3.4"), "updated.com")
        upsert_dns(self.conn, ip="9.9.9.9", hostname=None, resolved_at=1500)
        self.assertIsNone(get_dns_hostname(self.conn, "9.9.9.9"))
        self.assertIsNone(get_dns_hostname(self.conn, "missing.ip"))

    def test_timeseries_minute_aggregation(self):
        sid = open_session(self.conn, 0, "en0", "wifi", "Office", None, "192.168.1.42")
        # Two samples in minute-bucket [0,60), one in [120,180); bucket [60,120) empty.
        for ts, bi, bo in [(10, 100, 10), (50, 100, 10), (130, 200, 20)]:
            insert_interface_sample(self.conn, ts=ts, session_id=sid, bytes_in=bi, bytes_out=bo)
        result = query_timeseries(self.conn, from_ts=0, to_ts=300, granularity="minute")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["ts"], 0)
        self.assertEqual(result[0]["bytes_in"], 200)
        self.assertEqual(result[0]["bytes_out"], 20)
        self.assertEqual(result[1]["ts"], 120)
        self.assertEqual(result[1]["bytes_in"], 200)

    def test_timeseries_hourly_aggregation(self):
        sid = open_session(self.conn, 0, "en0", "wifi", "Office", None, "192.168.1.42")
        # 4 samples within the same hour (3600 sec window starting at 0)
        for ts, bi, bo in [(100, 1000, 100), (200, 500, 50), (3700, 200, 20), (3800, 300, 30)]:
            insert_interface_sample(self.conn, ts=ts, session_id=sid, bytes_in=bi, bytes_out=bo)
        result = query_timeseries(self.conn, from_ts=0, to_ts=7200, granularity="hour")
        # First bucket [0, 3600) -> 1500/150 ; second bucket [3600, 7200) -> 500/50
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["bytes_in"], 1500)
        self.assertEqual(result[0]["bytes_out"], 150)
        self.assertEqual(result[1]["bytes_in"], 500)
        self.assertEqual(result[1]["bytes_out"], 50)


if __name__ == "__main__":
    unittest.main()
