#!/usr/bin/env bash
set -euo pipefail

DB="$HOME/Library/Application Support/netmon/netmon.db"
if [[ ! -f "$DB" ]]; then
  echo "No DB at $DB"
  exit 1
fi
before=$(du -h "$DB" | cut -f1)
sqlite3 "$DB" "VACUUM;"
after=$(du -h "$DB" | cut -f1)
echo "VACUUM: $before -> $after"
