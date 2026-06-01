import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from appband.db import connect, init_schema


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
                "collector_health",
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


class ConnectPermsTest(unittest.TestCase):
    def test_db_file_is_owner_only(self):
        # The DB is a longitudinal record of network behavior; restrict it to
        # the owner (0600) so other local users can't read it at rest.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "appband.db"
            conn = connect(db_path)
            conn.close()
            mode = os.stat(db_path).st_mode & 0o777
            self.assertEqual(oct(mode), oct(0o600))


class CorruptDbTest(unittest.TestCase):
    def test_corrupt_db_is_quarantined_and_recreated(self):
        # A corrupt DB (power loss mid-WAL, disk full) must not crash-loop the
        # KeepAlive collector. connect() should quarantine it and start fresh.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "appband.db"
            db_path.write_bytes(b"NOT a sqlite database " * 100)

            conn = connect(db_path)  # must not raise
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            conn.close()
            self.assertIn("sessions", tables)  # fresh schema created

            quarantined = list(Path(tmp).glob("appband.db.corrupt-*"))
            self.assertEqual(len(quarantined), 1)

    def test_healthy_db_is_not_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "appband.db"
            connect(db_path).close()      # create a healthy DB
            connect(db_path).close()      # reopen — must not quarantine
            self.assertEqual(list(Path(tmp).glob("appband.db.corrupt-*")), [])

    def test_empty_db_is_not_quarantined(self):
        # A 0-byte file is a valid empty SQLite DB (quick_check returns "ok"),
        # not corruption — it should be initialized, not quarantined.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "appband.db"
            db_path.touch()
            conn = connect(db_path)
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            conn.close()
            self.assertIn("sessions", tables)
            self.assertEqual(list(Path(tmp).glob("appband.db.corrupt-*")), [])


if __name__ == "__main__":
    unittest.main()
