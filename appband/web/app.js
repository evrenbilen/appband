"use strict";

import { t, initI18n, setLocale, currentLocale, applyDom } from "/static/i18n.js";

/* ─── Helpers ────────────────────────────────────────────────────────────── */
const $ = (id) => document.getElementById(id);

/**
 * Format bytes to human-readable string with 1 decimal beyond MB.
 */
const fmtBytes = (n) => {
  if (n == null || isNaN(n)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  const decimals = i >= 2 ? 1 : 0; // 1 decimal for MB and above
  return `${n.toFixed(decimals)} ${units[i]}`;
};

/**
 * Format throughput: bytes-per-second → "1.23 Mbps"
 */
const fmtMbps = (bytesPerSec) => {
  const mbps = (bytesPerSec * 8) / 1_000_000;
  return mbps.toFixed(2);
};

/**
 * Format a unix timestamp into a locale string.
 */
const fmtTime = (ts) => new Date(ts * 1000).toLocaleString();

/**
 * Format relative duration (seconds → "3s 12m" etc).
 */
const fmtUptime = (startedAt) => {
  const secs = Math.floor(Date.now() / 1000) - startedAt;
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return `${h}h ${m}m`;
};

/**
 * Format a fixed duration (in seconds) between two timestamps → "2h 5m" / "8m" / "12s".
 * Unlike fmtUptime this is anchored to two known points, not "now".
 */
const fmtDur = (secs) => {
  if (secs == null || secs < 0) return "—";
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return m ? `${h}h ${m}m` : `${h}h`;
};

/**
 * Escape HTML to prevent injection.
 */
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/**
 * Map a raw link_type slug to a localized label.
 */
function linkTypeLabel(raw) {
  const slug = (raw || "unknown").replaceAll("-", "_");
  const key = `link_type.${slug}`;
  const out = t(key);
  return out === key ? (raw || "unknown") : out;
}

/* ─── State ──────────────────────────────────────────────────────────────── */
const state = {
  range: 86400,
  ssid: "",
  linkType: "",   // set instead of ssid for SSID-less networks (e.g. Ethernet)
  scope: "internet",
  charts: {},
  exports: {},   // last-fetched rows per panel, for CSV export
};

/* ─── CSV export (client-side only; no upload — keeps the localhost contract) ── */
function toCsv(rows) {
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

function downloadCsv(filename, rows) {
  const csv = toCsv(rows);
  if (!csv) return; // nothing loaded yet — no-op rather than an empty file
  // Blob + object URL: a same-document download, so the strict CSP (which has no
  // connect-src) is never engaged and nothing leaves localhost.
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* ─── Fetch ─────────────────────────────────────────────────────────────── */
async function fetchJson(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json();
}

function rangeBounds() {
  const now = Math.floor(Date.now() / 1000);
  // Custom mode: use the applied [from, to) window once both bounds are set.
  if (state.range === "custom" && state.customFrom != null && state.customTo != null) {
    return { from: state.customFrom, to: state.customTo };
  }
  const lookback = state.range === "custom" ? 86400 : state.range;
  return { from: now - lookback, to: now };
}

/** Parse a <input type="date"> value ("YYYY-MM-DD") to a local-midnight unix ts. */
function parseDateInput(val) {
  if (!val) return null;
  const [y, m, d] = val.split("-").map(Number);
  if (!y || !m || !d) return null;
  return Math.floor(new Date(y, m - 1, d).getTime() / 1000);
}

/** Query suffix scoping a request to the selected network (or "" for all). */
function netParam() {
  if (state.ssid) return `&ssid=${encodeURIComponent(state.ssid)}`;
  if (state.linkType) return `&link_type=${encodeURIComponent(state.linkType)}`;
  return "";
}

/* ─── Chart.js shared config ─────────────────────────────────────────────── */

/**
 * Returns Chart.js options shared by all charts: gridlines, tooltip, font.
 * @param {'light'|'auto'} _mode — reserved for future explicit theming
 */
function commonOptions(overrides = {}) {
  const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const gridColor = isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)";
  const tickColor = isDark ? "#636366" : "#aeaeb2";
  const tooltipBg = isDark ? "#2c2c2e" : "#1d1d1f";
  const tooltipBorder = isDark ? "#3a3a3c" : "transparent";

  return mergeDeep({
    responsive: true,
    animation: { duration: 250 },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: tooltipBg,
        titleColor: "#f5f5f7",
        bodyColor: "#aeaeb2",
        borderColor: tooltipBorder,
        borderWidth: 1,
        padding: { x: 12, y: 10 },
        cornerRadius: 8,
        boxPadding: 4,
        titleFont: { family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif", size: 12, weight: "600" },
        bodyFont: { family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif", size: 12 },
      },
    },
    scales: {
      x: {
        grid: { color: gridColor },
        ticks: { color: tickColor, font: { size: 11 } },
        border: { color: gridColor },
      },
      y: {
        grid: { color: gridColor },
        ticks: { color: tickColor, font: { size: 11 } },
        border: { color: gridColor },
      },
    },
  }, overrides);
}

/**
 * Simple deep merge utility (non-array values overwrite).
 */
function mergeDeep(target, source) {
  const out = Object.assign({}, target);
  for (const key of Object.keys(source)) {
    if (
      source[key] !== null &&
      typeof source[key] === "object" &&
      !Array.isArray(source[key]) &&
      typeof target[key] === "object" &&
      target[key] !== null &&
      !Array.isArray(target[key])
    ) {
      out[key] = mergeDeep(target[key], source[key]);
    } else {
      out[key] = source[key];
    }
  }
  return out;
}

/* ─── Chart create / update ──────────────────────────────────────────────── */
function makeOrUpdateChart(id, config) {
  const canvas = $(id);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (state.charts[id]) {
    const chart = state.charts[id];
    chart.data = config.data;
    chart.options = config.options;
    chart.update("active");
  } else {
    state.charts[id] = new Chart(ctx, config);
  }
}

/* ─── Panel rendering helpers ────────────────────────────────────────────── */

function showEmpty(containerId) {
  const el = $(containerId);
  if (!el) return;
  el.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">📭</div>
      <div>${esc(t("state.empty"))}</div>
    </div>`;
}

function showError(containerId, retryFn) {
  const el = $(containerId);
  if (!el) return;
  el.innerHTML = `
    <div class="error-state">
      <span class="error-icon">⚠</span>
      <span>${esc(t("state.error"))}</span>
      <button class="retry-link" id="retry-${containerId}">${esc(t("state.retry"))}</button>
    </div>`;
  const btn = $(`retry-${containerId}`);
  if (btn && retryFn) btn.addEventListener("click", retryFn);
}

/**
 * Inject a <canvas> into a container, destroying any old chart first.
 */
function ensureCanvas(containerId, chartId, height) {
  // Destroy existing chart if present
  if (state.charts[chartId]) {
    state.charts[chartId].destroy();
    delete state.charts[chartId];
  }
  const container = $(containerId);
  if (!container) return;
  const wrap = document.createElement("div");
  wrap.className = "chart-wrap";
  const canvas = document.createElement("canvas");
  canvas.id = chartId;
  if (height) canvas.height = height;
  wrap.appendChild(canvas);
  container.innerHTML = "";
  container.appendChild(wrap);
}

/* ─── Scope badge sync ───────────────────────────────────────────────────── */
function updateScopeBadges() {
  const label = t(`filters.scope.${state.scope}`) || state.scope;
  for (const id of ["scope-badge-process", "scope-badge-domain"]) {
    const el = $(id);
    if (el) el.textContent = label;
  }
  // By App is exact only at scope=all; show the "approximate" badge otherwise.
  const ab = $("approx-badge-process");
  if (ab) ab.hidden = state.scope === "all";
}

/* ─── Load: Current ──────────────────────────────────────────────────────── */
async function loadCurrent() {
  try {
    const data = await fetchJson("/api/current");
    const body = $("current-body");
    if (!body) return;

    if (!data.session) {
      body.innerHTML = `
        <div class="offline-state">
          <span class="offline-dot"></span>
          ${esc(t("panel.current.offline"))}
        </div>`;
      const badge = $("live-network-badge");
      if (badge) badge.innerHTML = "";
      return;
    }

    const s = data.session;
    const dlMbps = fmtMbps(data.bytes_in_60s / 60);
    const ulMbps = fmtMbps(data.bytes_out_60s / 60);
    const networkLabel = s.ssid || `(${linkTypeLabel(s.link_type)})`;

    // Exact "what is eating my bandwidth right now" — top apps over the last
    // 60s (process_samples bytes are exact, so no approximation caveat) and a
    // coverage chip explaining why per-app sums fall short of the total.
    const cov = data.coverage;
    const coverageChip = (cov && cov.pct != null)
      ? `<span class="coverage-chip" title="${esc(t("panel.current.coverage_help"))}">${esc(t("panel.current.coverage", { pct: cov.pct }))}</span>`
      : "";
    const apps = Array.isArray(data.top_apps) ? data.top_apps : [];
    const topAppsHtml = apps.length
      ? `<ul class="topapps-list">
          ${apps.map((a) => `
            <li class="topapps-row">
              <span class="topapps-name">${esc(a.process_name)}</span>
              <span class="topapps-bytes">${esc(fmtBytes((a.bytes_in || 0) + (a.bytes_out || 0)))}</span>
            </li>`).join("")}
        </ul>`
      : `<div class="topapps-empty">${esc(t("panel.current.no_app_traffic"))}</div>`;

    // Update badge in header
    const badge = $("live-network-badge");
    if (badge) {
      badge.innerHTML = `<span class="live-meta-badge">${esc(networkLabel)}</span>`;
    }

    body.innerHTML = `
      <div class="live-stats">
        <div class="live-stat">
          <div class="live-stat-label"><span class="arrow arrow-down">↓</span> ${esc(t("legend.download"))}</div>
          <div class="live-stat-value download">${esc(dlMbps)}<span class="live-stat-unit">Mbps</span></div>
        </div>
        <div class="live-divider"></div>
        <div class="live-stat">
          <div class="live-stat-label"><span class="arrow arrow-up">↑</span> ${esc(t("legend.upload"))}</div>
          <div class="live-stat-value upload">${esc(ulMbps)}<span class="live-stat-unit">Mbps</span></div>
        </div>
      </div>
      <div class="live-metadata">
        ${s.ssid ? `<span class="meta-chip"><span class="meta-icon">📶</span>${esc(s.ssid)}</span>` : ""}
        <span class="meta-chip"><span class="meta-icon">🔌</span>${esc(s.interface)}</span>
        <span class="meta-chip"><span class="meta-icon">🏷</span>${esc(linkTypeLabel(s.link_type))}</span>
        ${s.ip_address ? `<span class="meta-chip"><span class="meta-icon">🌐</span>${esc(s.ip_address)}</span>` : ""}
        <span class="meta-chip">⏱ ${esc(fmtUptime(s.started_at))}</span>
      </div>
      <div class="live-since">${esc(t("panel.current.started"))}: ${esc(fmtTime(s.started_at))}</div>
      <div class="live-topapps">
        <div class="live-topapps-header">
          <span class="live-topapps-title">${esc(t("panel.current.top_apps"))}<span class="info-icon" title="${esc(t("panel.current.top_apps_help"))}">ⓘ</span></span>
          ${coverageChip}
        </div>
        ${topAppsHtml}
      </div>`;
  } catch (err) {
    showError("current-body", loadCurrent);
  }
}

/* ─── Load: SSID options ─────────────────────────────────────────────────── */
async function loadSsidOptions() {
  try {
    const { from, to } = rangeBounds();
    const data = await fetchJson(`/api/by-network?from=${from}&to=${to}`);
    const sel = $("ssid");
    if (!sel) return;
    const current = sel.value;
    while (sel.options.length > 1) sel.remove(1);
    for (const row of data.rows) {
      const label = row.ssid || `(${linkTypeLabel(row.link_type)})`;
      const opt = document.createElement("option");
      opt.value = label;
      // Carry the real discriminator out-of-band so an SSID can be ANY string
      // (no in-value prefix to collide with). Server filters by ssid OR link_type.
      if (row.ssid) opt.dataset.ssid = row.ssid;
      else opt.dataset.link = row.link_type;
      opt.textContent = label;
      sel.appendChild(opt);
    }
    // Restore selection if still available
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
  } catch (_) {
    // Non-critical; fail silently
  }
}

/* ─── Load: Timeseries ───────────────────────────────────────────────────── */
async function loadTimeseries() {
  const containerId = "timeseries-body";
  try {
    const { from, to } = rangeBounds();
    // Short ranges get fine-grained per-minute buckets so a live download/spike
    // is actually visible; wide ranges stay on hour/day to bound the row count.
    let granularity = "hour";
    if (state.range > 86400 * 2) granularity = "day";
    else if (state.range <= 3600) granularity = "minute";
    const data = await fetchJson(`/api/timeseries?from=${from}&to=${to}&granularity=${granularity}${netParam()}`);

    if (!data.timeseries || data.timeseries.length === 0) {
      showEmpty(containerId);
      return;
    }

    ensureCanvas(containerId, "chart-timeseries", 80);

    const labels = data.timeseries.map((r) => {
      const d = new Date(r.ts * 1000);
      return granularity === "day"
        ? d.toLocaleDateString(undefined, { day: "numeric", month: "short" })
        : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    });

    makeOrUpdateChart("chart-timeseries", {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: t("legend.download"),
            data: data.timeseries.map((r) => r.bytes_in),
            backgroundColor: "rgba(10, 132, 255, 0.85)",
            borderRadius: 4,
            borderSkipped: false,
          },
          {
            label: t("legend.upload"),
            data: data.timeseries.map((r) => r.bytes_out),
            backgroundColor: "rgba(255, 149, 0, 0.85)",
            borderRadius: 4,
            borderSkipped: false,
          },
        ],
      },
      options: commonOptions({
        plugins: {
          tooltip: {
            callbacks: {
              label: (c) => ` ${c.dataset.label}: ${fmtBytes(c.parsed.y)}`,
            },
          },
        },
        scales: {
          y: { ticks: { callback: (v) => fmtBytes(v) } },
        },
      }),
    });

    // Surface collection gaps (sleep/wake) so a flat stretch reads as "we
    // weren't watching", not "zero traffic".
    try {
      const gd = await fetchJson(`/api/gaps?from=${from}&to=${to}`);
      if (gd.gaps && gd.gaps.length) {
        const note = document.createElement("div");
        note.className = "gap-note";
        note.textContent = `⚠ ${t("panel.timeseries.gaps_note", { count: gd.gaps.length })}`;
        $(containerId).prepend(note);
      }
    } catch (_) {
      // Non-critical; the chart already rendered.
    }
  } catch (err) {
    showError(containerId, loadTimeseries);
  }
}

/* ─── Load: By Network ───────────────────────────────────────────────────── */
async function loadByNetwork() {
  const containerId = "network-body";
  try {
    const { from, to } = rangeBounds();
    const data = await fetchJson(`/api/by-network?from=${from}&to=${to}`);

    if (!data.rows || data.rows.length === 0) {
      showEmpty(containerId);
      return;
    }

    const COLORS = [
      "rgba(10, 132, 255, 0.85)",
      "rgba(255, 149, 0, 0.85)",
      "rgba(48, 209, 88, 0.85)",
      "rgba(191, 90, 242, 0.85)",
      "rgba(255, 69, 58, 0.85)",
      "rgba(90, 200, 250, 0.85)",
    ];

    const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const cardBg = isDark ? "#1c1c1e" : "#ffffff";

    const labels = data.rows.map((r) => r.ssid || `(${linkTypeLabel(r.link_type)})`);
    const totals = data.rows.map((r) => r.bytes_in + r.bytes_out);

    // Lay the doughnut and the table side by side. A bare doughnut defaults to
    // a square the full width of the card (absurdly tall); a fixed-size box +
    // maintainAspectRatio:false keeps it compact and uses the freed space for
    // the table.
    if (state.charts["chart-network"]) {
      state.charts["chart-network"].destroy();
      delete state.charts["chart-network"];
    }
    const container = $(containerId);
    if (!container) return;
    container.innerHTML = `
      <div class="network-layout">
        <div class="network-chart"><canvas id="chart-network"></canvas></div>
        <div class="network-table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>${esc(t("table.network"))}</th>
                <th class="num">${esc(t("table.download"))}</th>
                <th class="num">${esc(t("table.upload"))}</th>
              </tr>
            </thead>
            <tbody>
              ${data.rows.map((r) => `
                <tr>
                  <td>${esc(r.ssid || `(${linkTypeLabel(r.link_type)})`)}</td>
                  <td class="num">${fmtBytes(r.bytes_in)}</td>
                  <td class="num">${fmtBytes(r.bytes_out)}</td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>
      </div>`;

    makeOrUpdateChart("chart-network", {
      type: "doughnut",
      data: {
        labels,
        datasets: [{
          data: totals,
          backgroundColor: COLORS.slice(0, labels.length),
          borderColor: cardBg,
          borderWidth: 3,
          hoverOffset: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 250 },
        cutout: "62%",
        plugins: {
          legend: {
            display: true,
            position: "bottom",
            labels: {
              font: { size: 11 },
              color: isDark ? "#98989d" : "#6e6e73",
              padding: 12,
              usePointStyle: true,
              pointStyleWidth: 8,
            },
          },
          tooltip: {
            backgroundColor: isDark ? "#2c2c2e" : "#1d1d1f",
            titleColor: "#f5f5f7",
            bodyColor: "#aeaeb2",
            cornerRadius: 8,
            padding: { x: 12, y: 10 },
            callbacks: {
              label: (c) => ` ${c.label}: ${fmtBytes(c.parsed)}`,
            },
          },
        },
      },
    });
  } catch (err) {
    showError(containerId, loadByNetwork);
  }
}

/* ─── Load: By Process ───────────────────────────────────────────────────── */
async function loadByProcess() {
  const containerId = "process-body";
  try {
    const { from, to } = rangeBounds();
    const data = await fetchJson(`/api/by-process?from=${from}&to=${to}&limit=15&scope=${state.scope}${netParam()}`);

    if (!data.rows || data.rows.length === 0) {
      showEmpty(containerId);
      return;
    }
    state.exports.process = data.rows;

    ensureCanvas(containerId, "chart-process", undefined);

    const labels = data.rows.map((r) => r.process_name);

    makeOrUpdateChart("chart-process", {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: t("legend.download"),
            data: data.rows.map((r) => r.bytes_in),
            backgroundColor: "rgba(10, 132, 255, 0.85)",
            borderRadius: 3,
            borderSkipped: false,
          },
          {
            label: t("legend.upload"),
            data: data.rows.map((r) => r.bytes_out),
            backgroundColor: "rgba(255, 149, 0, 0.85)",
            borderRadius: 3,
            borderSkipped: false,
          },
        ],
      },
      options: commonOptions({
        indexAxis: "y",
        plugins: {
          tooltip: {
            callbacks: {
              label: (c) => ` ${c.dataset.label}: ${fmtBytes(c.parsed.x)}`,
            },
          },
        },
        scales: {
          x: {
            stacked: true,
            ticks: { callback: (v) => fmtBytes(v) },
          },
          y: {
            stacked: true,
            ticks: { font: { size: 11 } },
          },
        },
      }),
    });
  } catch (err) {
    showError(containerId, loadByProcess);
  }
}

/* ─── Load: By Domain ────────────────────────────────────────────────────── */
async function loadByDomain() {
  const containerId = "domain-body";
  try {
    const { from, to } = rangeBounds();
    const data = await fetchJson(`/api/by-domain?from=${from}&to=${to}&limit=15&scope=${state.scope}${netParam()}`);

    if (!data.rows || data.rows.length === 0) {
      showEmpty(containerId);
      return;
    }
    state.exports.domain = data.rows;

    ensureCanvas(containerId, "chart-domain", 80);

    // For labels we just use the host name (approximate is shown in tooltip)
    const labels = data.rows.map((r) => r.host);
    const approxMap = new Map(data.rows.map((r) => [r.host, r.approximate]));

    makeOrUpdateChart("chart-domain", {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: t("legend.download"),
            data: data.rows.map((r) => r.bytes_in),
            backgroundColor: "rgba(10, 132, 255, 0.85)",
            borderRadius: 3,
            borderSkipped: false,
          },
          {
            label: t("legend.upload"),
            data: data.rows.map((r) => r.bytes_out),
            backgroundColor: "rgba(255, 149, 0, 0.85)",
            borderRadius: 3,
            borderSkipped: false,
          },
        ],
      },
      options: commonOptions({
        indexAxis: "y",
        plugins: {
          tooltip: {
            callbacks: {
              title: (items) => {
                const host = items[0]?.label ?? "";
                const isApprox = approxMap.get(host);
                return isApprox ? t("chart.tooltip.approx_title", { label: host }) : host;
              },
              label: (c) => ` ${c.dataset.label}: ${fmtBytes(c.parsed.x)}`,
              afterBody: (items) => {
                const host = items[0]?.label ?? "";
                if (approxMap.get(host)) {
                  return ["", t("chart.tooltip.approx_body")];
                }
                return [];
              },
            },
          },
        },
        scales: {
          x: {
            stacked: true,
            ticks: { callback: (v) => fmtBytes(v) },
          },
          y: {
            stacked: true,
            ticks: { font: { size: 11 } },
          },
        },
      }),
    });
  } catch (err) {
    showError(containerId, loadByDomain);
  }
}

/* ─── Load: By Port ──────────────────────────────────────────────────────── */
async function loadByPort() {
  const containerId = "port-body";
  try {
    const { from, to } = rangeBounds();
    const data = await fetchJson(`/api/by-port?from=${from}&to=${to}&limit=12${netParam()}`);
    if (!data.rows || data.rows.length === 0) {
      showEmpty(containerId);
      return;
    }
    const el = $(containerId);
    if (!el) return;
    el.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>${esc(t("table.port"))}</th>
            <th>${esc(t("table.service"))}</th>
            <th class="num">${esc(t("table.connections"))}</th>
          </tr>
        </thead>
        <tbody>
          ${data.rows.map((r) => `
            <tr>
              <td>${esc(r.port)}</td>
              <td>${esc(r.service || "—")}</td>
              <td class="num">${esc(r.count)}</td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  } catch (err) {
    showError(containerId, loadByPort);
  }
}

async function loadSessions() {
  const containerId = "history-body";
  try {
    const { from, to } = rangeBounds();
    const data = await fetchJson(`/api/sessions?from=${from}&to=${to}`);
    if (!data.sessions || data.sessions.length === 0) {
      showEmpty(containerId);
      return;
    }
    const el = $(containerId);
    if (!el) return;
    const rows = data.sessions.map((s) => {
      const network = s.ssid || `(${linkTypeLabel(s.link_type)})`;
      // An open session (ended_at IS NULL) is the live one — flag it instead
      // of computing a duration that would tick every refresh.
      const duration = s.ended_at
        ? esc(fmtDur(s.ended_at - s.started_at))
        : `<span class="session-active">${esc(t("session.active"))}</span>`;
      return `
        <tr>
          <td>${esc(network)}</td>
          <td>${esc(fmtTime(s.started_at))}</td>
          <td>${duration}</td>
          <td>${esc(s.ip_address || "—")}</td>
        </tr>`;
    }).join("");
    el.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>${esc(t("table.network"))}</th>
            <th>${esc(t("table.started"))}</th>
            <th>${esc(t("table.duration"))}</th>
            <th>${esc(t("table.ip"))}</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch (err) {
    showError(containerId, loadSessions);
  }
}

/* ─── Refresh groups ─────────────────────────────────────────────────────── */
async function refreshFast() {
  await loadCurrent();
}

async function refreshAll() {
  updateScopeBadges();
  await Promise.allSettled([
    loadCurrent(),
    loadSsidOptions(),
    loadTimeseries(),
    loadByNetwork(),
    loadByProcess(),
    loadByDomain(),
    loadByPort(),
    loadSessions(),
  ]);
}

/* ─── Refresh button spinner ─────────────────────────────────────────────── */
function withRefreshSpinner(fn) {
  return async () => {
    const btn = $("btn-refresh");
    if (btn) btn.classList.add("spinning");
    try {
      await fn();
    } finally {
      if (btn) {
        // Remove and re-add so animation restarts if clicked quickly
        btn.classList.remove("spinning");
      }
    }
  };
}

/* ─── Theme change: re-render charts ─────────────────────────────────────── */
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  // Destroy all charts so they rebuild with updated colors
  for (const id of Object.keys(state.charts)) {
    state.charts[id].destroy();
    delete state.charts[id];
  }
  refreshAll();
});

/* ─── Language toggle ────────────────────────────────────────────────────── */
function bindLangToggle() {
  document.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.addEventListener("click", () => setLocale(btn.dataset.lang));
  });
}

function highlightActiveLang() {
  const cur = currentLocale();
  document.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.classList.toggle("lang-btn--active", btn.dataset.lang === cur);
  });
}

/* ─── Event binding ──────────────────────────────────────────────────────── */
function bind() {
  $("range").addEventListener("change", (e) => {
    const val = e.target.value;
    const customEl = $("custom-range");
    if (val === "custom") {
      state.range = "custom";
      if (customEl) customEl.hidden = false;
      return; // wait for Apply before refetching
    }
    if (customEl) customEl.hidden = true;
    state.range = parseInt(val, 10);
    refreshAll();
  });
  $("apply-range").addEventListener("click", () => {
    const from = parseDateInput($("from-date").value);
    const to = parseDateInput($("to-date").value);
    if (from == null || to == null || to < from) return; // ignore incomplete/invalid
    state.range = "custom";
    state.customFrom = from;
    state.customTo = to + 86_400; // include the whole end day
    refreshAll();
  });
  $("ssid").addEventListener("change", (e) => {
    const opt = e.target.selectedOptions[0];
    state.ssid = (opt && opt.dataset.ssid) || "";
    state.linkType = (opt && opt.dataset.link) || "";
    refreshAll();
  });
  $("scope").addEventListener("change", (e) => {
    state.scope = e.target.value;
    updateScopeBadges();
    // Scope only affects by-process and by-domain
    Promise.allSettled([loadByProcess(), loadByDomain()]);
  });
  $("btn-refresh").addEventListener("click", withRefreshSpinner(refreshAll));
  $("export-process").addEventListener("click", () => downloadCsv("appband-by-app.csv", state.exports.process));
  $("export-domain").addEventListener("click", () => downloadCsv("appband-by-domain.csv", state.exports.domain));
}

/* ─── locale-changed: re-render JS-built content ────────────────────────── */
window.addEventListener("locale-changed", () => {
  highlightActiveLang();
  // Re-render all panels so translated strings appear in charts/tables
  refreshAll();
});

/* ─── Boot ───────────────────────────────────────────────────────────────── */
window.addEventListener("DOMContentLoaded", async () => {
  await initI18n();
  bindLangToggle();
  highlightActiveLang();
  bind();
  refreshAll();
  setInterval(refreshFast, 5_000);
  setInterval(refreshAll, 60_000);
});
