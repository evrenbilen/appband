// Playwright config for AppBand dashboard e2e tests.
// The webServer launches the real working-tree appband.server against a
// freshly-seeded temp DB (serve-test.py) on a dedicated port, so tests are
// deterministic and never touch the user's real DB or the installed instance.
const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: true,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:8799",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "PYTHONPATH=.. python3 serve-test.py",
    url: "http://127.0.0.1:8799/api/current",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
