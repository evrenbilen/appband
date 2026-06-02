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
    record_heartbeat,
    get_health,
    close_orphan_sessions,
    record_gap,
    get_gaps,
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

    def test_close_orphan_sessions_keeps_only_most_recent(self):
        # An unclean shutdown (SIGKILL) leaves sessions with ended_at IS NULL
        # forever; purge_old only deletes ended sessions, so they (and their
        # samples) leak past retention. Startup should close all but the most
        # recent (which SessionWatcher re-adopts).
        open_session(self.conn, 1000, "en0", "wifi", "A", None, "1.1.1.1")
        open_session(self.conn, 2000, "en0", "wifi", "B", None, "1.1.1.2")
        c = open_session(self.conn, 3000, "en0", "wifi", "C", None, "1.1.1.3")
        close_orphan_sessions(self.conn, now=5000)
        open_count = self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL"
        ).fetchone()[0]
        self.assertEqual(open_count, 1)
        self.assertEqual(get_active_session(self.conn)["id"], c)

    def test_close_orphan_sessions_breaks_ties_by_id(self):
        # Sessions sharing a started_at second must resolve deterministically to
        # the highest id (most recent insert), not by query-plan luck.
        open_session(self.conn, 1000, "en0", "wifi", "A", None, "1.1.1.1")
        open_session(self.conn, 1000, "en0", "wifi", "B", None, "1.1.1.2")
        c = open_session(self.conn, 1000, "en0", "wifi", "C", None, "1.1.1.3")
        close_orphan_sessions(self.conn, now=5000)
        self.assertEqual(get_active_session(self.conn)["id"], c)

    def test_close_orphan_sessions_noop_when_one_open(self):
        s = open_session(self.conn, 1000, "en0", "wifi", "A", None, "1.1.1.1")
        close_orphan_sessions(self.conn, now=5000)
        self.assertEqual(get_active_session(self.conn)["id"], s)  # still open

    def test_gap_record_and_read_with_overlap_filter(self):
        record_gap(self.conn, 1000, 2000)   # machine slept 1000..2000
        record_gap(self.conn, 5000, 5050)
        allg = get_gaps(self.conn, 0, 10000)
        self.assertEqual(len(allg), 2)
        self.assertEqual((allg[0]["start"], allg[0]["end"]), (1000, 2000))
        # Only gaps overlapping the window are returned.
        self.assertEqual(len(get_gaps(self.conn, 4000, 10000)), 1)
        # A gap ending exactly at the window start does NOT overlap [from, to).
        self.assertEqual(get_gaps(self.conn, 2000, 3000), [])

    def test_heartbeat_record_and_read(self):
        record_heartbeat(self.conn, "iface", 1000)
        record_heartbeat(self.conn, "proc", 1010)
        record_heartbeat(self.conn, "iface", 1020)  # upsert, not duplicate
        health = get_health(self.conn)
        self.assertEqual(health["iface"], 1020)
        self.assertEqual(health["proc"], 1010)

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

    def test_timeseries_ssid_filter(self):
        a = open_session(self.conn, 0, "en0", "wifi", "Office", None, "1.1.1.1")
        b = open_session(self.conn, 0, "en1", "wifi", "Guest", None, "1.1.1.2")
        insert_interface_sample(self.conn, ts=10, session_id=a, bytes_in=100, bytes_out=10)
        insert_interface_sample(self.conn, ts=20, session_id=b, bytes_in=500, bytes_out=50)
        rows = query_timeseries(self.conn, 0, 3600, "hour", ssid="Office")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bytes_in"], 100)

    def test_timeseries_link_type_filter_for_null_ssid(self):
        e = open_session(self.conn, 0, "en5", "ethernet", None, None, "10.0.0.1")
        w = open_session(self.conn, 0, "en0", "wifi", "Office", None, "1.1.1.1")
        insert_interface_sample(self.conn, ts=10, session_id=e, bytes_in=200, bytes_out=20)
        insert_interface_sample(self.conn, ts=20, session_id=w, bytes_in=100, bytes_out=10)
        rows = query_timeseries(self.conn, 0, 3600, "hour", link_type="ethernet")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bytes_in"], 200)

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


class MissingTableToleranceTest(unittest.TestCase):
    """collector_health and gaps are created by init_schema (run by the
    collector). The server reads them per request — but if it runs against a DB
    an older/other collector hasn't migrated yet (upgrade window, or a DB
    recovered without them), those reads must degrade to empty, not raise (which
    surfaced as a 500 on /api/health and /api/gaps against a real, un-migrated DB)."""

    def test_get_health_tolerates_missing_collector_health_table(self):
        bare = sqlite3.connect(":memory:")  # no init_schema → table absent
        try:
            self.assertEqual(get_health(bare), {})
        finally:
            bare.close()

    def test_get_gaps_tolerates_missing_gaps_table(self):
        bare = sqlite3.connect(":memory:")
        try:
            self.assertEqual(get_gaps(bare, 0, 9_999_999_999), [])
        finally:
            bare.close()

    def test_get_health_still_raises_on_a_non_missing_table_error(self):
        # Only "no such table" is swallowed — a genuinely broken connection must
        # still surface, so real failures aren't masked as "healthy/empty".
        bare = sqlite3.connect(":memory:")
        bare.close()
        with self.assertRaises(Exception):
            get_health(bare)


if __name__ == "__main__":
    unittest.main()
