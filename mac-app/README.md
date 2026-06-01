# AppBand menu bar app

A small native macOS menu bar app that wraps the AppBand backend.

## Build

```bash
cd mac-app
./build.sh
open AppBand.app    # double-click works too
```

The build produces `AppBand.app` in this directory.

## What it does on first launch

1. Copies the Python backend out of `AppBand.app/Contents/Resources/backend/` into `~/Library/Application Support/AppBand/backend/`
2. Runs `scripts/install.sh` from the copied backend, which installs and starts the LaunchAgents `dev.appband.collector` and `dev.appband.server`
3. Begins polling `http://127.0.0.1:8765/api/current` every 5 seconds to show live throughput

## Uninstall

Quitting the menu bar app does NOT stop the LaunchAgents. To uninstall:

```bash
~/Library/Application\ Support/AppBand/backend/scripts/uninstall.sh
# or to also delete the database:
~/Library/Application\ Support/AppBand/backend/scripts/uninstall.sh --purge
```

Then drag `AppBand.app` to the Trash.
