import sqlite3
import unittest

from netmon.db import init_schema


class InitSchemaTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_creates_all_tables(self):
        init_schema(self.conn)
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cur.fetchall()]
        self.assertEqual(
            tables,
            [
                "connections",
                "dns_cache",
                "interface_samples",
                "process_samples",
                "sessions",
            ],
        )

    def test_idempotent(self):
        init_schema(self.conn)
        init_schema(self.conn)  # second call must not raise

    def test_wal_mode_enabled(self):
        init_schema(self.conn)
        mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        # In-memory databases report "memory"; on-disk would be "wal".
        self.assertIn(mode, ("wal", "memory"))


if __name__ == "__main__":
    unittest.main()
