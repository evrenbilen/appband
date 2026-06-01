import json
import tempfile
import unittest
from pathlib import Path

from appband.config import Config, load_config


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.port, 8765)
        self.assertEqual(cfg.bind_host, "127.0.0.1")
        self.assertEqual(cfg.interface_poll_sec, 5)
        self.assertEqual(cfg.process_poll_sec, 10)
        self.assertEqual(cfg.connection_poll_sec, 30)
        self.assertEqual(cfg.session_poll_sec, 2)
        self.assertEqual(cfg.retention_days, 30)
        self.assertEqual(cfg.log_level, "INFO")
        self.assertTrue(str(cfg.db_path).endswith("appband.db"))

    def test_load_with_override_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"port": 9000, "retention_days": 7}))
            cfg = load_config(path)
            self.assertEqual(cfg.port, 9000)
            self.assertEqual(cfg.retention_days, 7)
            self.assertEqual(cfg.bind_host, "127.0.0.1")  # unchanged default

    def test_load_missing_file_uses_defaults(self):
        cfg = load_config(Path("/nonexistent/path.json"))
        self.assertEqual(cfg.port, 8765)

    def _load_with(self, data: dict) -> Config:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(data))
            return load_config(path)

    def test_clamps_non_loopback_bind_host_to_loopback(self):
        # The localhost-only constraint must survive a tampered config: a
        # routable bind_host would expose the unauthenticated API to the LAN.
        self.assertEqual(self._load_with({"bind_host": "0.0.0.0"}).bind_host, "127.0.0.1")
        self.assertEqual(self._load_with({"bind_host": "192.168.1.5"}).bind_host, "127.0.0.1")

    def test_allows_loopback_bind_hosts(self):
        self.assertEqual(self._load_with({"bind_host": "::1"}).bind_host, "::1")
        self.assertEqual(self._load_with({"bind_host": "localhost"}).bind_host, "localhost")
        self.assertEqual(self._load_with({"bind_host": "127.0.0.2"}).bind_host, "127.0.0.2")


if __name__ == "__main__":
    unittest.main()
