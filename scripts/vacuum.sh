#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: vacuum.sh [-h|--help]

Compact the AppBand SQLite database (VACUUM) and report the size before
and after.
EOF
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

DB="$HOME/Library/Application Support/appband/appband.db"
if [[ ! -f "$DB" ]]; then
  echo "No DB at $DB"
  exit 1
fi
before=$(du -h "$DB" | cut -f1)
sqlite3 "$DB" "VACUUM;"
after=$(du -h "$DB" | cut -f1)
echo "VACUUM: $before -> $after"
