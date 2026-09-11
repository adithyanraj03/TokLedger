"""The zero-dependency TokLedger dashboard (single file, vanilla JS + SVG).

Served at ``/``. Pulls ``/api/stats``, ``/api/by-day``, ``/api/by-model``
and ``/api/recent`` and renders:

* stats cards - requests, tokens, avg TTFT, local $, cloud-equivalent $, savings %
* per-day stacked bars (tokens) + cost lines (local vs cloud) as inline SVG
* per-model table
* recent-requests table with live auto-refresh (5s)
"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TokLedger - local inference ledger</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 40px; background: #0b0e14; color: #d6dae3;
       font: 14px/1.5 "Segoe UI", system-ui, -apple-system, sans-serif; }
h1 { font-size: 22px; margin: 0 0 2px; letter-spacing: .3px; }
.sub { color: #7a8194; margin: 0 0 22px; font-size: 13px; }
.sub code { background: #1a2030; padding: 1px 6px; border-radius: 4px; font-size: 12px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 26px; }
.card { background: #11151f; border: 1px solid #1f2534; border-radius: 10px; padding: 14px 16px; }
.card .k { color: #7a8194; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
.card .v { font-size: 20px; font-weight: 600; color: #e8ecf5; margin-top: 4px; font-variant-numeric: tabular-nums; }
.card .v.green { color: #4ade80; }
.card .v.dim { color: #9aa2b5; font-size: 15px; }
.panel { background: #11151f; border: 1px solid #1f2534; border-radius: 10px; padding: 16px 18px; margin-bottom: 22px; }
.panel h2 { font-size: 13px; margin: 0 0 12px; color: #9fb4ff; text-transform: uppercase; letter-spacing: 1.2px; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #1c2230; font-size: 13px; }
th { color: #7a8194; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.pill.ok { background: rgba(34,197,94,.15); color: #4ade80; }
.pill.err { background: rgba(239,68,68,.15); color: #f87171; }
.pill.est { background: rgba(122,129,148,.15); color: #9aa2b5; }
.legend { font-size: 12px; color: #7a8194; margin-top: 8px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 4px 0 12px; vertical-align: -1px; }
.muted { color: #555c6e; }
.preview { max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #9aa2b5; }
.footer { margin-top: 30px; color: #555c6e; font-size: 12px; }
svg text { font-family: inherit; }
</style>
</head>
<body>
<h1>TokLedger <span class="muted">- local inference ledger</span></h1>
<p class="sub" id="subline">connecting&hellip;</p>

<div class="cards" id="cards"></div>

<div class="panel">
  <h2>Daily activity</h2>
  <div id="chart"></div>
  <div class="legend">
    <i style="background:#4f8cff"></i>tokens (bars)
    <i style="background:#2dd4a7"></i>local cost (line)
    <i style="background:#f59e0b"></i>cloud-equivalent (line)
  </div>
</div>

<div class="panel">
  <h2>By model</h2>
  <table id="modeltable">
    <tr><th>model</th><th class="num">requests</th><th class="num">tokens</th>
    <th class="num">avg TTFT</th><th class="num">local $</th><th class="num">cloud-equiv $</th></tr>
  </table>
</div>

<div class="panel">
  <h2>Recent requests</h2>
  <table id="recenttable">
    <tr><th>time</th><th>model</th><th>prompt</th><th>completion</th><th class="num">TTFT</th>
    <th class="num">tok/s</th><th class="num">kWh</th><th class="num">local $</th>
    <th class="num">cloud $</th><th class="num">status</th><th>preview</th></tr>
  </table>
</div>

<div class="footer">TokLedger &middot; no cloud, no account, no telemetry &middot;
<a href="/export.jsonl" style="color:#9fb4ff">export JSONL</a></div>

<script>
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const usd = (v) => v == null ? "-" : (v === 0 ? "$0.000" : (v < 0.001 ? "$" + v.toFixed(4) : "$" + v.toFixed(3)));
const num = (v, d=0) => v == null ? "-" : Number(v).toLocaleString(undefined, {maximumFractionDigits: d, minimumFractionDigits: d});
const ms = (v) => v == null ? "-" : (v < 1 ? v.toFixed(1) + " ms" : (v/1000).toFixed(2) + " s");

async function j(u) { const r = await fetch(u); if (!r.ok) throw new Error(u + " -> " + r.status); return r.json(); }

function renderStats(s) {
  const cards = [
    ["requests", num(s.requests)],
    ["tokens", num(s.total_tokens)],
    ["avg TTFT", ms(s.avg_ttft_ms)],
    ["energy", (s.kwh || 0).toFixed(4) + " kWh"],
    ["local cost", usd(s.local_cost_usd)],
    ["cloud-equiv", usd(s.cloud_cost_usd)],
    ["saved vs cloud", s.savings_pct == null ? "-" : num(s.savings_pct, 1) + " %", s.savings_pct > 0 ? "green" : ""],
  ];
  $("#cards").innerHTML = cards.map(([k, v, c]) =>
    `<div class="card"><div class="k">${k}</div><div class="v ${c||""}">${v}</div></div>`).join("");
  $("#subline").innerHTML =
    `upstream: <code>${esc(s.upstream || "not configured")}</code> &middot; power mode: <code>${esc(s.power_mode)}</code> &middot; v${esc(s.version)}`;
}

function renderChart(days) {
  if (!days.length) { $("#chart").innerHTML = '<div class="muted">No data yet - send a request through the proxy.</div>'; return; }
  const W = 900, H = 220, PAD = 34;
  const maxTok = Math.max(...days.map(d => d.total_tokens || 0), 1);
  const maxCost = Math.max(...days.flatMap(d => [d.local_cost_usd||0, d.cloud_cost_usd||0]), 1e-9);
  const bw = (W - PAD*2) / days.length * 0.55;
  const x = (i) => PAD + (W - PAD*2) * (i + 0.5) / days.length;
  let bars = days.map((d, i) => {
    const h = (d.total_tokens||0) / maxTok * (H - 56);
    return `<rect x="${x(i)-bw/2}" y="${H-28-h}" width="${bw}" height="${Math.max(h,1)}" fill="#4f8cff" rx="2"/>`;
  }).join("");
  const line = (key, color) => {
    const pts = days.map((d, i) => `${x(i)},${H-28-((d[key]||0)/maxCost*(H-56))}`).join(" ");
    return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2"/>`;
  };
  const labels = days.map((d, i) =>
    `<text x="${x(i)}" y="${H-10}" font-size="10" fill="#7a8194" text-anchor="middle">${esc(d.day)}</text>`).join("");
  const tokLabels = days.map((d, i) =>
    (d.total_tokens||0) > 0 ? `<text x="${x(i)}" y="${H-32-((d.total_tokens||0)/maxTok*(H-56))}" font-size="9" fill="#9aa2b5" text-anchor="middle">${num(d.total_tokens)}</text>` : "").join("");
  $("#chart").innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">${bars}${line("local_cost_usd","#2dd4a7")}${line("cloud_cost_usd","#f59e0b")}${labels}${tokLabels}</svg>`;
}

function renderModels(rows) {
  $("#modeltable").innerHTML =
    `<tr><th>model</th><th class="num">requests</th><th class="num">tokens</th><th class="num">avg TTFT</th><th class="num">local $</th><th class="num">cloud-equiv $</th></tr>` +
    (rows.length ? rows.map(r =>
      `<tr><td>${esc(r.model)}</td><td class="num">${num(r.requests)}</td><td class="num">${num(r.total_tokens)}</td>
       <td class="num">${ms(r.avg_ttft_ms)}</td><td class="num">${usd(r.local_cost_usd)}</td><td class="num">${usd(r.cloud_cost_usd)}</td></tr>`
    ).join("") : `<tr><td colspan="6" class="muted">no requests yet</td></tr>`);
}

function renderRecent(rows) {
  $("#recenttable").innerHTML =
    `<tr><th>time</th><th>model</th><th>prompt</th><th>completion</th><th class="num">TTFT</th><th class="num">tok/s</th><th class="num">kWh</th><th class="num">local $</th><th class="num">cloud $</th><th class="num">status</th><th>preview</th></tr>` +
    (rows.length ? rows.map(r =>
      `<tr><td>${esc(new Date((r.ts||0)*1000).toISOString().slice(5,19).replace("T"," "))}</td>
       <td>${esc(r.model)}</td>
       <td class="num">${num(r.prompt_tokens)}${r.tokens_exact ? "" : ' <span class="pill est">est</span>'}</td>
       <td class="num">${num(r.completion_tokens)}</td>
       <td class="num">${ms(r.ttft_ms)}</td><td class="num">${r.tokens_per_s == null ? "-" : num(r.tokens_per_s,1)}</td>
       <td class="num">${(r.kwh||0).toExponential(2)}</td><td class="num">${usd(r.local_cost_usd)}</td><td class="num">${usd(r.cloud_cost_usd)}</td>
       <td class="num"><span class="pill ${r.status === 200 ? "ok" : "err"}">${esc(r.status)}</span></td>
       <td class="preview">${esc(r.preview || (r.error || ""))}</td></tr>`
    ).join("") : `<tr><td colspan="11" class="muted">no requests yet</td></tr>`);
}

async function refresh() {
  try {
    const [stats, days, models, recent] = await Promise.all([
      j("/api/stats"), j("/api/by-day"), j("/api/by-model"), j("/api/recent?limit=25"),
    ]);
    renderStats(stats); renderChart(days); renderModels(models); renderRecent(recent);
  } catch (e) {
    $("#subline").innerHTML = `<span class="pill err">api error: ${esc(e.message)}</span>`;
  }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
