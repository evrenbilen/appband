const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  webServer: {
    command: "PYTHONPATH=.. python3 serve-test-broken.py",
    url: "http://127.0.0.1:8799/api/current",
    reuseExistingServer: false,
    timeout: 5_000,
  },
});
