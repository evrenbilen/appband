#!/usr/bin/env bash
# Build AppBand-<VERSION>.dmg from AppBand.app
# Usage: ./build-dmg.sh <version>
# Example: ./build-dmg.sh 0.1.0

set -euo pipefail

VERSION="${1:?usage: $0 <version>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/AppBand.app"
DMG="$HERE/AppBand-$VERSION.dmg"

[ -d "$APP" ] || { echo "AppBand.app not found at $APP; run ./build.sh first"; exit 1; }
rm -f "$DMG"

if command -v create-dmg >/dev/null 2>&1; then
  echo "=== Using create-dmg ==="
  create-dmg \
    --volname "AppBand $VERSION" \
    --background "$HERE/dmg-assets/background.png" \
    --window-pos 200 120 \
    --window-size 600 320 \
    --icon-size 96 \
    --icon "AppBand.app" 150 160 \
    --hide-extension "AppBand.app" \
    --app-drop-link 450 160 \
    --no-internet-enable \
    "$DMG" "$APP" 2>&1 | tail -10
else
  echo "=== Using hdiutil (fallback) ==="
  STAGE="$HERE/.dmg-stage"
  rm -rf "$STAGE"
  mkdir -p "$STAGE"
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  hdiutil create \
    -volname "AppBand $VERSION" \
    -srcfolder "$STAGE" \
    -ov -format UDZO \
    "$DMG"
  rm -rf "$STAGE"
fi

[ -f "$DMG" ] || { echo "DMG was not produced"; exit 1; }

echo
echo "DMG built: $DMG"
ls -lh "$DMG"
shasum -a 256 "$DMG"
