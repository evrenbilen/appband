import sqlite3
import unittest

from appband.db import (
    init_schema,
    open_session,
    insert_interface_sample,
    query_budget,
    PERIOD_SECONDS,
)

# A fixed "now" so the rolling window is deterministic.
NOW = 1_000_000


class QueryBudgetTest(unittest.TestCase):
    def setUp(self):
        # :memory: is fine here — query_budget is a single-connection pure query,
        # unlike collector tests that need a real temp-file DB for multi-threaded _conn() access.
        self.conn = sqlite3.connect(":memory:")
        init_schema(self.conn)
        # Two networks. wifi "Home"; metered iphone-hotspot (no ssid).
        self.wifi = open_session(self.conn, NOW - 10_000, "en0", "wifi", "Home", None, "10.0.0.2")
        self.hot = open_session(self.conn, NOW - 10_000, "en5", "iphone-hotspot", None, None, "172.20.10.2")

    def tearDown(self):
        self.conn.close()

    def _seed(self, session_id, ts, bin_, bout):
        insert_interface_sample(self.conn, ts=ts, session_id=session_id, bytes_in=bin_, bytes_out=bout)

    def test_scope_all_sums_every_network_in_window(self):
        # Both inside the 1h window (from = NOW-3600).
        self._seed(self.wifi, NOW - 100, 1000, 200)
        self._seed(self.hot, NOW - 50, 500, 100)
        r = query_budget(self.conn, cap_bytes=10_000, period="hour", now=NOW, scope="all")
        self.assertEqual(r["used_bytes"], 1800)          # 1200 + 600
        self.assertEqual(r["window"], {"from": NOW - 3600, "to": NOW})
        self.assertEqual(r["pct"], 18.0)
        self.assertFalse(r["over"])

    def test_scope_metered_sums_only_hotspot(self):
        self._seed(self.wifi, NOW - 100, 1000, 200)      # ignored
        self._seed(self.hot, NOW - 50, 500, 100)
        r = query_budget(self.conn, cap_bytes=10_000, period="hour", now=NOW, scope="metered")
        self.assertEqual(r["used_bytes"], 600)

    def test_scope_net_by_ssid(self):
        self._seed(self.wifi, NOW - 100, 1000, 200)
        self._seed(self.hot, NOW - 50, 500, 100)         # ignored
        r = query_budget(self.conn, cap_bytes=10_000, period="hour", now=NOW, scope="net", ssid="Home")
        self.assertEqual(r["used_bytes"], 1200)

    def test_scope_net_by_link_type_only_ssidless(self):
        self._seed(self.wifi, NOW - 100, 1000, 200)      # ignored (has ssid)
        self._seed(self.hot, NOW - 50, 500, 100)
        r = query_budget(self.conn, cap_bytes=10_000, period="hour", now=NOW, scope="net", link_type="iphone-hotspot")
        self.assertEqual(r["used_bytes"], 600)

    def test_window_boundaries_from_inclusive_to_exclusive(self):
        self._seed(self.wifi, NOW - 3600, 10, 0)         # ts == from  → included
        self._seed(self.wifi, NOW, 999, 0)               # ts == to    → excluded
        self._seed(self.wifi, NOW - 3601, 777, 0)        # before from → excluded
        r = query_budget(self.conn, cap_bytes=1000, period="hour", now=NOW, scope="all")
        self.assertEqual(r["used_bytes"], 10)

    def test_periods_select_the_right_window(self):
        self.assertEqual(PERIOD_SECONDS, {"hour": 3600, "day": 86400, "week": 604800, "month": 2592000})
        self._seed(self.wifi, NOW - 7200, 50, 0)         # 2h ago: outside hour, inside day
        r_hour = query_budget(self.conn, cap_bytes=1000, period="hour", now=NOW, scope="all")
        r_day = query_budget(self.conn, cap_bytes=1000, period="day", now=NOW, scope="all")
        self.assertEqual(r_hour["used_bytes"], 0)
        self.assertEqual(r_day["used_bytes"], 50)

    def test_pct_and_over_at_and_above_cap(self):
        self._seed(self.wifi, NOW - 10, 1000, 0)
        exactly = query_budget(self.conn, cap_bytes=1000, period="hour", now=NOW, scope="all")
        self.assertEqual(exactly["pct"], 100.0)
        self.assertTrue(exactly["over"])                 # >= cap
        self._seed(self.wifi, NOW - 9, 500, 0)
        above = query_budget(self.conn, cap_bytes=1000, period="hour", now=NOW, scope="all")
        self.assertEqual(above["pct"], 150.0)
        self.assertTrue(above["over"])

    def test_empty_window_is_zero(self):
        r = query_budget(self.conn, cap_bytes=1000, period="hour", now=NOW, scope="all")
        self.assertEqual(r["used_bytes"], 0)
        self.assertEqual(r["pct"], 0.0)
        self.assertFalse(r["over"])

    def test_unknown_period_falls_back_to_month(self):
        r = query_budget(self.conn, cap_bytes=1000, period="bogus", now=NOW, scope="all")
        self.assertEqual(r["window"]["from"], NOW - 2592000)
        self.assertEqual(r["period"], "month")


if __name__ == "__main__":
    unittest.main()
