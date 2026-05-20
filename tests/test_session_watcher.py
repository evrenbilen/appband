import sqlite3
import unittest
from unittest.mock import patch

from netmon.db import init_schema, get_active_session
from netmon.session_watcher import SessionWatcher, NetworkSnapshot


class SessionWatcherTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        init_schema(self.conn)
        self.watcher = SessionWatcher(self.conn)

    def tearDown(self):
        self.conn.close()

    def _snap(self, **kw):
        return NetworkSnapshot(
            interface=kw.get("interface", "en0"),
            link_type=kw.get("link_type", "wifi"),
            ssid=kw.get("ssid", "Office"),
            bssid=kw.get("bssid", None),
            ip_address=kw.get("ip_address", "192.168.1.42"),
        )

    def test_first_snapshot_opens_session(self):
        sid = self.watcher.tick(self._snap(), now=1000)
        self.assertEqual(sid, get_active_session(self.conn)["id"])

    def test_same_network_keeps_session(self):
        sid1 = self.watcher.tick(self._snap(), now=1000)
        sid2 = self.watcher.tick(self._snap(), now=1100)
        self.assertEqual(sid1, sid2)

    def test_ssid_change_opens_new_session(self):
        sid1 = self.watcher.tick(self._snap(ssid="Office"), now=1000)
        sid2 = self.watcher.tick(self._snap(ssid="Home"), now=1100)
        self.assertNotEqual(sid1, sid2)
        cur = self.conn.execute(
            "SELECT ended_at FROM sessions WHERE id = ?", (sid1,)
        )
        self.assertEqual(cur.fetchone()[0], 1100)

    def test_interface_change_opens_new_session(self):
        sid1 = self.watcher.tick(self._snap(interface="en0"), now=1000)
        sid2 = self.watcher.tick(self._snap(interface="en6", link_type="usb-tether", ssid=None), now=1100)
        self.assertNotEqual(sid1, sid2)

    def test_offline_closes_session(self):
        sid1 = self.watcher.tick(self._snap(), now=1000)
        result = self.watcher.tick(None, now=1100)
        self.assertIsNone(result)
        cur = self.conn.execute(
            "SELECT ended_at FROM sessions WHERE id = ?", (sid1,)
        )
        self.assertEqual(cur.fetchone()[0], 1100)

    def test_back_online_after_offline(self):
        self.watcher.tick(self._snap(), now=1000)
        self.watcher.tick(None, now=1100)
        sid = self.watcher.tick(self._snap(), now=1200)
        self.assertEqual(get_active_session(self.conn)["id"], sid)


class CollectSnapshotTest(unittest.TestCase):
    def test_collect_snapshot_offline(self):
        from netmon.session_watcher import collect_snapshot
        with patch("netmon.session_watcher._run", return_value=""):
            self.assertIsNone(collect_snapshot())


if __name__ == "__main__":
    unittest.main()
