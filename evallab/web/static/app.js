// Agent Eval Lab dashboard: a small hash-routed single-page app over the JSON API.
"use strict";

const app = document.getElementById("app");
const banner = document.getElementById("banner");
let charts = [];
let sqlCache = null;

const COLORS = { blue: "#2563eb", sky: "#93c5fd", slate: "#94a3b8", green: "#16a34a", red: "#dc2626", amber: "#d97706" };
Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
Chart.defaults.color = "#475569";
Chart.defaults.animation = false;

// ---------- helpers ----------

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v, digits = 1) => (v === null || v === undefined ? "–" : `${Number(v).toFixed(digits)}%`);
const ratio = (v) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
const ms = (v) => (v === null || v === undefined ? "–" : `${Math.round(v).toLocaleString()} ms`);
const signed = (v, unit = "") => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(unit === "pp" ? 1 : 2)}${unit ? " " + unit : ""}`);
const pretty = (s) => String(s ?? "").replace(/_/g, " ");

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function chart(id, config) {
  const canvas = document.getElementById(id);
  if (!canvas) return;
  config.options = Object.assign({ responsive: true, maintainAspectRatio: false }, config.options || {});
  charts.push(new Chart(canvas, config));
}

function kpi(label, value, sub = "", cls = "") {
  return `<div class="kpi"><div class="label">${esc(label)}</div><div class="value ${cls}">${value}</div><div class="sub">${sub}</div></div>`;
}

function sqlButton(names) {
  return `<button class="sql-btn" data-sql="${esc(names)}" title="Show the SQL behind this card">SQL</button>`;
}

function statusBadge(passed) {
  return passed ? '<span class="badge pass">PASS</span>' : '<span class="badge fail">FAIL</span>';
}

function modeBadge(mode) {
  const cls = { demo: "warn", live: "info", import: "neutral" }[mode] || "neutral";
  return `<span class="badge ${cls}">${esc(mode.toUpperCase())}</span>`;
}

function bar(value) {
  return `<div class="bar"><span style="width:${Math.max(0, Math.min(100, value || 0))}%"></span></div>`;
}

function setBanner(runs) {
  const demo = runs.some((r) => r.mode === "demo");
  banner.hidden = !demo;
  banner.innerHTML = demo
    ? "<strong>Demo data.</strong> Runs marked DEMO use a rule-based agent, a scripted customer, a heuristic judge and simulated latency. They show how the lab works, not how any real model performs."
    : "";
}

function setNav(name) {
  document.querySelectorAll("nav a[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name));
}

// ---------- pages ----------

async function overview() {
  setNav("overview");
  const runs = await api("/api/runs");
  setBanner(runs);
  if (!runs.length) {
    app.innerHTML = `<div class="panel empty"><h1>No runs yet</h1><p>Create two demo runs with <code>python -m evallab demo</code>, or a live run with <code>python -m evallab run</code>.</p></div>`;
    return;
  }
  const latest = runs[runs.length - 1];
  const previous = runs.length > 1 ? runs[runs.length - 2] : null;
  const [sumLatest, sumPrev] = await Promise.all([api(`/api/runs/${encodeURIComponent(latest.id)}`), previous ? api(`/api/runs/${encodeURIComponent(previous.id)}`) : null]);
  const delta = previous ? latest.pass_rate - previous.pass_rate : null;
  const agreement = sumLatest.judge_agreement;

  app.innerHTML = `
    <div class="page-head"><div><h1>Overview</h1><p>${runs.length} evaluation runs. Latest: <a href="#/run/${encodeURIComponent(latest.id)}">${esc(latest.label)}</a></p></div>
      ${previous ? `<a class="btn" href="#/compare?a=${encodeURIComponent(previous.id)}&b=${encodeURIComponent(latest.id)}">Compare latest two runs</a>` : ""}</div>
    <div class="kpis">
      ${kpi("Latest pass rate", pct(latest.pass_rate), `${latest.passed} of ${latest.scenarios} scenarios`)}
      ${kpi("Change vs previous run", previous ? signed(delta, "pp") : "–", previous ? esc(previous.label) : "only one run", delta > 0 ? "up" : delta < 0 ? "down" : "")}
      ${kpi("Judge verdict agreement", ratio(agreement.verdict_agreement), `Cohen's kappa ${agreement.kappa === null ? "–" : agreement.kappa.toFixed(2)}`)}
      ${kpi("Needs human review", latest.judge_disagreements, "judge trials disagree")}
    </div>
    <div class="grid g2">
      <div class="panel"><h2>Pass rate by run ${sqlButton("runs")}</h2><div class="chart-box"><canvas id="c-runs"></canvas></div></div>
      <div class="panel"><h2>Pass rate by category ${sqlButton("pass_rate_by_category")}</h2><div class="chart-box"><canvas id="c-cats"></canvas></div></div>
    </div>
    <div class="panel"><h2>Runs ${sqlButton("runs")}</h2><div class="table-wrap"><table>
      <thead><tr><th>Run</th><th>Mode</th><th>Agent</th><th>Simulator / judge</th><th class="num">Passed</th><th>Pass rate</th><th>Started (UTC)</th><th></th></tr></thead>
      <tbody>${runs.slice().reverse().map((r) => `
        <tr class="click" data-href="#/run/${encodeURIComponent(r.id)}">
          <td><strong>${esc(r.label)}</strong><div class="muted">${esc(r.id)}</div></td>
          <td>${modeBadge(r.mode)}</td>
          <td>${esc(r.agent_version || "")}<div class="muted">${esc(r.model || "")}</div></td>
          <td>${esc(r.simulator || "")} / ${esc(r.judge || "")}${r.judge_trials ? ` ×${r.judge_trials}` : ""}</td>
          <td class="num">${r.passed}/${r.scenarios}</td>
          <td><div style="display:flex;gap:8px;align-items:center">${bar(r.pass_rate)}<strong>${pct(r.pass_rate)}</strong></div></td>
          <td class="muted">${esc((r.started_at || "").replace("T", " ").replace("Z", ""))}</td>
          <td><a href="#/gtm/${encodeURIComponent(r.id)}">GTM</a></td>
        </tr>`).join("")}</tbody></table></div></div>`;

  chart("c-runs", {
    type: "bar",
    data: { labels: runs.map((r) => r.label.replace(/^DEMO - /, "")), datasets: [{ label: "Pass rate %", data: runs.map((r) => r.pass_rate), backgroundColor: runs.map((r, i) => (i === runs.length - 1 ? COLORS.blue : COLORS.sky)), borderRadius: 6 }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } } },
  });
  const cats = sumLatest.categories.map((c) => c.category).sort();
  const datasets = [];
  if (sumPrev) {
    const prevMap = Object.fromEntries(sumPrev.categories.map((c) => [c.category, c.pass_rate]));
    datasets.push({ label: previous.label.replace(/^DEMO - /, ""), data: cats.map((c) => prevMap[c] ?? null), backgroundColor: COLORS.slate, borderRadius: 4 });
  }
  const latestMap = Object.fromEntries(sumLatest.categories.map((c) => [c.category, c.pass_rate]));
  datasets.push({ label: latest.label.replace(/^DEMO - /, ""), data: cats.map((c) => latestMap[c]), backgroundColor: COLORS.blue, borderRadius: 4 });
  chart("c-cats", { type: "bar", data: { labels: cats, datasets }, options: { scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } }, plugins: { legend: { position: "bottom" } } } });
}

async function runPage(runId) {
  setNav("overview");
  const [s, runs] = await Promise.all([api(`/api/runs/${encodeURIComponent(runId)}`), api("/api/runs")]);
  setBanner(runs);
  const r = s.run;
  const ag = s.judge_agreement;
  const lat = s.latency;
  const voice = lat.find((l) => l.channel === "voice");
  const chat = lat.find((l) => l.channel === "chat");
  const idx = runs.findIndex((x) => x.id === r.id);
  const prev = idx > 0 ? runs[idx - 1] : null;

  app.innerHTML = `
    <div class="page-head"><div><h1>${esc(r.label)} ${modeBadge(r.mode)}</h1>
      <p>Agent <strong>${esc(r.agent_name || "")} ${esc(r.agent_version || "")}</strong> · ${esc(r.model || "")} · simulator ${esc(r.simulator)} · judge ${esc(r.judge)} ×${r.judge_trials}</p></div>
      <div style="display:flex;gap:8px">${prev ? `<a class="btn" href="#/compare?a=${encodeURIComponent(prev.id)}&b=${encodeURIComponent(r.id)}">Compare with previous</a>` : ""}<a class="btn" style="background:#0f172a" href="#/gtm/${encodeURIComponent(r.id)}">GTM insights</a></div></div>
    <div class="kpis">
      ${kpi("Pass rate", pct(r.pass_rate), `${r.passed} of ${r.scenarios} scenarios`)}
      ${kpi("Chat latency p95", ms(chat?.p95_ms), chat ? `p50 ${ms(chat.p50_ms)} · ${chat.agent_turns} turns` : "no chat turns")}
      ${kpi("Voice latency p95", ms(voice?.p95_ms), voice ? `p50 ${ms(voice.p50_ms)} · ${voice.agent_turns} turns` : "no voice turns")}
      ${kpi("Judge verdict agreement", ratio(ag.verdict_agreement), `kappa ${ag.kappa === null ? "–" : ag.kappa.toFixed(2)} · ${ag.pairs} pairs`)}
      ${kpi("Evidence quotes grounded", ratio(ag.quote_grounding), `${ag.ungrounded_quotes} not found in transcript`)}
    </div>
    <div class="grid g2">
      <div class="panel"><h2>Pass rate by category ${sqlButton("pass_rate_by_category")}</h2><div class="chart-box"><canvas id="c-cat"></canvas></div></div>
      <div class="panel"><h2>Top failure reasons ${sqlButton("top_failure_reasons")}</h2><div class="chart-box"><canvas id="c-fail"></canvas></div></div>
    </div>
    <div class="grid g2">
      <div class="panel"><h2>LLM judge: scores by criterion ${sqlButton("judge_criteria")}</h2>
        <table><thead><tr><th>Criterion</th><th class="num">Avg score</th><th class="num">Pass rate</th><th class="num">Exact agreement</th><th class="num">Within ±1</th></tr></thead><tbody>
        ${s.judge_criteria.map((c) => { const a = ag.criteria.find((x) => x.criterion === c.criterion) || {}; return `<tr><td>${esc(pretty(c.criterion))}</td><td class="num">${c.avg_score.toFixed(2)}</td><td class="num">${pct(c.pass_rate)}</td><td class="num">${ratio(a.exact_agreement)}</td><td class="num">${ratio(a.within_one)}</td></tr>`; }).join("")}
        </tbody></table>
        <p class="muted" style="margin:10px 0 0">Agreement compares judge trial 1 with trial 2 on the same transcript ${sqlButton("judge_agreement,verdict_pairs")}. ${ag.unstable.length ? `Unstable verdicts: ${ag.unstable.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}` : "No unstable verdicts."}</p>
      </div>
      <div class="panel"><h2>Latency by channel ${sqlButton("latency")}</h2>
        <table><thead><tr><th>Channel</th><th class="num">Agent turns</th><th class="num">Avg</th><th class="num">p50</th><th class="num">p95</th><th class="num">Max</th></tr></thead><tbody>
        ${lat.map((l) => `<tr><td>${esc(l.channel)}</td><td class="num">${l.agent_turns}</td><td class="num">${ms(l.avg_ms)}</td><td class="num">${ms(l.p50_ms)}</td><td class="num">${ms(l.p95_ms)}</td><td class="num">${ms(l.max_ms)}</td></tr>`).join("")}
        </tbody></table>
        <p class="muted" style="margin:10px 0 0">${r.mode === "demo" ? "Demo latency is simulated from reply length, tool calls and prompt size." : "Wall-clock time per agent turn, including tool calls."}</p>
      </div>
    </div>
    <div class="panel"><h2>Scenarios ${sqlButton("scenario_results")}</h2><div class="table-wrap"><table>
      <thead><tr><th>Status</th><th>Scenario</th><th>Category</th><th>Channel</th><th class="num">Turns</th><th>Failed checks / judge criteria</th></tr></thead>
      <tbody>${s.scenarios.map((x) => `
        <tr class="click" data-href="#/result/${x.result_id}">
          <td>${statusBadge(x.passed)}${x.judge_disagreement ? ' <span class="badge warn" title="Judge trials disagree">REVIEW</span>' : ""}</td>
          <td><strong>${esc(x.title)}</strong><div class="muted">${esc(x.scenario_id)}</div></td>
          <td>${esc(x.category)}</td><td>${esc(x.channel)}</td>
          <td class="num">${x.turns}/${x.max_turns}</td>
          <td>${(x.failed_checks || "").split(", ").filter(Boolean).map((c) => `<span class="chip red">${esc(c)}</span>`).join("")}
              ${(x.failed_criteria || "").split(",").filter(Boolean).map((c) => `<span class="chip">judge:${esc(c)}</span>`).join("")}
              ${x.error ? `<span class="chip red">${esc(x.error)}</span>` : ""}</td>
        </tr>`).join("")}</tbody></table></div></div>`;

  const cats = s.categories.slice().sort((a, b) => a.category.localeCompare(b.category));
  chart("c-cat", {
    type: "bar",
    data: { labels: cats.map((c) => c.category), datasets: [
      { label: "Deterministic checks", data: cats.map((c) => c.checks_pass_rate), backgroundColor: COLORS.sky, borderRadius: 4 },
      { label: "LLM judge", data: cats.map((c) => c.judge_pass_rate), backgroundColor: COLORS.slate, borderRadius: 4 },
      { label: "Overall pass", data: cats.map((c) => c.pass_rate), backgroundColor: COLORS.blue, borderRadius: 4 },
    ] },
    options: { scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } }, plugins: { legend: { position: "bottom" } } },
  });
  const sevColor = { critical: COLORS.red, major: COLORS.amber, minor: COLORS.slate };
  chart("c-fail", {
    type: "bar",
    data: { labels: s.failure_reasons.map((f) => f.reason), datasets: [{ label: "Scenarios", data: s.failure_reasons.map((f) => f.scenarios), backgroundColor: s.failure_reasons.map((f) => sevColor[f.severity] || COLORS.slate), borderRadius: 4 }] },
    options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: (ctx) => `severity: ${s.failure_reasons[ctx.dataIndex].severity}` } } }, scales: { x: { ticks: { precision: 0 } }, y: { ticks: { font: { family: "Consolas, monospace", size: 11 } } } } },
  });
}

function toolCard(call, flagged) {
  const args = JSON.stringify(call.arguments);
  return `<details class="tool ${call.is_error ? "error" : ""}${flagged ? " error" : ""}">
    <summary>⚙ ${esc(call.name)}(${esc(args.length > 90 ? args.slice(0, 90) + "…" : args)}) ${call.is_error ? '<span class="badge fail">error</span>' : ""}</summary>
    <pre>arguments: ${esc(JSON.stringify(call.arguments, null, 2))}\n\nresult: ${esc(JSON.stringify(call.result, null, 2))}</pre></details>`;
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
    <span class="muted">turn ${e.turn} · trial ${e.trials.join(", ")}${e.grounded ? "" : " · NOT FOUND in transcript"}</span></div>`).join("");
}

async function resultPage(resultId) {
  setNav("overview");
  const d = await api(`/api/results/${encodeURIComponent(resultId)}`);
  banner.hidden = d.run.mode !== "demo";
  if (d.run.mode === "demo") banner.innerHTML = "<strong>Demo data.</strong> This transcript was produced by the rule-based demo agent and a scripted customer.";
  const sc = d.scenario;
  const failed = d.checks.filter((c) => !c.passed);
  const flagsByTurn = {};
  failed.forEach((c) => { if (c.turn_index !== null) (flagsByTurn[c.turn_index] = flagsByTurn[c.turn_index] || []).push(c); });
  const toolFlags = new Set(failed.filter((c) => c.check_type === "expected_tool" || c.check_type === "forbidden_tool").map((c) => `${c.turn_index}:${c.name}`));

  const transcript = d.turns.map((t) => {
    const flags = t.role === "agent" ? flagsByTurn[t.index] || [] : [];
    return `<div class="msg ${t.role} ${flags.length ? "flagged" : ""}">
      <div class="who"><span>${t.role === "user" ? "Customer" : "Agent"} · turn ${t.index}</span>${t.role === "agent" && t.latency_ms !== null ? `<span>${ms(t.latency_ms)}</span>` : ""}</div>
      <div class="text">${esc(t.text) || '<span class="muted">(no text)</span>'}</div>
      ${(t.tool_calls || []).map((c) => toolCard(c, toolFlags.has(`${t.index}:${c.name}`))).join("")}
      ${flags.length ? `<div class="flags">${flags.map((f) => `<div class="flag"><b>${esc(f.check_type)}:${esc(f.name)}</b> ${esc(f.message)}</div>`).join("")}</div>` : ""}
    </div>`;
  }).join("");

  const trials = d.judge_trials;
  const criteria = trials.length ? Object.keys(trials[0].scores) : [];
  const scoreCls = (sc) => (sc.passed ? "pass" : "fail");
  const judgeHtml = criteria.map((c) => `
    <div class="criterion">
      <div class="criterion-head"><strong>${esc(pretty(c))}</strong><span class="score">${trials.map((t) => `<span class="${scoreCls(t.scores[c])}" title="trial ${t.trial}">${t.scores[c].score}</span>`).join("")}</span></div>
      <div class="muted" style="margin-top:4px">${esc(trials[0].scores[c].rationale)}</div>
      ${evidenceList(trials, c)}
    </div>`).join("");

  app.innerHTML = `
    <div class="page-head"><div><h1>${esc(sc.title)} ${statusBadge(d.passed)} ${d.judge_disagreement ? '<span class="badge warn">JUDGE DISAGREES</span>' : ""}</h1>
      <p><a href="#/run/${encodeURIComponent(d.run.id)}">${esc(d.run.label)}</a> · ${esc(sc.id)} · ${esc(sc.category)} · ${esc(sc.channel)} · ${d.turns.length ? d.turns[d.turns.length - 1].index : 0}/${d.max_turns} turns · ended: ${esc(pretty(d.end_reason))}</p></div></div>
    <div class="grid split">
      <div class="panel"><h2>Transcript ${failed.length ? `<span class="badge fail">${failed.length} failed check${failed.length > 1 ? "s" : ""}</span>` : '<span class="badge pass">all checks passed</span>'}</h2>
        <div class="transcript">${transcript}</div>${d.error ? `<p class="flag">${esc(d.error)}</p>` : ""}</div>
      <div class="grid">
        <div class="panel"><h2>Scenario</h2><dl class="facts">
          <dt>Persona</dt><dd>${esc(sc.persona)}</dd><dt>Goal</dt><dd>${esc(sc.goal)}</dd>
          <dt>Success</dt><dd><ul class="clean" style="margin:0">${sc.success_criteria.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></dd>
          <dt>Limits</dt><dd>${sc.max_turns} turns · ${sc.max_latency_ms.toLocaleString()} ms per turn</dd></dl></div>
        <div class="panel"><h2>Deterministic checks</h2>${d.checks.map((c) => `
          <div class="check"><span class="icon ${c.passed ? "ok" : "bad"}">${c.passed ? "✓" : "✕"}</span><div>
            <div class="name">${esc(c.check_type)}:${esc(c.name)} ${c.passed ? "" : `<span class="badge ${c.severity === "critical" ? "fail" : "warn"}">${esc(c.severity)}</span>`}${c.turn_index !== null && !c.passed ? ` <span class="muted">turn ${c.turn_index}</span>` : ""}</div>
            <div class="msgtext">${esc(c.message)}</div></div></div>`).join("")}</div>
        <div class="panel"><h2>LLM judge <span class="muted" style="font-weight:400">scores per trial · ${esc(trials[0]?.judge || "")}</span></h2>${judgeHtml || '<p class="muted">No judge results.</p>'}
          ${trials.map((t) => `<p class="muted" style="margin:8px 0 0">Trial ${t.trial}: ${statusBadge(t.verdict)} ${esc(t.summary)}</p>`).join("")}</div>
        ${d.lead ? `<div class="panel"><h2>Lead &amp; intent (GTM)</h2><dl class="facts">
          <dt>Intent</dt><dd>${esc(pretty(d.lead.primary_intent))}</dd><dt>Product</dt><dd>${esc(d.lead.product_interest || "–")}</dd>
          <dt>Purchase intent</dt><dd>${esc(d.lead.purchase_intent)}</dd><dt>Upsell</dt><dd>${esc(d.lead.upsell_opportunity || "–")}</dd>
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
    app.innerHTML = `<div class="panel empty"><h1>Need two runs</h1><p>Run <code>python -m evallab demo</code> to create a v1 and a v2 run.</p></div>`;
    return;
  }
  const a = params.get("a") || runs[runs.length - 2].id;
  const b = params.get("b") || runs[runs.length - 1].id;
  const opts = (sel) => runs.map((r) => `<option value="${esc(r.id)}" ${r.id === sel ? "selected" : ""}>${esc(r.label)} (${pct(r.pass_rate)})</option>`).join("");
  const c = await api(`/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  const list = (key, cls, title) => {
    const items = c.scenarios.filter((s) => s.change === key);
    return `<div class="list-group"><h3><span class="badge ${cls}">${items.length}</span> ${title}</h3>${items.length ? `<table><tbody>${items.map((s) => `
      <tr class="click" data-href="#/result/${s.result_b}"><td><strong>${esc(s.title)}</strong> <span class="muted">${esc(s.scenario_id)} · ${esc(s.category)}</span>
      <div>${(s.failed_checks_b || "").split(", ").filter(Boolean).map((x) => `<span class="chip red">${esc(x)}</span>`).join("")}${(s.failed_criteria_b || "").split(",").filter(Boolean).map((x) => `<span class="chip">judge:${esc(x)}</span>`).join("")}</div></td></tr>`).join("")}</tbody></table>` : '<p class="muted">None</p>'}</div>`;
  };
  const p = c.mcnemar_p;
  app.innerHTML = `
    <div class="page-head"><div><h1>Run comparison</h1><p>Candidate (B) compared with baseline (A) on ${c.common_scenarios} shared scenarios.</p></div>
      <form id="cmp" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><label>A <select name="a">${opts(a)}</select></label><label>B <select name="b">${opts(b)}</select></label><button class="btn">Compare</button></form></div>
    <div class="kpis">
      ${kpi("Baseline (A)", pct(c.pass_rate_a), esc(c.run_a.label))}
      ${kpi("Candidate (B)", pct(c.pass_rate_b), esc(c.run_b.label))}
      ${kpi("Pass-rate delta", signed(c.pass_rate_delta, "pp"), `${c.groups.newly_passing.length} fixed · ${c.groups.newly_failing.length} broken`, c.pass_rate_delta > 0 ? "up" : c.pass_rate_delta < 0 ? "down" : "")}
      ${kpi("McNemar exact p", p === null ? "–" : p.toFixed(3), p === null ? "no changed scenarios" : p < 0.05 ? "change unlikely to be noise" : "could be noise at this sample size")}
    </div>
    <div class="grid g2">
      <div class="panel"><h2>Scenario changes ${sqlButton("regression_scenarios")}</h2>
        ${list("newly_failing", "fail", "Newly failing (regressions)")}${list("newly_passing", "pass", "Newly passing (fixes)")}${list("still_failing", "warn", "Still failing")}
        <p class="muted" style="margin-top:12px">${c.groups.still_passing.length} scenarios pass in both runs.</p></div>
      <div class="grid">
        <div class="panel"><h2>Judge criteria: average score ${sqlButton("regression_criteria")}</h2><div class="chart-box"><canvas id="c-crit"></canvas></div></div>
        <div class="panel"><h2>Pass rate by category ${sqlButton("regression_categories")}</h2><div class="chart-box"><canvas id="c-cat"></canvas></div></div>
        <div class="panel"><h2>Failed checks by type ${sqlButton("regression_checks")}</h2><table><thead><tr><th>Check</th><th class="num">A</th><th class="num">B</th><th class="num">Change</th></tr></thead><tbody>
          ${c.checks.map((x) => { const d = x.failures_b - x.failures_a; return `<tr><td><code>${esc(x.check_type)}</code></td><td class="num">${x.failures_a}</td><td class="num">${x.failures_b}</td><td class="num ${d > 0 ? "down" : d < 0 ? "up" : ""}">${d > 0 ? "+" : ""}${d}</td></tr>`; }).join("")}</tbody></table></div>
      </div>
    </div>`;
  document.getElementById("cmp").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    location.hash = `#/compare?a=${encodeURIComponent(f.get("a"))}&b=${encodeURIComponent(f.get("b"))}`;
  });
  const short = (r) => r.label.replace(/^DEMO - /, "");
  chart("c-crit", {
    type: "bar",
    data: { labels: c.criteria.map((x) => pretty(x.criterion)), datasets: [
      { label: "A: " + short(c.run_a), data: c.criteria.map((x) => x.avg_a), backgroundColor: COLORS.slate, borderRadius: 4 },
      { label: "B: " + short(c.run_b), data: c.criteria.map((x) => x.avg_b), backgroundColor: COLORS.blue, borderRadius: 4 }] },
    options: { scales: { y: { min: 1, max: 5 } }, plugins: { legend: { position: "bottom" } } },
  });
  chart("c-cat", {
    type: "bar",
    data: { labels: c.categories.map((x) => x.category), datasets: [
      { label: "A", data: c.categories.map((x) => x.pass_rate_a), backgroundColor: COLORS.slate, borderRadius: 4 },
      { label: "B", data: c.categories.map((x) => x.pass_rate_b), backgroundColor: COLORS.blue, borderRadius: 4 }] },
    options: { scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } }, plugins: { legend: { position: "bottom" } } },
  });
}

async function gtmPage(runId) {
  setNav("gtm");
  const runs = await api("/api/runs");
  setBanner(runs);
  if (!runs.length) {
    app.innerHTML = `<div class="panel empty"><h1>No runs yet</h1></div>`;
    return;
  }
  const id = runId || runs[runs.length - 1].id;
  const run = runs.find((r) => r.id === id);
  const g = await api(`/api/runs/${encodeURIComponent(id)}/gtm`);
  const total = g.intents.reduce((s, x) => s + x.conversations, 0);
  const signals = g.intents.reduce((s, x) => s + x.buying_signals, 0);
  const upsell = g.intents.reduce((s, x) => s + x.upsell_opportunities, 0);
  const churn = g.intents.reduce((s, x) => s + x.high_churn_risk, 0);
  app.innerHTML = `
    <div class="page-head"><div><h1>GTM insights</h1><p>Structured lead and intent data extracted from every conversation of <strong>${esc(run ? run.label : id)}</strong>.</p></div>
      <label>Run <select id="gtm-run">${runs.map((r) => `<option value="${esc(r.id)}" ${r.id === id ? "selected" : ""}>${esc(r.label)}</option>`).join("")}</select></label></div>
    ${total ? `
    <div class="kpis">
      ${kpi("Conversations analysed", total, "one lead record each")}
      ${kpi("Buying signals", signals, "purchase intent medium or high")}
      ${kpi("Upsell opportunities", upsell, "installation, warranty, cross-sell")}
      ${kpi("High churn risk", churn, "frustrated or refused customers")}
    </div>
    <div class="grid g2">
      <div class="panel"><h2>Contact reasons ${sqlButton("gtm_intents")}</h2><div class="chart-box"><canvas id="c-int"></canvas></div></div>
      <div class="panel"><h2>Signals by intent ${sqlButton("gtm_intents")}</h2><table><thead><tr><th>Intent</th><th class="num">Conv.</th><th class="num">Buying</th><th class="num">Contacts</th><th class="num">Upsell</th><th class="num">Churn risk</th></tr></thead><tbody>
        ${g.intents.map((x) => `<tr><td>${esc(pretty(x.primary_intent))}</td><td class="num">${x.conversations}</td><td class="num">${x.buying_signals}</td><td class="num">${x.contacts_captured}</td><td class="num">${x.upsell_opportunities}</td><td class="num">${x.high_churn_risk}</td></tr>`).join("")}</tbody></table></div>
    </div>
    <div class="panel"><h2>Leads and accounts to act on ${sqlButton("gtm_leads")}</h2><div class="table-wrap"><table><thead><tr><th>Conversation</th><th>Intent</th><th>Product interest</th><th>Purchase intent</th><th>Upsell</th><th>Churn risk</th><th>CRM note</th></tr></thead><tbody>
      ${g.leads.map((l) => `<tr class="click" data-href="#/result/${l.result_id}"><td><code>${esc(l.scenario_id)}</code></td><td>${esc(pretty(l.primary_intent))}</td><td>${esc(l.product_interest || "–")}</td>
        <td><span class="badge ${l.purchase_intent === "high" ? "pass" : l.purchase_intent === "medium" ? "info" : "neutral"}">${esc(l.purchase_intent)}</span></td><td>${esc(l.upsell_opportunity || "–")}</td>
        <td><span class="badge ${l.churn_risk === "high" ? "fail" : l.churn_risk === "medium" ? "warn" : "neutral"}">${esc(l.churn_risk)}</span></td><td class="muted">${esc(l.summary)}</td></tr>`).join("")}</tbody></table></div></div>`
    : `<div class="panel empty">This run has no lead data (lead extraction was off).</div>`}`;
  document.getElementById("gtm-run").addEventListener("change", (e) => { location.hash = `#/gtm/${encodeURIComponent(e.target.value)}`; });
  if (total) {
    chart("c-int", {
      type: "doughnut",
      data: { labels: g.intents.map((x) => pretty(x.primary_intent)), datasets: [{ data: g.intents.map((x) => x.conversations), backgroundColor: ["#2563eb", "#60a5fa", "#0f172a", "#16a34a", "#d97706", "#dc2626", "#94a3b8", "#7c3aed", "#0891b2"] }] },
      options: { plugins: { legend: { position: "right" } } },
    });
  }
}

// ---------- router ----------

async function route() {
  charts.forEach((c) => c.destroy());
  charts = [];
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
  } catch (err) {
    app.innerHTML = `<div class="panel empty"><h1>Something went wrong</h1><p>${esc(err.message)}</p><p><a href="#/">Back to overview</a></p></div>`;
  }
}

document.addEventListener("click", async (e) => {
  const sql = e.target.closest("[data-sql]");
  if (sql) {
    e.stopPropagation();
    sqlCache = sqlCache || (await api("/api/sql"));
    const names = sql.dataset.sql.split(",");
    document.getElementById("sql-title").textContent = "SQL: " + names.join(", ");
    document.getElementById("sql-body").textContent = names.map((n) => `-- ${n}\n${sqlCache[n]}`).join("\n\n");
    document.getElementById("sql-modal").hidden = false;
    return;
  }
  const row = e.target.closest("tr[data-href]");
  if (row && !e.target.closest("a")) location.hash = row.dataset.href;
});
document.getElementById("sql-close").addEventListener("click", () => { document.getElementById("sql-modal").hidden = true; });
document.getElementById("sql-modal").addEventListener("click", (e) => { if (e.target.id === "sql-modal") e.target.hidden = true; });
window.addEventListener("hashchange", route);
route();
