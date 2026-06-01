"""Launch the working-tree appband.server against a freshly-seeded temp DB on
port 8799 for Playwright e2e tests. Deterministic data; never touches the real
DB. Killed by Playwright when the run finishes."""
import os
import sqlite3
import tempfile
import time
from pathlib import Path

from appband.db import (
    close_session,
    init_schema,
    insert_connection,
    insert_interface_sample,
    insert_process_sample,
    open_session,
    upsert_dns,
)
from appband.server import NetmonServer, build_handler

fd, dbf = tempfile.mkstemp(suffix=".db")
os.close(fd)
c = sqlite3.connect(dbf)
init_schema(c)
now = int(time.time())

# Active Wi-Fi session + a second ended Ethernet session (so By Network has >1 slice).
sid = open_session(c, now - 3600, "en0", "wifi", "TestNet", None, "192.168.0.50")
sid2 = open_session(c, now - 7200, "en5", "ethernet", None, None, "10.0.0.5")
close_session(c, sid2, now - 3601)

# Very recent samples for the live (last-60s) top-apps + coverage view.
for off in (3, 8, 13, 20, 35, 50):
    ts = now - off
    insert_interface_sample(c, ts=ts, session_id=sid, bytes_in=1_000_000, bytes_out=300_000)
    insert_process_sample(c, ts=ts, session_id=sid, process_name="Safari", pid=101, bytes_in=600_000, bytes_out=120_000)
    insert_process_sample(c, ts=ts, session_id=sid, process_name="Mail", pid=102, bytes_in=40_000, bytes_out=8_000)
    insert_process_sample(c, ts=ts, session_id=sid, process_name="Chrome", pid=103, bytes_in=150_000, bytes_out=30_000)

# Older minutes within the last hour for the minute-granularity chart.
for m in range(2, 12):
    ts = now - m * 60 - 10
    insert_interface_sample(c, ts=ts, session_id=sid, bytes_in=500_000, bytes_out=100_000)
    insert_process_sample(c, ts=ts, session_id=sid, process_name="Safari", pid=101, bytes_in=300_000, bytes_out=60_000)

# Connections + DNS so by-domain / scoped by-process have content.
insert_connection(c, ts=now - 10, session_id=sid, process_name="Safari", remote_ip="142.250.1.1", remote_port=443, protocol="tcp", scope="internet")
insert_connection(c, ts=now - 10, session_id=sid, process_name="Chrome", remote_ip="151.101.1.1", remote_port=443, protocol="tcp", scope="internet")
upsert_dns(c, ip="142.250.1.1", hostname="google.com", resolved_at=now - 10)
upsert_dns(c, ip="151.101.1.1", hostname="fastly.net", resolved_at=now - 10)
# Traffic on the ended Ethernet session for the second doughnut slice.
insert_interface_sample(c, ts=now - 3600, session_id=sid2, bytes_in=2_000_000, bytes_out=500_000)

c.commit()
c.close()

srv = NetmonServer(("127.0.0.1", 8799), build_handler(Path(dbf)))
print(f"e2e test server on http://127.0.0.1:8799  (db={dbf})", flush=True)
srv.serve_forever()
