#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: uninstall.sh [--purge] [-h|--help]

Stop and remove the AppBand LaunchAgents. The collected database is kept
unless --purge is given.

  --purge   Also delete the collected database.
EOF
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
DATA_DIR="$HOME/Library/Application Support/appband"
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

for label in collector server; do
  plist="$LAUNCH_AGENTS/dev.appband.${label}.plist"
  launchctl bootout "gui/$UID/dev.appband.${label}" 2>/dev/null || true
  rm -f "$plist"
  echo "removed: $plist"
done

if [[ $PURGE -eq 1 ]]; then
  rm -rf "$DATA_DIR"
  echo "purged: $DATA_DIR"
else
  echo "Data kept at $DATA_DIR (use --purge to delete)."
fi
