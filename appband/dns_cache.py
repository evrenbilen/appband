"""Async reverse-DNS resolver with persistent SQLite cache."""
from __future__ import annotations

import asyncio
import socket
import sqlite3
import time

from appband.db import upsert_dns

FAILURE_RETRY_SEC = 24 * 3600
SUCCESS_RETRY_SEC = 90 * 24 * 3600


class DnsResolver:
    def __init__(
        self,
        conn: sqlite3.Connection,
        timeout: float = 2.0,
        concurrency: int = 5,
    ):
        self.conn = conn
        self.timeout = timeout
        self.sem = asyncio.Semaphore(concurrency)
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    def _should_lookup(self, ip: str, now: int) -> bool:
        cur = self.conn.execute(
            "SELECT hostname, resolved_at FROM dns_cache WHERE ip = ?", (ip,)
        )
        row = cur.fetchone()
        if row is None:
            return True
        hostname, resolved_at = row
        if hostname is not None:
            return (now - resolved_at) > SUCCESS_RETRY_SEC
        return (now - resolved_at) > FAILURE_RETRY_SEC

    async def _lookup(self, ip: str) -> str:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: socket.gethostbyaddr(ip)[0]),
            timeout=self.timeout,
        )

    async def _resolve_one(self, ip: str, now: int | None = None) -> None:
        if now is None:
            now = int(time.time())
        async with self.sem:
            try:
                host = await self._lookup(ip)
                upsert_dns(self.conn, ip=ip, hostname=host, resolved_at=now)
            except (socket.herror, socket.gaierror, asyncio.TimeoutError, OSError):
                upsert_dns(self.conn, ip=ip, hostname=None, resolved_at=now)

    def enqueue(self, ip: str) -> None:
        """Synchronously hand an IP to the running event loop's queue."""
        self.queue.put_nowait(ip)

    async def run_forever(self) -> None:
        while True:
            ip = await self.queue.get()
            now = int(time.time())
            if self._should_lookup(ip, now):
                await self._resolve_one(ip, now=now)
            self.queue.task_done()
