#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install.sh [-h|--help]

Render the LaunchAgent plist templates, bootstrap and start the AppBand
collector and server agents (idempotent — safe to re-run), then open the
dashboard at http://127.0.0.1:8765/.

  Data: ~/Library/Application Support/appband/
  Logs: ~/Library/Logs/appband/
EOF
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
DATA_DIR="$HOME/Library/Application Support/appband"
LOG_DIR="$HOME/Library/Logs/appband"

mkdir -p "$LAUNCH_AGENTS" "$DATA_DIR" "$LOG_DIR"

for label in collector server; do
  src="$PROJECT_ROOT/launchd/dev.appband.${label}.plist.template"
  dst="$LAUNCH_AGENTS/dev.appband.${label}.plist"
  sed -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
      -e "s|__LOG_DIR__|$LOG_DIR|g" \
      "$src" > "$dst"
  launchctl bootout "gui/$UID/dev.appband.${label}" 2>/dev/null || true
  launchctl bootstrap "gui/$UID" "$dst"
  launchctl enable "gui/$UID/dev.appband.${label}"
  echo "loaded: $dst"
done

echo
echo "AppBand installed. Dashboard: http://127.0.0.1:8765/"
echo "Logs: $LOG_DIR"
echo "Data: $DATA_DIR"
open http://127.0.0.1:8765/ 2>/dev/null || true
