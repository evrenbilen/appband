import sqlite3
import unittest

from netmon.db import (
    init_schema,
    open_session,
    close_session,
    insert_interface_sample,
    insert_process_sample,
    insert_connection,
    upsert_dns,
)
from netmon.retention import purge_old

# Use a fixed reference timestamp that is well into the future relative to the
# retention windows so the maths in purge_old produce positive cutoffs.
_NOW = 200_000_000          # ~6.3 years from epoch — purely synthetic
_OLD = 5                    # "ancient" – clearly before any retention window
_RECENT = _NOW - 86400      # 1 day before _NOW – within all retention windows


class RetentionTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_purges_old_samples_and_keeps_recent(self):
        sid = open_session(self.conn, 0, "en0", "wifi", "Office", None, "1.1.1.1")
        close_session(self.conn, sid, ended_at=_OLD + 5)
        insert_interface_sample(self.conn, ts=_OLD, session_id=sid, bytes_in=1, bytes_out=1)
        insert_process_sample(self.conn, ts=_OLD, session_id=sid, process_name="X", pid=1, bytes_in=1, bytes_out=1)
        insert_connection(self.conn, ts=_OLD, session_id=sid, process_name="X", remote_ip="1.2.3.4", remote_port=80, protocol="tcp")
        upsert_dns(self.conn, ip="1.2.3.4", hostname="x.com", resolved_at=_OLD)

        recent_sid = open_session(self.conn, _RECENT, "en0", "wifi", "Office", None, "1.1.1.1")
        insert_interface_sample(self.conn, ts=_RECENT, session_id=recent_sid, bytes_in=1, bytes_out=1)

        purge_old(
            self.conn,
            now=_NOW,
            sample_retention_sec=86400 * 30,  # 30 days
            dns_retention_sec=86400 * 90,
        )

        # Old samples must be gone
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM interface_samples WHERE ts <= ?", (_OLD,)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM process_samples WHERE ts <= ?", (_OLD,)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM connections WHERE ts <= ?", (_OLD,)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE id = ?", (sid,)
            ).fetchone()[0],
            0,
        )

        # Recent data must survive
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM interface_samples").fetchone()[0], 1
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1
        )

        # Old DNS entry must be purged
        self.assertIsNone(
            self.conn.execute(
                "SELECT hostname FROM dns_cache WHERE ip = '1.2.3.4'"
            ).fetchone()
        )


if __name__ == "__main__":
    unittest.main()
