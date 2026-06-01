import asyncio
import socket
import sqlite3
import unittest
from unittest.mock import patch

from appband.db import init_schema, get_dns_hostname
from appband.dns_cache import DnsResolver


class DnsResolverTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        init_schema(self.conn)
        self.resolver = DnsResolver(self.conn, timeout=1.0, concurrency=2)

    def tearDown(self):
        self.conn.close()

    def test_resolves_and_caches(self):
        async def fake_lookup(ip):
            return "example.com"

        async def run():
            with patch.object(self.resolver, "_lookup", side_effect=fake_lookup):
                await self.resolver._resolve_one("1.2.3.4", now=1000)

        asyncio.run(run())
        self.assertEqual(get_dns_hostname(self.conn, "1.2.3.4"), "example.com")

    def test_caches_failures_as_null(self):
        async def fake_lookup(ip):
            raise socket.herror("not found")

        async def run():
            with patch.object(self.resolver, "_lookup", side_effect=fake_lookup):
                await self.resolver._resolve_one("9.9.9.9", now=1000)

        asyncio.run(run())
        cur = self.conn.execute("SELECT hostname FROM dns_cache WHERE ip = ?", ("9.9.9.9",))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row[0])

    def test_skips_recent_failed_lookup(self):
        self.conn.execute(
            "INSERT INTO dns_cache (ip, hostname, resolved_at) VALUES (?, NULL, ?)",
            ("5.5.5.5", 1000),
        )
        self.assertFalse(self.resolver._should_lookup("5.5.5.5", now=1000 + 3600))

    def test_retries_stale_failed_lookup(self):
        self.conn.execute(
            "INSERT INTO dns_cache (ip, hostname, resolved_at) VALUES (?, NULL, ?)",
            ("5.5.5.5", 1000),
        )
        self.assertTrue(self.resolver._should_lookup("5.5.5.5", now=1000 + 48 * 3600))

    def test_skips_already_resolved(self):
        self.conn.execute(
            "INSERT INTO dns_cache (ip, hostname, resolved_at) VALUES (?, ?, ?)",
            ("8.8.8.8", "dns.google", 1000),
        )
        self.assertFalse(self.resolver._should_lookup("8.8.8.8", now=1000 + 86400))


if __name__ == "__main__":
    unittest.main()
