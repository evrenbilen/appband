# Contributing to AppBand

Thanks for your interest in improving AppBand.

## Ground rules

- **No third-party Python dependencies.** AppBand is stdlib-only on purpose. If you need a feature that would require `pip install`, open an issue first to discuss.
- **macOS-only.** AppBand targets macOS (currently tested on Sequoia / Sonoma). Linux/Windows support is out of scope.
- **Localhost-only.** The server binds to `127.0.0.1`. PRs that expose any network surface to the outside world will not be accepted.

## Development setup

```bash
git clone https://github.com/evrenbilen/appband ~/Development/appband
cd ~/Development/appband
./scripts/install.sh   # installs as LaunchAgents
```

Open `http://127.0.0.1:8765/` and you have a live dashboard fed by your real network activity.

## Running tests

```bash
python3 -m unittest discover tests -v
```

All tests use the stdlib `unittest` module — no `pytest`, no fixtures framework.

### Frontend / e2e tests (`e2e/`)

The web dashboard is exercised end-to-end with **Playwright (Node)**, run in a
headless browser:

```bash
cd e2e
npm install
npx playwright install chromium   # one-time browser download
npm test                          # launches the server on a seeded temp DB + runs specs
```

This is **dev-only test tooling and does not affect the backend's stdlib-only /
no-`pip` constraint** — it is Node, lives entirely under `e2e/`, ships in
nothing, and is never imported by `appband`. `e2e/serve-test.py` boots the real
working-tree server against a freshly-seeded temp DB on port 8799, so e2e runs
are deterministic and never touch your real DB or an installed instance.

## Code style

- Python 3.10+ type hints where they help
- `from __future__ import annotations` at the top of every module
- Small focused modules — one responsibility per file
- Tests next to behavior they verify; mock subprocess boundaries, not internal logic

## Adding a new locale

1. Copy `appband/web/locales/en.json` to `appband/web/locales/<lang>.json`
2. Translate the values (keep keys identical)
3. Add a button to the language toggle in `appband/web/index.html` (`<button data-lang="<lang>">XX</button>`)

No JS changes needed — the i18n module auto-loads any locale referenced by the toggle.

## Reporting bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) and include:

- macOS version
- Commit SHA you're running
- Relevant log excerpts from `~/Library/Logs/appband/`
- Output of `./scripts/status.sh`

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](./LICENSE).
