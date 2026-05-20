"use strict";

const $ = (id) => document.getElementById(id);

const fmtBytes = (n) => {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
};
const fmtMbps = (bytes) => `${(bytes * 8 / 1_000_000).toFixed(2)} Mbps`;
const fmtTime = (ts) => new Date(ts * 1000).toLocaleString();

const state = {
  range: 86400,
  ssid: "",
  scope: "internet",
  charts: {},
};

async function fetchJson(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function rangeBounds() {
  const now = Math.floor(Date.now() / 1000);
  return { from: now - state.range, to: now };
}

async function loadCurrent() {
  const data = await fetchJson("/api/current");
  const body = $("current-body");
  if (!data.session) {
    body.textContent = "Aktif ağ yok (çevrimdışı).";
    return;
  }
  const s = data.session;
  body.innerHTML = `
    <strong>${s.link_type}</strong> • ${s.ssid || "(no SSID)"} • ${s.interface}
    • ↓ ${fmtMbps(data.bytes_in_60s / 60)} ↑ ${fmtMbps(data.bytes_out_60s / 60)}
    <br><small>Başlangıç: ${fmtTime(s.started_at)} • IP: ${s.ip_address || "-"}</small>
  `;
}

async function loadSsidOptions() {
  const { from, to } = rangeBounds();
  const data = await fetchJson(`/api/by-network?from=${from}&to=${to}`);
  const sel = $("ssid");
  const current = sel.value;
  while (sel.options.length > 1) sel.remove(1);
  for (const row of data.rows) {
    const v = row.ssid || `(${row.link_type})`;
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    sel.appendChild(opt);
  }
  sel.value = current;
}

function makeOrUpdateChart(id, config) {
  const ctx = $(id).getContext("2d");
  if (state.charts[id]) {
    state.charts[id].data = config.data;
    state.charts[id].options = config.options || {};
    state.charts[id].update();
  } else {
    state.charts[id] = new Chart(ctx, config);
  }
}

async function loadTimeseries() {
  const { from, to } = rangeBounds();
  const granularity = state.range > 86400 * 2 ? "day" : "hour";
  const data = await fetchJson(`/api/timeseries?from=${from}&to=${to}&granularity=${granularity}`);
  const labels = data.timeseries.map((r) => fmtTime(r.ts));
  makeOrUpdateChart("chart-timeseries", {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "İndirme", data: data.timeseries.map((r) => r.bytes_in), backgroundColor: "#0a84ff" },
        { label: "Yükleme", data: data.timeseries.map((r) => r.bytes_out), backgroundColor: "#ff9500" },
      ],
    },
    options: {
      scales: { y: { ticks: { callback: (v) => fmtBytes(v) } } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtBytes(c.parsed.y)}` } } },
    },
  });
}

async function refreshFast() { await loadCurrent(); }
async function refreshAll() {
  await Promise.all([loadCurrent(), loadSsidOptions(), loadTimeseries(), loadByNetwork(), loadByProcess(), loadByDomain()]);
}

async function loadByNetwork() {
  const { from, to } = rangeBounds();
  const data = await fetchJson(`/api/by-network?from=${from}&to=${to}`);
  const labels = data.rows.map((r) => r.ssid || `(${r.link_type})`);
  const totals = data.rows.map((r) => r.bytes_in + r.bytes_out);
  makeOrUpdateChart("chart-network", {
    type: "doughnut",
    data: { labels, datasets: [{ data: totals, backgroundColor: ["#0a84ff", "#ff9500", "#30d158", "#bf5af2", "#ff453a"] }] },
    options: { plugins: { tooltip: { callbacks: { label: (c) => `${c.label}: ${fmtBytes(c.parsed)}` } } } },
  });
  const tbl = $("table-network");
  tbl.innerHTML = "<tr><th>Ağ</th><th class='num'>↓</th><th class='num'>↑</th></tr>" +
    data.rows.map((r) => `<tr><td>${r.ssid || `(${r.link_type})`}</td><td class='num'>${fmtBytes(r.bytes_in)}</td><td class='num'>${fmtBytes(r.bytes_out)}</td></tr>`).join("");
}

async function loadByProcess() {
  const { from, to } = rangeBounds();
  const data = await fetchJson(`/api/by-process?from=${from}&to=${to}&limit=15&scope=${state.scope}`);
  makeOrUpdateChart("chart-process", {
    type: "bar",
    data: {
      labels: data.rows.map((r) => r.process_name),
      datasets: [
        { label: "↓", data: data.rows.map((r) => r.bytes_in), backgroundColor: "#0a84ff" },
        { label: "↑", data: data.rows.map((r) => r.bytes_out), backgroundColor: "#ff9500" },
      ],
    },
    options: {
      indexAxis: "y",
      scales: { x: { stacked: true, ticks: { callback: (v) => fmtBytes(v) } }, y: { stacked: true } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtBytes(c.parsed.x)}` } } },
    },
  });
}

async function loadByDomain() {
  const { from, to } = rangeBounds();
  const data = await fetchJson(`/api/by-domain?from=${from}&to=${to}&limit=30&scope=${state.scope}`);
  makeOrUpdateChart("chart-domain", {
    type: "bar",
    data: {
      labels: data.rows.map((r) => "~ " + r.host),
      datasets: [
        { label: "↓", data: data.rows.map((r) => r.bytes_in), backgroundColor: "#0a84ff" },
        { label: "↑", data: data.rows.map((r) => r.bytes_out), backgroundColor: "#ff9500" },
      ],
    },
    options: {
      indexAxis: "y",
      scales: { x: { stacked: true, ticks: { callback: (v) => fmtBytes(v) } }, y: { stacked: true } },
      plugins: {
        tooltip: {
          callbacks: {
            title: (c) => `${c[0].label} (yaklaşık)`,
            label: (c) => `${c.dataset.label}: ${fmtBytes(c.parsed.x)}`,
            afterBody: () => "Yaklaşık: süreç byte'ı bağlantılara dağıtıldı.",
          },
        },
      },
    },
  });
}

function bind() {
  $("range").addEventListener("change", (e) => { state.range = parseInt(e.target.value, 10); refreshAll(); });
  $("ssid").addEventListener("change", (e) => { state.ssid = e.target.value; refreshAll(); });
  $("scope").addEventListener("change", (e) => { state.scope = e.target.value; refreshAll(); });
  $("refresh").addEventListener("click", () => refreshAll());
}

window.addEventListener("DOMContentLoaded", () => {
  bind();
  refreshAll();
  setInterval(refreshFast, 5000);
  setInterval(refreshAll, 60000);
});
