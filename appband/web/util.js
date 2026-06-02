// Pure, dependency-free formatting/encoding helpers shared by the dashboard.
// Kept separate from app.js (the browser app shell, which touches the DOM,
// fetch, Chart.js and i18n) so these can be unit-tested in plain Node with no
// browser — see e2e/unit/util.test.mjs.

/** Format bytes to a human-readable string with 1 decimal beyond MB. */
export const fmtBytes = (n) => {
  if (n == null || isNaN(n)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  const decimals = i >= 2 ? 1 : 0; // 1 decimal for MB and above
  return `${n.toFixed(decimals)} ${units[i]}`;
};

/** Format throughput: bytes-per-second → "1.23" (Mbps string, 2 decimals). */
export const fmtMbps = (bytesPerSec) => {
  const mbps = (bytesPerSec * 8) / 1_000_000;
  return mbps.toFixed(2);
};

/**
 * Format a fixed duration (seconds between two known points) → "2h 5m" / "8m" / "12s".
 * Anchored to two known timestamps, not "now" (cf. app.js fmtUptime).
 */
export const fmtDur = (secs) => {
  if (secs == null || secs < 0) return "—";
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return m ? `${h}h ${m}m` : `${h}h`;
};

/** Escape HTML to prevent injection in innerHTML sinks. */
export const esc = (s) =>
  String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/**
 * Serialize an array of row objects to RFC-4180 CSV. The header is the first
 * row's keys; cells containing comma/quote/newline are quoted, and embedded
 * quotes are doubled. Returns "" for an empty/missing array.
 */
export function toCsv(rows) {
  if (!rows || rows.length === 0) return "";
  const cols = Object.keys(rows[0]);
  const cell = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const head = cols.join(",");
  const body = rows.map((r) => cols.map((c) => cell(r[c])).join(",")).join("\n");
  return `${head}\n${body}\n`;
}

/** Parse a <input type="date"> value ("YYYY-MM-DD") to a local-midnight unix ts (or null). */
export function parseDateInput(val) {
  if (!val) return null;
  const [y, m, d] = val.split("-").map(Number);
  if (!y || !m || !d) return null;
  return Math.floor(new Date(y, m - 1, d).getTime() / 1000);
}
