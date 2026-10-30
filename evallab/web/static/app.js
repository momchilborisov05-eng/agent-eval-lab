// Agent Eval Lab dashboard: a small hash-routed single-page app over the JSON API.
// Works without GSAP (no animation) and without Chart.js (charts show a fallback note).
"use strict";

const app = document.getElementById("app");
const banner = document.getElementById("banner");
const demoBadge = document.getElementById("demo-badge");
const sqlModal = document.getElementById("sql-modal");
const nav = document.getElementById("main-nav");
const HAS_CHART = typeof Chart !== "undefined";
const motion = typeof gsap !== "undefined" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let charts = [];        // live Chart instances
let chartSpecs = [];    // { id, build } so charts can be rebuilt on theme change
let sqlCache = null;
const lastValues = {};  // KPI label -> last shown number (count-up starts from here)

// ---------- icons (Lucide-style inline SVG) ----------

const svg = (d, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const I = {
  check: (c) => svg('<path d="M20 6 9 17l-5-5"/>', c),
  x: (c) => svg('<path d="M18 6 6 18M6 6l12 12"/>', c),
  alert: (c) => svg('<path d="m10.3 3.9-8.1 14a2 2 0 0 0 1.7 3h16.2a2 2 0 0 0 1.7-3l-8.1-14a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>', c),
  info: (c) => svg('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>', c),
  target: (c) => svg('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>', c),
  trend: (c) => svg('<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>', c),
  scale: (c) => svg('<path d="m16 16 3-8 3 8c-.9.7-1.9 1-3 1s-2.1-.3-3-1ZM2 16l3-8 3 8c-.9.7-1.9 1-3 1s-2.1-.3-3-1Z"/><path d="M7 21h10M12 3v18M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>', c),
  eye: (c) => svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>', c),
  clock: (c) => svg('<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>', c),
  mic: (c) => svg('<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M19 10a7 7 0 0 1-14 0M12 17v5"/>', c),
  quote: (c) => svg('<path d="M3 21c3 0 7-1 7-8V5H3v7h4c0 3-1 5-4 5Z"/><path d="M14 21c3 0 7-1 7-8V5h-7v7h4c0 3-1 5-4 5Z"/>', c),
  chart: (c) => svg('<path d="M3 3v18h18"/><path d="M7 16V9M12 16V5M17 16v-4"/>', c),
  list: (c) => svg('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>', c),
  chat: (c) => svg('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/>', c),
  gavel: (c) => svg('<path d="m14 13-7.5 7.5a2.1 2.1 0 0 1-3-3L11 10"/><path d="m16 16 6-6M8 8l6-6M9 7l8 8M21 11l-8-8"/>', c),
  wrench: (c) => svg('<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9Z"/>', c),
  chevron: (c) => svg('<path d="m9 18 6-6-6-6"/>', c),
  arrowRight: (c) => svg('<path d="M5 12h14M12 5l7 7-7 7"/>', c),
  compare: (c) => svg('<path d="M16 3h5v5M8 21H3v-5M21 3l-7 7M3 21l7-7"/>', c),
  users: (c) => svg('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>', c),
  spark: (c) => svg('<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>', c),
  bot: (c) => svg('<rect x="3" y="8" width="18" height="12" rx="3"/><path d="M12 8V4M8 14h.01M16 14h.01"/>', c),
  user: (c) => svg('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>', c),
  db: (c) => svg('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>', c),
  flask: (c) => svg('<path d="M9 3h6M10 3v6.5L4.6 18.2A1.8 1.8 0 0 0 6.1 21h11.8a1.8 1.8 0 0 0 1.5-2.8L14 9.5V3"/><path d="M7.5 15h9"/>', c),
  repeat: (c) => svg('<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>', c),
};

// ---------- helpers ----------

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v, digits = 1) => (v === null || v === undefined ? "–" : `${Number(v).toFixed(digits)}%`);
const ratio = (v) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
const ms = (v) => (v === null || v === undefined ? "–" : `${Math.round(v).toLocaleString()} ms`);
const signed = (v, unit = "") => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(unit === "pp" ? 1 : 2)}${unit ? " " + unit : ""}`);
const pretty = (s) => String(s ?? "").replace(/_/g, " ");
const short = (label) => String(label ?? "").replace(/^DEMO - /, "");
const enc = encodeURIComponent;

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

// Number spec for count-up KPIs. Null values render as an en dash.
const num = (n, dec = 0, suf = "", sign = false) => ({ n, dec, suf, sign });
const fmtCount = (v, dec, suf, sign) => `${sign && v > 0 ? "+" : ""}${Number(v).toFixed(dec)}${suf}`;

function countSpan(key, value) {
  if (value.n === null || value.n === undefined) return "–";
  return `<span class="count" data-key="${esc(key)}" data-n="${Number(value.n)}" data-dec="${value.dec}" data-suf="${esc(value.suf)}" data-sign="${value.sign ? 1 : 0}">${esc(fmtCount(value.n, value.dec, value.suf, value.sign))}</span>`;
}

function kpi(label, value, sub = "", cls = "", icon = "") {
  const val = value && typeof value === "object" ? countSpan(label, value) : value;
  return `<div class="kpi"><div class="label">${icon}${esc(label)}</div><div class="value ${cls}">${val}</div><div class="sub">${sub}</div></div>`;
}

function sqlButton(names, extra = "") {
  return `<button type="button" class="sql-btn ${extra}" data-sql="${esc(names)}" title="Show the SQL behind this card">${I.db()}SQL</button>`;
}

function panelHead(title, icon, sql = "", sub = "") {
  return `<div class="panel-head"><h2>${icon ? icon("h-icon") : ""}${title}${sub ? ` <span class="sub">${sub}</span>` : ""}</h2>${sql ? sqlButton(sql) : ""}</div>`;
}

function statusBadge(passed) {
  return passed ? '<span class="badge pass">PASS</span>' : '<span class="badge fail">FAIL</span>';
}

function modeBadge(mode) {
  const cls = { demo: "warn", live: "info", import: "neutral" }[mode] || "neutral";
  return `<span class="badge ${cls}">${esc(String(mode || "").toUpperCase())}</span>`;
}

function bar(value) {
  return `<div class="bar"><span style="width:${Math.max(0, Math.min(100, value || 0))}%"></span></div>`;
}

function deltaPill(d, unit = "", invert = false, dec = 0) {
  if (d === null || d === undefined) return '<span class="delta flat">–</span>';
  const good = invert ? d < 0 : d > 0;
  const cls = d === 0 ? "flat" : good ? "up" : "down";
  const arrow = d > 0 ? "▲" : d < 0 ? "▼" : "";
  return `<span class="delta ${cls}">${arrow} ${d > 0 ? "+" : ""}${Number(d).toFixed(dec)}${unit}</span>`;
}

function emptyState(title, body, icon = I.flask) {
  return `<div class="panel empty"><div class="e-icon">${icon()}</div><h1>${title}</h1>${body}</div>`;
}

function setBanner(runs) {
  const demo = runs.some((r) => r.mode === "demo");
  showDemo(demo, "<strong>Demo data.</strong> Runs marked DEMO use a rule-based agent, a scripted customer, a heuristic judge and simulated latency. They show how the lab works, not how any real model performs.");
}

function showDemo(on, html) {
  banner.hidden = !on;
  banner.innerHTML = on ? `${I.info()}<span>${html}</span>` : "";
  demoBadge.hidden = !on;
}

function setNav(name) {
  document.querySelectorAll("nav a[data-nav]").forEach((a) => {
    const active = a.dataset.nav === name;
    a.classList.toggle("active", active);
    if (active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

// ---------- theme + charts ----------

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function palette() {
  return {
    accent: cssVar("--accent"), accent2: cssVar("--accent-2"), text: cssVar("--text"), text2: cssVar("--text-2"), text3: cssVar("--text-3"),
    border: cssVar("--border"), borderStrong: cssVar("--border-strong"), surface: cssVar("--surface-strong"), base: cssVar("--chart-base"),
    success: cssVar("--success"), warning: cssVar("--warning"), danger: cssVar("--danger"), info: cssVar("--info"),
    font: cssVar("--font") || "system-ui, sans-serif", mono: cssVar("--mono") || "monospace",
  };
}

// Gradient fill along the value axis (falls back to the first colour before layout).
const grad = (c1, c2, horizontal = false) => (ctx) => {
  const { chart: ch } = ctx;
  const a = ch.chartArea;
  if (!a) return c1;
  const g = horizontal ? ch.ctx.createLinearGradient(a.left, 0, a.right, 0) : ch.ctx.createLinearGradient(0, a.bottom, 0, a.top);
  g.addColorStop(0, c1);
  g.addColorStop(1, c2);
  return g;
};

function applyChartDefaults(P, animate) {
  const d = Chart.defaults;
  d.font.family = P.font;
  d.font.size = 12;
  d.color = P.text2;
  d.borderColor = P.border;
  d.animation = animate && motion ? { duration: 750, easing: "easeOutQuart" } : false;
  d.animations.colors = false; // gradients cannot be colour-interpolated
  d.plugins.legend.labels.usePointStyle = true;
  d.plugins.legend.labels.pointStyle = "rectRounded";
  d.plugins.legend.labels.boxWidth = 8;
  d.plugins.legend.labels.boxHeight = 8;
  d.plugins.legend.labels.padding = 14;
  Object.assign(d.plugins.tooltip, {
    backgroundColor: P.surface, titleColor: P.text, bodyColor: P.text2, borderColor: P.borderStrong, borderWidth: 1,
    padding: 10, cornerRadius: 10, boxPadding: 4, usePointStyle: true, titleFont: { weight: "600" },
  });
}

function renderChart(spec, animate) {
  const canvas = document.getElementById(spec.id);
  if (!canvas) return;
  if (!HAS_CHART) {
    if (!canvas.parentElement.querySelector(".chart-fallback")) {
      canvas.insertAdjacentHTML("afterend", '<div class="chart-fallback">Chart library could not be loaded. The numbers are in the tables and behind the SQL button.</div>');
    }
    canvas.hidden = true;
    return;
  }
  const P = palette();
  applyChartDefaults(P, animate);
  const config = spec.build(P);
  config.options = Object.assign({ responsive: true, maintainAspectRatio: false }, config.options || {});
  charts.push(new Chart(canvas, config));
}

function chart(id, build) {
  const spec = { id, build };
  chartSpecs.push(spec);
  renderChart(spec, true);
}

function rerenderCharts() {
  charts.forEach((c) => c.destroy());
  charts = [];
  chartSpecs.forEach((s) => renderChart(s, false));
}

const pctAxis = (P, extra = {}) => Object.assign({ min: 0, max: 100, ticks: { callback: (v) => v + "%", color: P.text3 }, border: { display: false }, grid: { color: P.border } }, extra);
const catAxis = (P, extra = {}) => Object.assign({ grid: { display: false }, border: { color: P.border }, ticks: { color: P.text2 } }, extra);

function currentTheme() { return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark"; }

function setTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("evallab-theme", t); } catch (e) { /* storage unavailable */ }
  rerenderCharts();
}

// ---------- motion ----------

function animateCounts(root) {
  root.querySelectorAll(".count").forEach((el) => {
    const key = el.dataset.key;
    const to = Number(el.dataset.n);
    const dec = Number(el.dataset.dec);
    const suf = el.dataset.suf || "";
    const sign = el.dataset.sign === "1";
    const from = key in lastValues ? lastValues[key] : 0;
    lastValues[key] = to;
    if (!motion || from === to) return;
    const o = { v: from };
    el.textContent = fmtCount(from, dec, suf, sign);
    gsap.to(o, { v: to, duration: 0.9, ease: "power2.out", onUpdate: () => { el.textContent = fmtCount(o.v, dec, suf, sign); } });
  });
}

function animatePage() {
  animateCounts(app);
  if (!motion) return;
  const q = (s) => Array.from(app.querySelectorAll(s));
  const clear = { clearProps: "transform,opacity" };
  gsap.from(q(".page-head"), { y: 10, opacity: 0, duration: 0.45, ease: "power3.out", ...clear });
  gsap.from(q(".kpi"), { y: 16, opacity: 0, duration: 0.55, stagger: 0.06, ease: "power3.out", delay: 0.05, ...clear });
  gsap.from(q("main > .panel, main > .grid > .panel, main > .grid > .grid > .panel, .groups > .panel"), { y: 16, opacity: 0, duration: 0.55, stagger: 0.06, ease: "power3.out", delay: 0.12, ...clear });
  gsap.from(q("tbody tr").slice(0, 25), { y: 8, opacity: 0, duration: 0.4, stagger: 0.03, ease: "power2.out", delay: 0.25, ...clear });
  gsap.from(q(".turn").slice(0, 25), { y: 10, opacity: 0, duration: 0.45, stagger: 0.05, ease: "power3.out", delay: 0.2, ...clear });
  gsap.from(q(".scn-item"), { x: -8, opacity: 0, duration: 0.4, stagger: 0.04, ease: "power2.out", delay: 0.3, ...clear });
  gsap.from(q(".bar > span, .cat-track .b"), { scaleX: 0, duration: 0.9, ease: "power3.out", delay: 0.25, stagger: 0.03, ...clear });
  gsap.from(q(".delta"), { scale: 0.6, opacity: 0, duration: 0.5, ease: "back.out(2)", delay: 0.45, stagger: 0.03, ...clear });
}

// ---------- pages ----------

async function overview() {
  setNav("overview");
  const runs = await api("/api/runs");
  setBanner(runs);
  if (!runs.length) {
    app.innerHTML = emptyState("No runs yet", "<p>Create two demo runs with <code>python -m evallab demo</code>, or a live run with <code>python -m evallab run</code>.</p>");
    return;
  }
  const latest = runs[runs.length - 1];
  const previous = runs.length > 1 ? runs[runs.length - 2] : null;
  const [sumLatest, sumPrev] = await Promise.all([api(`/api/runs/${enc(latest.id)}`), previous ? api(`/api/runs/${enc(previous.id)}`) : null]);
  const delta = previous ? latest.pass_rate - previous.pass_rate : null;
  const agreement = sumLatest.judge_agreement;

  app.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">${I.spark()}Evaluation dashboard</div><h1>Overview</h1>
      <p>${runs.length} evaluation run${runs.length > 1 ? "s" : ""}. Latest: <a href="#/run/${enc(latest.id)}">${esc(latest.label)}</a></p></div>
      <div class="head-actions">${previous ? `<a class="btn" href="#/compare?a=${enc(previous.id)}&b=${enc(latest.id)}">${I.compare()}Compare latest two runs</a>` : ""}</div></div>
    <div class="kpis">
      ${kpi("Latest pass rate", num(latest.pass_rate, 1, "%"), `${latest.passed} of ${latest.scenarios} scenarios`, "", I.target())}
      ${kpi("Change vs previous run", previous ? num(delta, 1, " pp", true) : "–", previous ? esc(short(previous.label)) : "only one run", delta > 0 ? "up" : delta < 0 ? "down" : "", I.trend())}
      ${kpi("Judge verdict agreement", agreement.verdict_agreement === null ? "–" : num(agreement.verdict_agreement * 100, 0, "%"), `Cohen's kappa ${agreement.kappa === null ? "–" : agreement.kappa.toFixed(2)}`, "", I.scale())}
      ${kpi("Needs human review", num(latest.judge_disagreements), "judge trials disagree", "", I.eye())}
    </div>
    <div class="grid g2">
      <div class="panel lift">${panelHead("Pass rate by run", I.chart, "runs")}<div class="chart-box"><canvas id="c-runs"></canvas></div></div>
      <div class="panel lift">${panelHead("Pass rate by category", I.list, "pass_rate_by_category")}<div class="chart-box"><canvas id="c-cats"></canvas></div></div>
    </div>
    <div class="panel">${panelHead("Runs", I.flask, "runs", "click a run for details")}<div class="table-wrap"><table>
      <thead><tr><th>Run</th><th>Mode</th><th>Agent</th><th>Simulator / judge</th><th class="num">Passed</th><th>Pass rate</th><th>Started (UTC)</th><th></th></tr></thead>
      <tbody>${runs.slice().reverse().map((r) => `
        <tr class="click" tabindex="0" data-href="#/run/${enc(r.id)}">
          <td><strong>${esc(r.label)}</strong><div class="cell-sub">${esc(r.id)}</div></td>
          <td>${modeBadge(r.mode)}</td>
          <td>${esc(r.agent_version || "")}<div class="cell-sub">${esc(r.model || "")}</div></td>
          <td>${esc(r.simulator || "")} / ${esc(r.judge || "")}${r.judge_trials ? ` ×${r.judge_trials}` : ""}</td>
          <td class="num">${r.passed}/${r.scenarios}</td>
          <td><div class="bar-cell">${bar(r.pass_rate)}<strong class="num">${pct(r.pass_rate)}</strong></div></td>
          <td class="faint num">${esc((r.started_at || "").replace("T", " ").replace("Z", "").slice(0, 16))}</td>
          <td><a href="#/gtm/${enc(r.id)}">GTM</a></td>
        </tr>`).join("")}</tbody></table></div></div>`;

  chart("c-runs", (P) => ({
    type: "bar",
    data: { labels: runs.map((r) => short(r.label)), datasets: [{ label: "Pass rate %", data: runs.map((r) => r.pass_rate),
      backgroundColor: (ctx) => (ctx.dataIndex === runs.length - 1 ? grad(P.accent, P.accent2)(ctx) : P.base), borderRadius: 8, maxBarThickness: 64 }] },
    options: { plugins: { legend: { display: false } }, scales: { y: pctAxis(P), x: catAxis(P) } },
  }));
  const cats = sumLatest.categories.map((c) => c.category).sort();
  const latestMap = Object.fromEntries(sumLatest.categories.map((c) => [c.category, c.pass_rate]));
  const prevMap = sumPrev ? Object.fromEntries(sumPrev.categories.map((c) => [c.category, c.pass_rate])) : null;
  chart("c-cats", (P) => {
    const datasets = [];
    if (prevMap) datasets.push({ label: short(previous.label), data: cats.map((c) => prevMap[c] ?? null), backgroundColor: P.base, borderRadius: 5, maxBarThickness: 22 });
    datasets.push({ label: short(latest.label), data: cats.map((c) => latestMap[c]), backgroundColor: grad(P.accent, P.accent2), borderRadius: 5, maxBarThickness: 22 });
    return { type: "bar", data: { labels: cats, datasets }, options: { scales: { y: pctAxis(P), x: catAxis(P) }, plugins: { legend: { position: "bottom" } } } };
  });
}

async function runPage(runId) {
  setNav("overview");
  const [s, runs] = await Promise.all([api(`/api/runs/${enc(runId)}`), api("/api/runs")]);
  setBanner(runs);
  const r = s.run;
  const ag = s.judge_agreement;
  const lat = s.latency;
  const voice = lat.find((l) => l.channel === "voice");
  const chat = lat.find((l) => l.channel === "chat");
  const idx = runs.findIndex((x) => x.id === r.id);
  const prev = idx > 0 ? runs[idx - 1] : null;

  app.innerHTML = `
    <div class="page-head"><div><div class="eyebrow"><a href="#/">Overview</a> / Run</div><h1>${esc(r.label)} ${modeBadge(r.mode)}</h1>
      <div class="meta"><span>Agent <b>${esc(r.agent_name || "")} ${esc(r.agent_version || "")}</b></span><span>Model <b>${esc(r.model || "–")}</b></span><span>Simulator <b>${esc(r.simulator)}</b></span><span>Judge <b>${esc(r.judge)} ×${r.judge_trials}</b></span></div></div>
      <div class="head-actions">${prev ? `<a class="btn" href="#/compare?a=${enc(prev.id)}&b=${enc(r.id)}">${I.compare()}Compare with previous</a>` : ""}<a class="btn btn-secondary" href="#/gtm/${enc(r.id)}">${I.users()}GTM insights</a></div></div>
    <div class="kpis">
      ${kpi("Pass rate", num(r.pass_rate, 1, "%"), `${r.passed} of ${r.scenarios} scenarios`, "", I.target())}
      ${kpi("Chat latency p95", chat ? num(Math.round(chat.p95_ms), 0, " ms") : "–", chat ? `p50 ${ms(chat.p50_ms)} · ${chat.agent_turns} turns` : "no chat turns", "", I.clock())}
      ${kpi("Voice latency p95", voice ? num(Math.round(voice.p95_ms), 0, " ms") : "–", voice ? `p50 ${ms(voice.p50_ms)} · ${voice.agent_turns} turns` : "no voice turns", "", I.mic())}
      ${kpi("Judge verdict agreement", ag.verdict_agreement === null ? "–" : num(ag.verdict_agreement * 100, 0, "%"), `kappa ${ag.kappa === null ? "–" : ag.kappa.toFixed(2)} · ${ag.pairs} pairs`, "", I.scale())}
      ${kpi("Evidence quotes grounded", ag.quote_grounding === null ? "–" : num(ag.quote_grounding * 100, 0, "%"), `${ag.ungrounded_quotes} not found in transcript`, "", I.quote())}
    </div>
    <div class="grid g2">
      <div class="panel lift">${panelHead("Pass rate by category", I.list, "pass_rate_by_category")}<div class="chart-box"><canvas id="c-cat"></canvas></div></div>
      <div class="panel lift">${panelHead("Top failure reasons", I.alert, "top_failure_reasons")}<div class="chart-box"><canvas id="c-fail"></canvas></div></div>
    </div>
    <div class="grid g2">
      <div class="panel">${panelHead("LLM judge: scores by criterion", I.gavel, "judge_criteria")}
        <div class="table-wrap"><table><thead><tr><th>Criterion</th><th class="num">Avg score</th><th class="num">Pass rate</th><th class="num">Exact agr.</th><th class="num">Within ±1</th></tr></thead><tbody>
        ${s.judge_criteria.map((c) => { const a = ag.criteria.find((x) => x.criterion === c.criterion) || {}; return `<tr><td>${esc(pretty(c.criterion))}</td><td class="num"><strong>${c.avg_score.toFixed(2)}</strong></td><td class="num">${pct(c.pass_rate)}</td><td class="num">${ratio(a.exact_agreement)}</td><td class="num">${ratio(a.within_one)}</td></tr>`; }).join("")}
        </tbody></table></div>
        <p class="panel-foot">Agreement compares judge trial 1 with trial 2 on the same transcript ${sqlButton("judge_agreement,verdict_pairs", "inline-sql")}. ${ag.unstable.length ? `Unstable verdicts: ${ag.unstable.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}` : "No unstable verdicts."}</p>
      </div>
      <div class="panel">${panelHead("Latency by channel", I.clock, "latency")}
        <div class="table-wrap"><table><thead><tr><th>Channel</th><th class="num">Turns</th><th class="num">Avg</th><th class="num">p50</th><th class="num">p95</th><th class="num">Max</th></tr></thead><tbody>
        ${lat.map((l) => `<tr><td><span class="badge plain ${l.channel === "voice" ? "accent" : "info"}">${esc(l.channel)}</span></td><td class="num">${l.agent_turns}</td><td class="num">${ms(l.avg_ms)}</td><td class="num">${ms(l.p50_ms)}</td><td class="num"><strong>${ms(l.p95_ms)}</strong></td><td class="num">${ms(l.max_ms)}</td></tr>`).join("")}
        </tbody></table></div>
        <p class="panel-foot">${r.mode === "demo" ? "Demo latency is simulated from reply length, tool calls and prompt size." : "Wall-clock time per agent turn, including tool calls."}</p>
      </div>
    </div>
    <div class="panel">${panelHead("Scenarios", I.chat, "scenario_results", "click a row to open the transcript")}<div class="table-wrap"><table>
      <thead><tr><th>Status</th><th>Scenario</th><th>Category</th><th>Channel</th><th class="num">Turns</th><th>Failed checks / judge criteria</th><th></th></tr></thead>
      <tbody>${s.scenarios.map((x) => `
        <tr class="click" tabindex="0" data-href="#/result/${enc(x.result_id)}">
          <td>${statusBadge(x.passed)}${x.judge_disagreement ? ' <span class="badge warn" title="Judge trials disagree">REVIEW</span>' : ""}</td>
          <td><strong>${esc(x.title)}</strong><div class="cell-sub">${esc(x.scenario_id)}</div></td>
          <td>${esc(x.category)}</td><td>${esc(x.channel)}</td>
          <td class="num">${x.turns}/${x.max_turns}</td>
          <td>${(x.failed_checks || "").split(", ").filter(Boolean).map((c) => `<span class="chip red">${esc(c)}</span>`).join("")}
              ${(x.failed_criteria || "").split(",").filter(Boolean).map((c) => `<span class="chip">judge:${esc(c)}</span>`).join("")}
              ${x.error ? `<span class="chip red">${esc(x.error)}</span>` : ""}</td>
          <td>${I.chevron("row-arrow")}</td>
        </tr>`).join("")}</tbody></table></div></div>`;

  const cats = s.categories.slice().sort((a, b) => a.category.localeCompare(b.category));
  chart("c-cat", (P) => ({
    type: "bar",
    data: { labels: cats.map((c) => c.category), datasets: [
      { label: "Deterministic checks", data: cats.map((c) => c.checks_pass_rate), backgroundColor: P.base, borderRadius: 4, maxBarThickness: 16 },
      { label: "LLM judge", data: cats.map((c) => c.judge_pass_rate), backgroundColor: P.accent2, borderRadius: 4, maxBarThickness: 16 },
      { label: "Overall pass", data: cats.map((c) => c.pass_rate), backgroundColor: P.accent, borderRadius: 4, maxBarThickness: 16 },
    ] },
    options: { scales: { y: pctAxis(P), x: catAxis(P) }, plugins: { legend: { position: "bottom" } } },
  }));
  chart("c-fail", (P) => {
    const sevColor = { critical: P.danger, major: P.warning, minor: P.base };
    return {
      type: "bar",
      data: { labels: s.failure_reasons.map((f) => f.reason), datasets: [{ label: "Scenarios", data: s.failure_reasons.map((f) => f.scenarios), backgroundColor: s.failure_reasons.map((f) => sevColor[f.severity] || P.base), borderRadius: 6, maxBarThickness: 18 }] },
      options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: (ctx) => `severity: ${s.failure_reasons[ctx.dataIndex].severity}` } } },
        scales: { x: { ticks: { precision: 0, color: P.text3 }, border: { display: false }, grid: { color: P.border } }, y: { grid: { display: false }, border: { color: P.border }, ticks: { color: P.text2, font: { family: P.mono, size: 11 } } } } },
    };
  });
}

function toolCard(call, flagged) {
  const args = JSON.stringify(call.arguments ?? {});
  const bad = call.is_error || flagged;
  return `<details class="tool${bad ? " error" : ""}">
    <summary>${I.wrench("t-icon")}<span class="t-name">${esc(call.name)}</span><span class="t-args">${esc(args.length > 90 ? args.slice(0, 90) + "…" : args)}</span>${call.is_error ? '<span class="badge fail">error</span>' : ""}${flagged && !call.is_error ? '<span class="badge fail">check failed</span>' : ""}${I.chevron("chev")}</summary>
    <pre><span class="k">arguments</span> ${esc(JSON.stringify(call.arguments, null, 2))}\n\n<span class="k">result</span> ${esc(JSON.stringify(call.result, null, 2))}</pre></details>`;
}

// Evidence quotes of all judge trials for one criterion; identical quotes are shown once.
function evidenceList(trials, criterion) {
  const quotes = new Map();
  trials.forEach((t) => t.scores[criterion].evidence.forEach((e) => {
    const key = `${e.turn}|${e.quote}`;
    if (!quotes.has(key)) quotes.set(key, { ...e, trials: [] });
    quotes.get(key).trials.push(t.trial);
  }));
  return [...quotes.values()].map((e) => `<div class="quote ${e.grounded ? "" : "ungrounded"}">“${esc(e.quote)}”
    <span class="src">turn ${esc(e.turn)} · trial ${esc(e.trials.join(", "))}${e.grounded ? "" : " · NOT FOUND in transcript"}</span></div>`).join("");
}

async function resultPage(resultId) {
  setNav("overview");
  const d = await api(`/api/results/${enc(resultId)}`);
  showDemo(d.run.mode === "demo", "<strong>Demo data.</strong> This transcript was produced by the rule-based demo agent and a scripted customer.");
  const sc = d.scenario;
  const failed = d.checks.filter((c) => !c.passed);
  const flagsByTurn = {};
  failed.forEach((c) => { if (c.turn_index !== null) (flagsByTurn[c.turn_index] = flagsByTurn[c.turn_index] || []).push(c); });
  const toolFlags = new Set(failed.filter((c) => c.check_type === "expected_tool" || c.check_type === "forbidden_tool").map((c) => `${c.turn_index}:${c.name}`));

  const transcript = d.turns.map((t) => {
    const isAgent = t.role === "agent";
    const flags = isAgent ? flagsByTurn[t.index] || [] : [];
    const slow = isAgent && t.latency_ms !== null && sc.max_latency_ms && t.latency_ms > sc.max_latency_ms;
    return `<div class="turn ${isAgent ? "agent" : "user"} ${flags.length ? "flagged" : ""}">
      <div class="avatar" title="${isAgent ? "Agent" : "Customer"}">${isAgent ? I.bot() : I.user()}</div>
      <div class="turn-body">
        <div class="who"><b>${isAgent ? "Agent" : "Customer"}</b><span>turn ${esc(t.index)}</span>${isAgent && t.latency_ms !== null ? `<span class="lat ${slow ? "slow" : ""}">${ms(t.latency_ms)}</span>` : ""}</div>
        ${(t.tool_calls || []).map((c) => toolCard(c, toolFlags.has(`${t.index}:${c.name}`))).join("")}
        <div class="bubble">${esc(t.text) || '<span class="faint">(no text)</span>'}</div>
        ${flags.length ? `<div class="flags">${flags.map((f) => `<div class="flag">${I.alert()}<span><b>${esc(f.check_type)}:${esc(f.name)}</b>${esc(f.message)}</span></div>`).join("")}</div>` : ""}
      </div>
    </div>`;
  }).join("");

  const trials = d.judge_trials;
  const criteria = trials.length ? Object.keys(trials[0].scores) : [];
  const scoreCls = (x) => (x.passed ? "pass" : "fail");
  const judgeHtml = criteria.map((c) => `
    <div class="criterion">
      <div class="criterion-head"><strong>${esc(pretty(c))}</strong><span class="score">${trials.map((t) => `<span class="${scoreCls(t.scores[c])}" title="trial ${esc(t.trial)}">${esc(t.scores[c].score)}</span>`).join("")}</span></div>
      <div class="rationale">${esc(trials[0].scores[c].rationale)}</div>
      ${evidenceList(trials, c)}
    </div>`).join("");

  const lastTurn = d.turns.length ? d.turns[d.turns.length - 1].index : 0;
  app.innerHTML = `
    <div class="page-head"><div><div class="eyebrow"><a href="#/">Overview</a> / <a href="#/run/${enc(d.run.id)}">${esc(short(d.run.label))}</a> / Transcript</div>
      <h1>${esc(sc.title)} ${statusBadge(d.passed)} ${d.judge_disagreement ? '<span class="badge warn">JUDGE DISAGREES</span>' : ""}</h1>
      <div class="meta"><span class="mono">${esc(sc.id)}</span><span>Category <b>${esc(sc.category)}</b></span><span>Channel <b>${esc(sc.channel)}</b></span><span>Turns <b>${esc(lastTurn)}/${esc(d.max_turns)}</b></span><span>Ended <b>${esc(pretty(d.end_reason))}</b></span></div></div></div>
    <div class="grid split">
      <div class="panel">${panelHead(`Transcript ${failed.length ? `<span class="badge fail">${failed.length} failed check${failed.length > 1 ? "s" : ""}</span>` : '<span class="badge pass">all checks passed</span>'}`, I.chat)}
        <div class="transcript">${transcript}</div>${d.error ? `<div class="flag" style="margin-top:12px">${I.alert()}<span>${esc(d.error)}</span></div>` : ""}</div>
      <div class="grid">
        <div class="panel">${panelHead("Scenario", I.target)}<dl class="facts">
          <dt>Persona</dt><dd>${esc(sc.persona)}</dd><dt>Goal</dt><dd>${esc(sc.goal)}</dd>
          <dt>Success</dt><dd><ul class="clean">${sc.success_criteria.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></dd>
          <dt>Limits</dt><dd>${esc(sc.max_turns)} turns · ${esc(Number(sc.max_latency_ms).toLocaleString())} ms per turn</dd></dl></div>
        <div class="panel">${panelHead("Deterministic checks", I.check, "", `${d.checks.length - failed.length}/${d.checks.length} passed`)}${d.checks.map((c) => `
          <div class="check"><span class="icon ${c.passed ? "ok" : "bad"}">${c.passed ? I.check() : I.x()}</span><div style="min-width:0">
            <div class="name">${esc(c.check_type)}:${esc(c.name)} ${c.passed ? "" : `<span class="badge ${c.severity === "critical" ? "fail" : "warn"}">${esc(c.severity)}</span>`}${c.turn_index !== null && !c.passed ? ` <span class="faint">turn ${esc(c.turn_index)}</span>` : ""}</div>
            <div class="msgtext">${esc(c.message)}</div></div></div>`).join("")}</div>
        <div class="panel">${panelHead("LLM judge", I.gavel, "", `scores per trial · ${esc(trials[0]?.judge || "")}`)}${judgeHtml || '<p class="muted">No judge results.</p>'}
          ${trials.map((t) => `<div class="trial-line">${statusBadge(t.verdict)}<span><b>Trial ${esc(t.trial)}</b> · ${esc(t.summary)}</span></div>`).join("")}</div>
        ${d.lead ? `<div class="panel">${panelHead("Lead &amp; intent (GTM)", I.users)}<dl class="facts">
          <dt>Intent</dt><dd>${esc(pretty(d.lead.primary_intent))}</dd><dt>Product</dt><dd>${esc(d.lead.product_interest || "–")}</dd>
          <dt>Purchase</dt><dd>${esc(d.lead.purchase_intent)}</dd><dt>Upsell</dt><dd>${esc(d.lead.upsell_opportunity || "–")}</dd>
          <dt>Churn risk</dt><dd>${esc(d.lead.churn_risk)}</dd><dt>Sentiment</dt><dd>${esc(d.lead.sentiment)}</dd>
          <dt>Summary</dt><dd>${esc(d.lead.summary)}</dd></dl></div>` : ""}
      </div>
    </div>`;
}

async function comparePage(params) {
  setNav("compare");
  const runs = await api("/api/runs");
  setBanner(runs);
  if (runs.length < 2) {
    app.innerHTML = emptyState("Need two runs", "<p>Run <code>python -m evallab demo</code> to create a v1 and a v2 run.</p>", I.compare);
    return;
  }
  const a = params.get("a") || runs[runs.length - 2].id;
  const b = params.get("b") || runs[runs.length - 1].id;
  const opts = (sel) => runs.map((r) => `<option value="${esc(r.id)}" ${r.id === sel ? "selected" : ""}>${esc(short(r.label))} (${pct(r.pass_rate)})</option>`).join("");
  const c = await api(`/api/compare?a=${enc(a)}&b=${enc(b)}`);
  const group = (key, cls, title, hint, icon) => {
    const items = c.scenarios.filter((s) => s.change === key);
    return `<div class="panel group ${cls}"><div class="group-head"><span class="g-icon">${icon()}</span><div><h3>${title}</h3><small>${hint}</small></div><span class="g-count">${countSpan("group:" + key, num(items.length))}</span></div>
      ${items.length ? `<div class="scn-list">${items.map((s) => `
        <a class="scn-item" href="#/result/${enc(s.result_b)}"><strong>${esc(s.title)}</strong><div class="cell-sub">${esc(s.scenario_id)} · ${esc(s.category)}</div>
        <div>${(s.failed_checks_b || "").split(", ").filter(Boolean).map((x) => `<span class="chip red">${esc(x)}</span>`).join("")}${(s.failed_criteria_b || "").split(",").filter(Boolean).map((x) => `<span class="chip">judge:${esc(x)}</span>`).join("")}</div></a>`).join("")}</div>`
        : '<div class="group-empty">None</div>'}</div>`;
  };
  const p = c.mcnemar_p;
  const dl = c.pass_rate_delta;
  app.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">${I.compare()}Regression check</div><h1>Run comparison</h1><p>Candidate (B) compared with baseline (A) on ${c.common_scenarios} shared scenarios.</p></div>
      <form id="cmp" class="cmp-form"><label class="field">A <select name="a" aria-label="Baseline run">${opts(a)}</select></label><label class="field">B <select name="b" aria-label="Candidate run">${opts(b)}</select></label><button class="btn">${I.repeat()}Compare</button></form></div>
    <div class="kpis">
      ${kpi("Baseline (A)", num(c.pass_rate_a, 1, "%"), esc(short(c.run_a.label)), "", I.flask())}
      ${kpi("Candidate (B)", num(c.pass_rate_b, 1, "%"), esc(short(c.run_b.label)), "", I.flask())}
      ${kpi("Pass-rate delta", num(dl, 1, " pp", true), `${c.groups.newly_passing.length} fixed · ${c.groups.newly_failing.length} broken`, dl > 0 ? "up" : dl < 0 ? "down" : "", I.trend())}
      ${kpi("McNemar exact p", p === null ? "–" : num(p, 3), p === null ? "no changed scenarios" : p < 0.05 ? "change unlikely to be noise" : "could be noise at this sample size", "", I.scale())}
    </div>
    <div class="panel-head" style="margin:4px 0 -6px"><h2>${I.list("h-icon")}Scenario changes</h2>${sqlButton("regression_scenarios")}</div>
    <div class="groups">
      ${group("newly_passing", "fixed", "Fixed", "failing in A, passing in B", I.check)}
      ${group("newly_failing", "broke", "Broke", "passing in A, failing in B", I.x)}
      ${group("still_failing", "still", "Still failing", "failing in both runs", I.alert)}
    </div>
    <p class="faint" style="margin:-4px 0 0;font-size:12.5px">${c.groups.still_passing.length} scenarios pass in both runs.</p>
    <div class="grid g2">
      <div class="panel lift">${panelHead("Judge criteria: average score", I.gavel, "regression_criteria")}<div class="chart-box"><canvas id="c-crit"></canvas></div></div>
      <div class="panel lift">${panelHead("Pass rate by category", I.chart, "regression_categories")}<div class="chart-box"><canvas id="c-cat"></canvas></div></div>
    </div>
    <div class="grid g2">
      <div class="panel">${panelHead("Category deltas", I.trend, "regression_categories", "B vs A")}
        <div class="cat-deltas">${c.categories.map((x) => {
          const da = x.pass_rate_a, db = x.pass_rate_b;
          const dd = da === null || db === null || da === undefined || db === undefined ? null : db - da;
          return `<div class="cat-row"><span class="cat-name" title="${esc(x.category)}">${esc(x.category)}</span>
            <div class="cat-track" title="A ${pct(da)} · B ${pct(db)}"><span class="b" style="width:${Math.max(0, Math.min(100, db || 0))}%"></span><span class="a" style="left:calc(${Math.max(0, Math.min(100, da || 0))}% - 1px)"></span></div>
            ${deltaPill(dd, " pp", false, 0)}</div>`; }).join("")}</div>
        <div class="legend-inline"><span><i></i>Candidate (B)</span><span><i class="mark"></i>Baseline (A)</span></div>
      </div>
      <div class="panel">${panelHead("Failed checks by type", I.alert, "regression_checks")}<div class="table-wrap"><table><thead><tr><th>Check</th><th class="num">A</th><th class="num">B</th><th class="num">Change</th></tr></thead><tbody>
        ${c.checks.map((x) => { const d = x.failures_b - x.failures_a; return `<tr><td><code>${esc(x.check_type)}</code></td><td class="num">${x.failures_a}</td><td class="num">${x.failures_b}</td><td class="num">${deltaPill(d, "", true)}</td></tr>`; }).join("")}</tbody></table></div></div>
    </div>`;
  document.getElementById("cmp").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    location.hash = `#/compare?a=${enc(f.get("a"))}&b=${enc(f.get("b"))}`;
  });
  chart("c-crit", (P) => ({
    type: "bar",
    data: { labels: c.criteria.map((x) => pretty(x.criterion)), datasets: [
      { label: "A: " + short(c.run_a.label), data: c.criteria.map((x) => x.avg_a), backgroundColor: P.base, borderRadius: 5, maxBarThickness: 22 },
      { label: "B: " + short(c.run_b.label), data: c.criteria.map((x) => x.avg_b), backgroundColor: grad(P.accent, P.accent2), borderRadius: 5, maxBarThickness: 22 }] },
    options: { scales: { y: { min: 1, max: 5, ticks: { color: P.text3 }, border: { display: false }, grid: { color: P.border } }, x: catAxis(P) }, plugins: { legend: { position: "bottom" } } },
  }));
  chart("c-cat", (P) => ({
    type: "bar",
    data: { labels: c.categories.map((x) => x.category), datasets: [
      { label: "A", data: c.categories.map((x) => x.pass_rate_a), backgroundColor: P.base, borderRadius: 5, maxBarThickness: 22 },
      { label: "B", data: c.categories.map((x) => x.pass_rate_b), backgroundColor: grad(P.accent, P.accent2), borderRadius: 5, maxBarThickness: 22 }] },
    options: { scales: { y: pctAxis(P), x: catAxis(P) }, plugins: { legend: { position: "bottom" } } },
  }));
}

async function gtmPage(runId) {
  setNav("gtm");
  const runs = await api("/api/runs");
  setBanner(runs);
  if (!runs.length) {
    app.innerHTML = emptyState("No runs yet", "<p>Run <code>python -m evallab demo</code> first.</p>", I.users);
    return;
  }
  const id = runId || runs[runs.length - 1].id;
  const run = runs.find((r) => r.id === id);
  const g = await api(`/api/runs/${enc(id)}/gtm`);
  const total = g.intents.reduce((s, x) => s + x.conversations, 0);
  const signals = g.intents.reduce((s, x) => s + x.buying_signals, 0);
  const upsell = g.intents.reduce((s, x) => s + x.upsell_opportunities, 0);
  const churn = g.intents.reduce((s, x) => s + x.high_churn_risk, 0);
  app.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">${I.users()}Go-to-market</div><h1>GTM insights</h1><p>Structured lead and intent data extracted from every conversation of <strong>${esc(run ? run.label : id)}</strong>.</p></div>
      <label class="field">Run <select id="gtm-run">${runs.map((r) => `<option value="${esc(r.id)}" ${r.id === id ? "selected" : ""}>${esc(short(r.label))}</option>`).join("")}</select></label></div>
    ${total ? `
    <div class="kpis">
      ${kpi("Conversations analysed", num(total), "one lead record each", "", I.chat())}
      ${kpi("Buying signals", num(signals), "purchase intent medium or high", "", I.target())}
      ${kpi("Upsell opportunities", num(upsell), "installation, warranty, cross-sell", "", I.trend())}
      ${kpi("High churn risk", num(churn), "frustrated or refused customers", churn ? "down" : "", I.alert())}
    </div>
    <div class="grid g2">
      <div class="panel lift">${panelHead("Contact reasons", I.chart, "gtm_intents")}<div class="chart-box"><canvas id="c-int"></canvas></div></div>
      <div class="panel">${panelHead("Signals by intent", I.list, "gtm_intents")}<div class="table-wrap"><table><thead><tr><th>Intent</th><th class="num">Conv.</th><th class="num">Buying</th><th class="num">Contacts</th><th class="num">Upsell</th><th class="num">Churn</th></tr></thead><tbody>
        ${g.intents.map((x) => `<tr><td>${esc(pretty(x.primary_intent))}</td><td class="num"><strong>${x.conversations}</strong></td><td class="num">${x.buying_signals}</td><td class="num">${x.contacts_captured}</td><td class="num">${x.upsell_opportunities}</td><td class="num ${x.high_churn_risk ? "down" : ""}">${x.high_churn_risk}</td></tr>`).join("")}</tbody></table></div></div>
    </div>
    <div class="panel">${panelHead("Leads and accounts to act on", I.users, "gtm_leads", "click a row to open the conversation")}<div class="table-wrap scroll"><table><thead><tr><th>Conversation</th><th>Intent</th><th>Product interest</th><th>Purchase intent</th><th>Upsell</th><th>Churn risk</th><th>CRM note</th></tr></thead><tbody>
      ${g.leads.map((l) => `<tr class="click" tabindex="0" data-href="#/result/${enc(l.result_id)}"><td><code>${esc(l.scenario_id)}</code></td><td>${esc(pretty(l.primary_intent))}</td><td>${esc(l.product_interest || "–")}</td>
        <td><span class="badge ${l.purchase_intent === "high" ? "pass" : l.purchase_intent === "medium" ? "info" : "neutral"}">${esc(l.purchase_intent)}</span></td><td>${esc(l.upsell_opportunity || "–")}</td>
        <td><span class="badge ${l.churn_risk === "high" ? "fail" : l.churn_risk === "medium" ? "warn" : "neutral"}">${esc(l.churn_risk)}</span></td><td class="note">${esc(l.summary)}</td></tr>`).join("")}</tbody></table></div></div>`
    : emptyState("No lead data", "<p>This run has no lead data (lead extraction was off).</p>", I.users)}`;
  document.getElementById("gtm-run").addEventListener("change", (e) => { location.hash = `#/gtm/${enc(e.target.value)}`; });
  if (total) {
    chart("c-int", (P) => ({
      type: "doughnut",
      data: { labels: g.intents.map((x) => pretty(x.primary_intent)), datasets: [{ data: g.intents.map((x) => x.conversations),
        backgroundColor: [P.accent, P.accent2, "#06b6d4", P.success, P.warning, P.danger, "#ec4899", P.base, P.info], borderColor: P.surface, borderWidth: 2, hoverOffset: 6 }] },
      options: { cutout: "64%", plugins: { legend: { position: window.innerWidth < 640 ? "bottom" : "right" } } },
    }));
  }
}

// ---------- router ----------

async function route() {
  charts.forEach((c) => c.destroy());
  charts = [];
  chartSpecs = [];
  nav.classList.remove("open");
  document.getElementById("nav-toggle").setAttribute("aria-expanded", "false");
  const hash = location.hash.replace(/^#/, "") || "/";
  const [path, query] = hash.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  try {
    if (parts[0] === "run" && parts[1]) await runPage(parts[1]);
    else if (parts[0] === "result" && parts[1]) await resultPage(parts[1]);
    else if (parts[0] === "compare") await comparePage(new URLSearchParams(query || ""));
    else if (parts[0] === "gtm") await gtmPage(parts[1]);
    else await overview();
    window.scrollTo(0, 0);
    animatePage();
  } catch (err) {
    app.innerHTML = emptyState("Something went wrong", `<p>${esc(err.message)}</p><p><a href="#/">Back to overview</a></p>`, I.alert);
    if (motion) gsap.fromTo(app.querySelector(".empty"), { x: -6 }, { x: 0, duration: 0.6, ease: "elastic.out(1, .3)" });
  }
}

// ---------- SQL drawer ----------

const SQL_KW = /(--[^\n]*)|('(?:[^']|'')*')|\b(\d+(?:\.\d+)?)\b|\b(SELECT|FROM|WHERE|JOIN|LEFT|INNER|OUTER|ON|AND|OR|NOT|AS|GROUP|BY|ORDER|HAVING|LIMIT|WITH|UNION|ALL|CASE|WHEN|THEN|ELSE|END|DESC|ASC|COUNT|SUM|AVG|MIN|MAX|ROUND|DISTINCT|IN|IS|NULL|OVER|PARTITION|ROW_NUMBER|COALESCE|CAST|LIKE|EXISTS|BETWEEN|FILTER|NULLIF|IIF|REAL|INTEGER|TEXT)\b/gi;

function highlightSql(src) {
  let out = "";
  let last = 0;
  src.replace(SQL_KW, (m, cm, st, nm, kw, off) => {
    out += esc(src.slice(last, off));
    const cls = cm ? "cm" : st ? "st" : nm ? "nm" : "kw";
    out += `<span class="${cls}">${esc(m)}</span>`;
    last = off + m.length;
    return m;
  });
  return out + esc(src.slice(last));
}

let lastFocus = null;
let closeTimer = null;
function openSql(names) {
  const text = names.map((n) => `-- ${n}\n${sqlCache[n] ?? "(query not found)"}`).join("\n\n");
  document.getElementById("sql-title").textContent = names.join(", ");
  const body = document.getElementById("sql-body");
  body.dataset.raw = text;
  body.innerHTML = highlightSql(text);
  body.scrollTop = 0;
  clearTimeout(closeTimer);
  lastFocus = document.activeElement;
  sqlModal.hidden = false;
  void sqlModal.offsetWidth; // start the CSS transition from the closed state
  sqlModal.classList.add("open");
  document.body.classList.add("modal-open");
  document.getElementById("sql-close").focus();
}
function closeSql() {
  if (sqlModal.hidden) return;
  sqlModal.classList.remove("open");
  document.body.classList.remove("modal-open");
  closeTimer = setTimeout(() => { sqlModal.hidden = true; }, 180);
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}

document.addEventListener("click", async (e) => {
  const sql = e.target.closest("[data-sql]");
  if (sql) {
    e.stopPropagation();
    try {
      sqlCache = sqlCache || (await api("/api/sql"));
      openSql(sql.dataset.sql.split(","));
    } catch (err) {
      if (motion) gsap.fromTo(sql, { x: -6 }, { x: 0, duration: 0.6, ease: "elastic.out(1, .3)" });
    }
    return;
  }
  const row = e.target.closest("tr[data-href]");
  if (row && !e.target.closest("a")) location.hash = row.dataset.href;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeSql();
  if (e.key === "Enter") {
    const row = e.target.closest && e.target.closest("tr[data-href]");
    if (row) location.hash = row.dataset.href;
  }
});
document.getElementById("sql-close").addEventListener("click", closeSql);
sqlModal.addEventListener("click", (e) => { if (e.target.id === "sql-modal") closeSql(); });
document.getElementById("sql-copy").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  try {
    await navigator.clipboard.writeText(document.getElementById("sql-body").dataset.raw || "");
    btn.textContent = "Copied";
  } catch (err) {
    btn.textContent = "Copy failed";
  }
  setTimeout(() => { btn.textContent = "Copy"; }, 1400);
});

// ---------- shell ----------

document.getElementById("theme-toggle").addEventListener("click", () => setTheme(currentTheme() === "dark" ? "light" : "dark"));
document.getElementById("nav-toggle").addEventListener("click", (e) => {
  const open = nav.classList.toggle("open");
  e.currentTarget.setAttribute("aria-expanded", String(open));
});

if (motion) {
  gsap.ticker.lagSmoothing(0); // keep tweens on wall-clock time (no slow-motion after a stalled frame)
  gsap.from(".topbar", { y: -14, opacity: 0, duration: 0.5, ease: "power3.out", clearProps: "transform,opacity" });
  gsap.to(".glow.g1", { x: 90, y: 50, duration: 26, ease: "sine.inOut", yoyo: true, repeat: -1 });
  gsap.to(".glow.g2", { x: -80, y: 60, duration: 22, ease: "sine.inOut", yoyo: true, repeat: -1 });
}

window.addEventListener("hashchange", route);
route();
