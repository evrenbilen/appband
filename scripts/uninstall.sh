#!/usr/bin/env bash
set -euo pipefail

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
DATA_DIR="$HOME/Library/Application Support/netmon"
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

for label in collector server; do
  plist="$LAUNCH_AGENTS/com.evren.netmon.${label}.plist"
  launchctl bootout "gui/$UID/com.evren.netmon.${label}" 2>/dev/null || true
  rm -f "$plist"
  echo "removed: $plist"
done

if [[ $PURGE -eq 1 ]]; then
  rm -rf "$DATA_DIR"
  echo "purged: $DATA_DIR"
else
  echo "Data kept at $DATA_DIR (use --purge to delete)."
fi
