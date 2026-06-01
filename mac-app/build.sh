#!/usr/bin/env bash
# Build AppBand.app from the swift sources + bundle the Python backend.
# Usage: ./build.sh   (run from mac-app/)

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
APP="$HERE/AppBand.app"

echo "=== 1. Clean previous app ==="
rm -rf "$APP"

echo "=== 2. Build Swift binary (release) ==="
cd "$HERE"
# Try universal (arm64+x86_64) first; fall back to native arch
if swift build -c release --arch arm64 --arch x86_64 2>/dev/null; then
    # Universal build goes to .build/apple/Products/Release/
    BIN="$HERE/.build/apple/Products/Release/AppBand"
else
    swift build -c release
    BIN="$HERE/.build/release/AppBand"
    [ -f "$BIN" ] || BIN="$HERE/.build/$(uname -m)-apple-macosx/release/AppBand"
fi
[ -f "$BIN" ] || { echo "swift binary not found"; exit 1; }

echo "=== 3. Assemble .app bundle ==="
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/AppBand"
cp "$HERE/Sources/AppBand/Info.plist" "$APP/Contents/Info.plist"

echo "=== 4. Bundle Python backend into Resources ==="
mkdir -p "$APP/Contents/Resources/backend"
# Copy only what the runtime needs
cp -R "$REPO/appband"   "$APP/Contents/Resources/backend/"
cp -R "$REPO/launchd"   "$APP/Contents/Resources/backend/"
cp -R "$REPO/scripts"   "$APP/Contents/Resources/backend/"
# Trim caches
find "$APP/Contents/Resources/backend" -name "__pycache__" -type d -exec rm -rf {} +
find "$APP/Contents/Resources/backend" -name "*.pyc" -delete

echo "=== 5. Ad-hoc code-sign ==="
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "=== 6. Done ==="
echo "Built: $APP"
du -sh "$APP" | awk '{print "Size:", $1}'
