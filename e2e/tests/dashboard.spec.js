// e2e coverage for the P0-B dashboard + the P0-A self-hosted/CSP posture.
const { test, expect } = require("@playwright/test");

test.describe("AppBand dashboard", () => {
  test("loads with no JS errors and makes zero external requests", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    const external = [];
    page.on("request", (r) => {
      const host = new URL(r.url()).hostname;
      if (host !== "127.0.0.1" && host !== "localhost") external.push(r.url());
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Self-hosted Chart.js + strict CSP ⇒ nothing leaves localhost.
    expect(external, "no external (CDN) requests").toEqual([]);
    expect(errors, "no console/page errors").toEqual([]);
  });

  test("serves a strict CSP and nosniff header", async ({ request }) => {
    const res = await request.get("/");
    expect(res.status()).toBe(200);
    const csp = res.headers()["content-security-policy"] || "";
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("script-src 'self'");
    expect(res.headers()["x-content-type-options"]).toBe("nosniff");
  });

  test("LIVE panel shows exact top apps, info tooltip, and coverage chip", async ({ page }) => {
    await page.goto("/");
    const rows = page.locator(".topapps-list .topapps-row");
    await expect(rows.first()).toBeVisible({ timeout: 10_000 });
    expect(await rows.count()).toBeGreaterThan(0);
    // Safari is seeded as the heaviest app → ranks first.
    await expect(rows.first()).toContainText("Safari");
    // ⓘ tooltip clarifies that "now" means the last 60 seconds (EN or TR).
    await expect(page.locator(".live-topapps-title .info-icon")).toHaveAttribute(
      "title",
      /60 seconds|60 saniye/
    );
    await expect(page.locator(".coverage-chip")).toContainText("%");
  });

  test("By Network is a compact doughnut beside the table (not a full-width square)", async ({ page }) => {
    await page.goto("/");
    const canvas = page.locator(".network-layout .network-chart canvas#chart-network");
    await expect(canvas).toBeVisible({ timeout: 10_000 });
    const box = await page.locator(".network-chart").boundingBox();
    expect(box.height).toBeLessThan(320); // old bug rendered it ~700px tall
    await expect(page.locator(".network-layout .data-table")).toBeVisible();
  });

  test('selecting "Last hour" requests minute granularity', async ({ page }) => {
    await page.goto("/");
    const req = page.waitForRequest(
      (r) => r.url().includes("/api/timeseries") && r.url().includes("granularity=minute"),
      { timeout: 10_000 }
    );
    await page.selectOption("#range", "3600");
    await req; // throws if the minute-granularity request is never made
  });

  test("selecting a network scopes the analytics requests", async ({ page }) => {
    // The SSID filter was dead (state.ssid was never sent). Selecting TestNet
    // (the seeded active Wi-Fi network) must now scope the API requests.
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    const req = page.waitForRequest(
      (r) => r.url().includes("/api/by-process") && r.url().includes("ssid=TestNet"),
      { timeout: 10_000 }
    );
    await page.selectOption("#ssid", "TestNet");
    await req; // throws if the network-scoped request is never made
  });

  test("By Domain shows a visible approximate badge with an explainer", async ({ page }) => {
    await page.goto("/");
    const badge = page.locator("#panel-domain .approx-badge");
    await expect(badge).toBeVisible();
    // The explainer title is applied by i18n applyDom after load — poll for it
    // (toHaveAttribute auto-retries) rather than read synchronously, which raced.
    await expect(badge).toHaveAttribute("title", /.{15,}/, { timeout: 10_000 });
  });

  test("a collection gap is surfaced on the Time Series panel", async ({ page }) => {
    // serve-test.py seeds a gap ~30 min ago, within the default Today range.
    await page.goto("/");
    await expect(page.locator("#panel-timeseries .gap-note")).toBeVisible({ timeout: 10_000 });
  });

  test("By Port lists ports with service labels", async ({ page }) => {
    // serve-test.py seeds connections to :443; /api/by-port labels it HTTPS.
    await page.goto("/");
    const table = page.locator("#panel-port .data-table");
    await expect(table).toBeVisible({ timeout: 10_000 });
    await expect(table).toContainText("443");
    await expect(table).toContainText("HTTPS");
  });

  test("exports the By App panel as CSV", async ({ page }) => {
    await page.goto("/");
    // Wait for the By App chart to render (data fetched + cached for export).
    await expect(page.locator("#panel-process #chart-process")).toBeVisible({ timeout: 10_000 });
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#export-process"),
    ]);
    expect(download.suggestedFilename()).toContain("by-app");
    const fs = require("fs");
    const content = fs.readFileSync(await download.path(), "utf8");
    expect(content).toContain("process_name"); // header row from the row keys
    expect(content).toContain("Safari"); // seeded app with internet traffic
  });

  test("custom date range drives the from/to query window", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    // Selecting "Custom" reveals the date inputs.
    await page.selectOption("#range", "custom");
    await expect(page.locator("#custom-range")).toBeVisible();
    // A single-day window (same from/to) must request exactly 86400s of data,
    // independent of timezone (both bounds are computed as local midnights).
    await page.fill("#from-date", "2026-05-10");
    await page.fill("#to-date", "2026-05-10");
    const req = page.waitForRequest(
      (r) => r.url().includes("/api/timeseries"),
      { timeout: 10_000 }
    );
    await page.click("#apply-range");
    const url = new URL((await req).url());
    const from = Number(url.searchParams.get("from"));
    const to = Number(url.searchParams.get("to"));
    expect(to - from).toBe(86_400);
  });

  test("Session History lists past + active sessions", async ({ page }) => {
    // serve-test.py seeds an active Wi-Fi "TestNet" session and an ended
    // Ethernet session; /api/sessions returns both within the Today range.
    await page.goto("/");
    const table = page.locator("#panel-history .data-table");
    await expect(table).toBeVisible({ timeout: 10_000 });
    await expect(table).toContainText("TestNet"); // the active Wi-Fi session
    await expect(table).toContainText("Ethernet"); // the ended SSID-less session
    // The active session (ended_at IS NULL) is flagged, not given a duration.
    await expect(table.locator(".session-active")).toBeVisible();
  });
});
