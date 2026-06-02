"""AppBand — per-app bandwidth & network monitor for macOS."""
from __future__ import annotations

# Single source of truth for the version. mac-app/build.sh injects this into
# Info.plist's CFBundleShortVersionString, and the README download links are
# checked against it by tests/test_version.py.
__version__ = "0.2.0"
