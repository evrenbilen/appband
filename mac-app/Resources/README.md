# Resources placeholder

The Python backend gets bundled here at build time by `build.sh`.

During `build.sh`, the following directories from the repo root are copied into
`AppBand.app/Contents/Resources/backend/`:

- `appband/`   — Python collector + server + web dashboard
- `launchd/`   — LaunchAgent plist templates
- `scripts/`   — install.sh, uninstall.sh, status.sh, vacuum.sh

Do not commit build output here. The `backend/` subdirectory (if present locally
after a build) is git-ignored.
