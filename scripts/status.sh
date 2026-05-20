#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="$HOME/Library/Application Support/netmon"
LOG_DIR="$HOME/Library/Logs/netmon"
DB="$DATA_DIR/netmon.db"

echo "== launchctl =="
launchctl list | grep netmon || echo "(no netmon services loaded)"

echo
echo "== DB =="
if [[ -f "$DB" ]]; then
  size=$(du -h "$DB" | cut -f1)
  echo "Size: $size"
  sqlite3 "$DB" "
    SELECT 'sessions: '          || COUNT(*) FROM sessions;
    SELECT 'interface_samples: ' || COUNT(*) FROM interface_samples;
    SELECT 'process_samples: '   || COUNT(*) FROM process_samples;
    SELECT 'connections: '       || COUNT(*) FROM connections;
    SELECT 'dns_cache: '         || COUNT(*) FROM dns_cache;
    SELECT 'last sample ts: '    || COALESCE(datetime(MAX(ts), 'unixepoch', 'localtime'), 'none')
      FROM interface_samples;
  "
else
  echo "(no DB at $DB)"
fi

echo
echo "== last log lines =="
for f in "$LOG_DIR/collector.log" "$LOG_DIR/server.log"; do
  if [[ -f "$f" ]]; then
    echo "--- $f ---"
    tail -5 "$f"
  fi
done
