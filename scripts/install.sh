#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
DATA_DIR="$HOME/Library/Application Support/netmon"
LOG_DIR="$HOME/Library/Logs/netmon"

mkdir -p "$LAUNCH_AGENTS" "$DATA_DIR" "$LOG_DIR"

for label in collector server; do
  src="$PROJECT_ROOT/launchd/com.evren.netmon.${label}.plist.template"
  dst="$LAUNCH_AGENTS/com.evren.netmon.${label}.plist"
  sed -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
      -e "s|__LOG_DIR__|$LOG_DIR|g" \
      "$src" > "$dst"
  launchctl bootout "gui/$UID/com.evren.netmon.${label}" 2>/dev/null || true
  launchctl bootstrap "gui/$UID" "$dst"
  launchctl enable "gui/$UID/com.evren.netmon.${label}"
  echo "loaded: $dst"
done

echo
echo "netmon installed. Dashboard: http://127.0.0.1:8765/"
echo "Logs: $LOG_DIR"
echo "Data: $DATA_DIR"
open http://127.0.0.1:8765/ 2>/dev/null || true
