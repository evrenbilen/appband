"""Parse `nettop -P -x -L 1 -J bytes_in,bytes_out` output.

Real macOS nettop output format (observed on macOS 15.x):
  - First row is the column-name row: ",bytes_in,bytes_out,"
  - Remaining rows are process rows: "<process_name>.<pid>,<bytes_in>,<bytes_out>,"
  - No "time" header row or timestamp row in real output.

Synthetic/multi-run format may also include:
  - A "time,,,,\n" header row
  - A timestamp row like "12:34:56.789012,,,,\n"
  - followed by the column-name row and process rows

Each process row's first column is "<process_name>.<pid>"; the process name
may itself contain dots (e.g., "com.apple.WebKit.Networking.999"), so we
split on the *last* dot to separate name from pid.

We tolerate extra trailing empty columns macOS adds.
"""
from __future__ import annotations


def _split_name_pid(token: str) -> tuple[str, int | None]:
    """Split 'name.pid' tail; process name may contain dots."""
    if "." not in token:
        return token, None
    name, _, pid_str = token.rpartition(".")
    if not pid_str.isdigit():
        return token, None
    return name, int(pid_str)


def parse_nettop(text: str) -> list[dict]:
    """Return a list of {'process_name', 'pid', 'bytes_in', 'bytes_out'}."""
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("time,") or line.startswith(","):
            # header, timestamp, or column-name row (starts with comma)
            continue
        parts = [p.strip() for p in line.split(",")]
        # parts: [name.pid, bytes_in, bytes_out, ...]
        if len(parts) < 3:
            continue
        name_pid = parts[0]
        try:
            bytes_in = int(parts[1])
            bytes_out = int(parts[2])
        except ValueError:
            continue
        name, pid = _split_name_pid(name_pid)
        rows.append(
            {
                "process_name": name,
                "pid": pid,
                "bytes_in": bytes_in,
                "bytes_out": bytes_out,
            }
        )
    return rows
