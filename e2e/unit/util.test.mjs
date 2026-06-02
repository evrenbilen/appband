// Unit tests for the pure dashboard helpers in appband/web/util.js.
// Plain Node (node:test + node:assert) — no browser, no deps. These cover the
// edge cases the Playwright e2e (which runs against fixed seed data) can't:
// CSV quoting of comma/quote/newline, invalid date input, byte-unit boundaries.
//
// Run: node --test e2e/unit/   (CI runs this in the e2e job)
import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtBytes, fmtMbps, fmtDur, esc, toCsv, parseDateInput } from "../../appband/web/util.js";

test("fmtBytes scales units and decimals", () => {
  assert.equal(fmtBytes(0), "0 B");
  assert.equal(fmtBytes(512), "512 B");
  assert.equal(fmtBytes(1024), "1 KB");
  assert.equal(fmtBytes(1536), "2 KB"); // <MB → 0 decimals → 1.5 rounds to 2
  assert.equal(fmtBytes(1024 * 1024), "1.0 MB");
  assert.equal(fmtBytes(1024 ** 3), "1.0 GB");
  assert.equal(fmtBytes(1024 ** 4), "1.0 TB");
  assert.equal(fmtBytes(null), "—");
  assert.equal(fmtBytes(NaN), "—");
});

test("fmtMbps converts bytes/sec to a 2-decimal Mbps string", () => {
  assert.equal(fmtMbps(0), "0.00");
  assert.equal(fmtMbps(125000), "1.00"); // 125000 B/s * 8 / 1e6 = 1 Mbps
  assert.equal(fmtMbps(1_000_000), "8.00");
});

test("fmtDur formats fixed spans and guards negatives/null", () => {
  assert.equal(fmtDur(0), "0s");
  assert.equal(fmtDur(45), "45s");
  assert.equal(fmtDur(90), "1m");
  assert.equal(fmtDur(3600), "1h");
  assert.equal(fmtDur(3660), "1h 1m");
  assert.equal(fmtDur(7320), "2h 2m");
  assert.equal(fmtDur(-5), "—");
  assert.equal(fmtDur(null), "—");
});

test("esc neutralizes HTML metacharacters", () => {
  assert.equal(esc("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;");
  assert.equal(esc("a & b < c"), "a &amp; b &lt; c");
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
  assert.equal(esc(42), "42");
});

test("toCsv emits a header row and applies RFC-4180 quoting", () => {
  assert.equal(toCsv([]), "");
  assert.equal(toCsv(null), "");
  assert.equal(toCsv([{ a: 1, b: 2 }]), "a,b\n1,2\n");
  // comma + embedded quote (doubled) must be quoted
  assert.equal(
    toCsv([{ name: "a,b", note: 'say "hi"' }]),
    'name,note\n"a,b","say ""hi"""\n'
  );
  // embedded newline must be quoted
  assert.equal(toCsv([{ x: "line1\nline2" }]), 'x\n"line1\nline2"\n');
  // null/undefined become empty cells
  assert.equal(toCsv([{ a: null, b: undefined }]), "a,b\n,\n");
  // header is taken from the first row's keys
  assert.equal(toCsv([{ port: 443, service: "HTTPS" }]), "port,service\n443,HTTPS\n");
});

test("parseDateInput → local-midnight unix ts, null on bad input", () => {
  assert.equal(parseDateInput(""), null);
  assert.equal(parseDateInput(null), null);
  assert.equal(parseDateInput("not-a-date"), null);
  assert.equal(parseDateInput("2026-13"), null); // missing day component
  const ts = parseDateInput("2026-05-10");
  assert.equal(ts, Math.floor(new Date(2026, 4, 10).getTime() / 1000));
  // a one-day window spans exactly 86400s (the dashboard's custom-range assumption)
  assert.equal(parseDateInput("2026-05-11") - ts, 86_400);
});
