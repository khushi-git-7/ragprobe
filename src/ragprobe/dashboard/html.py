"""The dashboard page.

One self-contained HTML file: tokens, layout, charts, data and the interaction
layer are all inlined, so it opens from disk, from a CI artifact viewer or from an
email attachment with no network. The design is a product-analytics layout - a
left navigation rail, a row of KPI tiles, charts in cards, a filterable table -
because that is the shape a team already knows how to read.

Everything visible is computed by :mod:`ragprobe.dashboard.analytics` and
:mod:`ragprobe.dashboard.insights`; this module only lays it out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence

from ragprobe import __version__
from ragprobe.dashboard.analytics import (
    ATTRIBUTION_ERROR,
    ATTRIBUTION_RETRIEVAL,
    RETRIEVAL_FAMILIES,
    CaseRow,
    DashboardModel,
    Kpi,
)
from ragprobe.dashboard.insights import Insight, generate_insights
from ragprobe.dashboard.svg import (
    fmt_delta,
    fmt_value,
    hbar_chart,
    histogram,
    line_chart,
    sparkline,
    stacked_hbar,
)
from ragprobe.regression.diff import (
    STATUS_DEGRADED,
    STATUS_FLAT,
    STATUS_IMPROVED,
    STATUS_NEW,
    STATUS_REGRESSED,
    STATUS_REMOVED,
)
from ragprobe.reporting.fragments import checks_table, chunk_list, esc, fmt_pct, fmt_score

SECTIONS = (
    ("overview", "Overview"),
    ("trends", "Trends"),
    ("breakdown", "Breakdown"),
    ("cases", "Cases"),
    ("regression", "Regression"),
    ("insights", "Insights"),
)

# --------------------------------------------------------------------- styles

_CSS = """
:root {
  --bg: #f5f6f8; --surface: #ffffff; --surface-2: #f2f3f5; --surface-3: #e9ebef;
  --border: #e3e6ea; --border-strong: #cfd4da;
  --text: #111418; --text-2: #4b5563; --text-3: #6b7280;
  --accent: #2a5bd7; --accent-bg: #e8eefb; --accent-ink: #ffffff;
  --series: #2a78d6; --series-soft: rgba(42, 120, 214, 0.12);
  --pass: #0a7a3c; --pass-bg: #e3f5ea;
  --fail: #c62828; --fail-bg: #fdecec;
  --warn: #8a5a00; --warn-bg: #fff4d6;
  --flat: #6b7280; --flat-bg: #eef0f3;
  --grid: #eceef1; --axis: #d0d5db; --track: #eef0f3;
  --shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06);
  --radius: 10px; --radius-sm: 6px;
  --font: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0d1117; --surface: #161b22; --surface-2: #1f262e; --surface-3: #262e38;
    --border: #2a323c; --border-strong: #3a4552;
    --text: #e6edf3; --text-2: #b0bac6; --text-3: #8b96a3;
    --accent: #79a6f6; --accent-bg: #1b2a44; --accent-ink: #0d1117;
    --series: #5b9cf0; --series-soft: rgba(91, 156, 240, 0.16);
    --pass: #4ade80; --pass-bg: #10301f;
    --fail: #ff7b72; --fail-bg: #3b1a1a;
    --warn: #f2c14e; --warn-bg: #3a2d10;
    --flat: #9aa4b1; --flat-bg: #242b33;
    --grid: #232a33; --axis: #3a4552; --track: #232a33;
    --shadow: none;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #0d1117; --surface: #161b22; --surface-2: #1f262e; --surface-3: #262e38;
  --border: #2a323c; --border-strong: #3a4552;
  --text: #e6edf3; --text-2: #b0bac6; --text-3: #8b96a3;
  --accent: #79a6f6; --accent-bg: #1b2a44; --accent-ink: #0d1117;
  --series: #5b9cf0; --series-soft: rgba(91, 156, 240, 0.16);
  --pass: #4ade80; --pass-bg: #10301f;
  --fail: #ff7b72; --fail-bg: #3b1a1a;
  --warn: #f2c14e; --warn-bg: #3a2d10;
  --flat: #9aa4b1; --flat-bg: #242b33;
  --grid: #232a33; --axis: #3a4552; --track: #232a33;
  --shadow: none;
  color-scheme: dark;
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--text); font-family: var(--font);
  font-size: 14px; line-height: 1.5; -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
code, .mono { font-family: var(--mono); font-size: 0.86em; }
button { font: inherit; color: inherit; }
h1, h2, h3 { margin: 0; font-weight: 600; letter-spacing: -0.01em; }
h1 { font-size: 20px; }
h2 { font-size: 15px; }
h3 { font-size: 13px; color: var(--text-2); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
p { margin: 0; }
.muted { color: var(--text-3); }
.small { font-size: 12px; }
.hidden { display: none !important; }

/* ---- shell ---- */
.app { display: grid; grid-template-columns: 224px minmax(0, 1fr); min-height: 100vh; }
.sidebar {
  position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column;
  background: var(--surface); border-right: 1px solid var(--border); padding: 16px 12px;
}
.brand { display: flex; align-items: center; gap: 8px; padding: 4px 8px 16px; font-weight: 600; font-size: 15px; }
.brand .mark { width: 22px; height: 22px; border-radius: 6px; background: var(--accent); display: inline-grid; place-items: center; }
.brand .mark svg { width: 14px; height: 14px; }
.brand span.sub { color: var(--text-3); font-weight: 500; }
.nav { display: flex; flex-direction: column; gap: 2px; }
.nav a {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 7px 10px; border-radius: var(--radius-sm); color: var(--text-2); font-weight: 500;
}
.nav a:hover { background: var(--surface-2); color: var(--text); }
.nav a.active { background: var(--accent-bg); color: var(--accent); }
.nav .count { font-size: 11px; color: var(--text-3); background: var(--surface-2); padding: 1px 7px; border-radius: 99px; font-variant-numeric: tabular-nums; }
.nav a.active .count { background: var(--surface); }
.sidebar-foot { margin-top: auto; padding: 12px 8px 0; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-3); display: grid; gap: 8px; }
.sidebar-foot .kv { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; }
.sidebar-foot .kv b { font-weight: 500; color: var(--text-2); }
.theme-btn {
  display: inline-flex; align-items: center; gap: 8px; width: 100%; padding: 7px 10px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); border-radius: var(--radius-sm); color: var(--text-2);
}
.theme-btn:hover { background: var(--surface-2); }
.main { padding: 24px 32px 64px; min-width: 0; }
.topbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 20px; }
.topbar .title { display: flex; flex-direction: column; gap: 2px; }
.topbar .title .muted { font-size: 13px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 99px; font-size: 12px;
  background: var(--surface); border: 1px solid var(--border); color: var(--text-2);
}
.chip code { font-size: 11px; }
.panel { display: none; }
.panel.active { display: block; }
.section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin: 24px 0 12px; }
.section-head:first-child { margin-top: 0; }

/* ---- cards & grids ---- */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); }
.card .card-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 14px 16px 0; }
.card .card-head .value { font-size: 20px; font-weight: 600; }
.card .card-body { padding: 12px 16px 16px; }
.grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.grid-kpi { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.kpi { padding: 14px 16px 12px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.kpi .label { font-size: 12px; color: var(--text-3); font-weight: 500; }
.kpi .value { font-size: 26px; font-weight: 600; line-height: 1.1; }
.kpi .delta { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 500; white-space: nowrap; }
.kpi .delta .arrow { font-size: 10px; }
.kpi .delta.good { color: var(--pass); }
.kpi .delta.bad { color: var(--fail); }
.kpi .delta.neutral { color: var(--text-3); }
.kpi .delta .vs { color: var(--text-3); font-weight: 400; }
.kpi .spark { margin-top: 4px; width: 100%; height: 32px; }
.kpi .note { font-size: 11px; color: var(--text-3); }

/* ---- banners & pills ---- */
.banner { border-radius: var(--radius); padding: 10px 14px; margin-bottom: 12px; font-size: 13px; border: 1px solid; }
.banner.warn { background: var(--warn-bg); border-color: var(--warn); color: var(--warn); }
.banner.fail { background: var(--fail-bg); border-color: var(--fail); color: var(--fail); }
.banner.pass { background: var(--pass-bg); border-color: var(--pass); color: var(--pass); }
.banner ul { margin: 6px 0 0; padding-left: 18px; }
.pill { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; padding: 2px 8px; border-radius: 99px; white-space: nowrap; }
.pill::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.pill.pass, .pill.improved, .pill.good { background: var(--pass-bg); color: var(--pass); }
.pill.fail, .pill.regressed, .pill.bad { background: var(--fail-bg); color: var(--fail); }
.pill.degraded, .pill.removed, .pill.warn { background: var(--warn-bg); color: var(--warn); }
.pill.flat, .pill.skip, .pill.info { background: var(--flat-bg); color: var(--flat); }
.pill.new { background: var(--accent-bg); color: var(--accent); }
.pill.plain::before { display: none; }
.tag { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 4px; background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); }

/* ---- tables ---- */
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
th { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-3); background: var(--surface-2); white-space: nowrap; }
th:first-child { border-top-left-radius: var(--radius); }
th:last-child { border-top-right-radius: var(--radius); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody:last-child tr:last-child td { border-bottom: none; }
.table-card { overflow: hidden; }
.table-scroll { overflow-x: auto; }
th[data-sort] { cursor: pointer; user-select: none; }
th[data-sort]:hover { color: var(--text); }
th[data-sort] .dir { opacity: 0.35; margin-left: 4px; font-size: 10px; }
th[data-sort][aria-sort="ascending"] .dir, th[data-sort][aria-sort="descending"] .dir { opacity: 1; color: var(--accent); }
.delta-cell.good { color: var(--pass); } .delta-cell.bad { color: var(--fail); } .delta-cell.neutral { color: var(--text-3); }

/* ---- toolbar ---- */
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }
.toolbar input[type="search"], .toolbar select {
  font: inherit; font-size: 13px; padding: 6px 10px; border-radius: var(--radius-sm); border: 1px solid var(--border);
  background: var(--surface); color: var(--text); min-width: 200px;
}
.toolbar select { min-width: 150px; }
.toolbar input[type="search"]:focus, .toolbar select:focus, .fbtn:focus-visible, .theme-btn:focus-visible, .nav a:focus-visible, .rule-btn:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 1px;
}
.fgroup { display: inline-flex; gap: 4px; padding: 3px; border: 1px solid var(--border); border-radius: 99px; background: var(--surface); }
.fbtn { font-size: 12px; cursor: pointer; padding: 4px 11px; border-radius: 99px; border: 0; background: transparent; color: var(--text-2); display: inline-flex; gap: 6px; align-items: center; }
.fbtn:hover { background: var(--surface-2); }
.fbtn[aria-pressed="true"] { background: var(--accent); color: var(--accent-ink); }
.fbtn .n { font-size: 11px; opacity: 0.75; font-variant-numeric: tabular-nums; }
.toolbar .spacer { flex: 1; }
.result-count { font-size: 12px; color: var(--text-3); }

/* ---- case rows ---- */
tbody.case-group tr.case-row { cursor: pointer; }
tbody.case-group tr.case-row:hover td { background: var(--surface-2); }
tbody.case-group tr.case-row td .caret { display: inline-block; width: 14px; color: var(--text-3); font-size: 10px; transition: transform 0.15s; }
tbody.case-group.open tr.case-row td .caret { transform: rotate(90deg); }
tbody.case-group tr.case-detail { display: none; }
tbody.case-group.open tr.case-detail { display: table-row; }
tbody.case-group tr.case-detail > td { background: var(--surface-2); padding: 16px 20px 20px; }
.case-id { font-family: var(--mono); font-size: 12px; }
.case-q { display: block; color: var(--text-3); font-size: 12px; margin-top: 2px; max-width: 420px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fails { display: flex; flex-wrap: wrap; gap: 4px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.detail-grid .full { grid-column: 1 / -1; }
.kv-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-3); font-weight: 600; margin: 0 0 6px; }
.answer { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 12px; font-size: 13px; white-space: pre-wrap; }
.answer.expected { border-style: dashed; }
.chunk { border: 1px solid var(--border); background: var(--surface); border-radius: var(--radius-sm); padding: 8px 12px; margin-bottom: 6px; }
.chunk.expected { border-color: var(--pass); background: var(--pass-bg); }
.chunk .chead { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 12px; }
.chunk .cid { font-family: var(--mono); font-weight: 600; font-size: 12px; }
.chunk .ctext { font-size: 12px; color: var(--text-2); margin-top: 4px; max-height: 5.5em; overflow: hidden; }
.attrib { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: var(--radius-sm); background: var(--surface); border: 1px solid var(--border); font-size: 13px; }
.attrib .k { font-weight: 600; text-transform: capitalize; white-space: nowrap; }
.metric-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.metric-chips .chip b { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--text); }
.history-row { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.history-row .spark { width: 240px; height: 48px; }
.history-list { display: flex; flex-wrap: wrap; gap: 4px; }
.history-list .tag { font-variant-numeric: tabular-nums; }
.history-list .tag.fail { color: var(--fail); border-color: var(--fail); }

/* ---- charts ---- */
.chart-wrap { position: relative; }
svg.chart { width: 100%; height: auto; display: block; overflow: visible; }
svg.spark { display: block; }
.spark-line { fill: none; stroke: var(--series); stroke-width: 1.6; stroke-linejoin: round; stroke-linecap: round; }
.spark-dot { fill: var(--series); stroke: var(--surface); stroke-width: 1.5; }
.spark-dot.good { fill: var(--pass); } .spark-dot.bad { fill: var(--fail); }
.c-grid { stroke: var(--grid); stroke-width: 1; }
.c-axis { fill: var(--text-3); font-size: 11px; font-family: var(--font); }
.c-label { fill: var(--text-2); font-size: 12px; font-family: var(--font); }
.c-note { fill: var(--text-3); font-size: 10px; }
.c-value { fill: var(--text-2); font-size: 11px; font-family: var(--font); font-variant-numeric: tabular-nums; }
.c-end { fill: var(--text); font-size: 12px; font-weight: 600; font-family: var(--font); }
.c-line { fill: none; stroke: var(--series); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.c-area { fill: var(--series-soft); }
.c-dot { fill: var(--series); stroke: var(--surface); stroke-width: 2; }
.c-fill { fill: var(--series); }
.c-fill.pass { fill: var(--pass); } .c-fill.fail { fill: var(--fail); } .c-fill.skip { fill: var(--axis); } .c-fill.warn { fill: var(--warn); }
.c-track { fill: var(--track); }
.c-hit { fill: transparent; }
.c-cross { stroke: var(--axis); stroke-width: 1; pointer-events: none; }
.c-focus { fill: var(--surface); stroke: var(--series); stroke-width: 2.5; pointer-events: none; }
.c-annot { stroke: var(--warn); stroke-width: 1; stroke-dasharray: 3 3; }
.c-annot.dataset { stroke: var(--accent); }
.c-annot-mark { fill: var(--warn); }
.c-annot-mark.dataset { fill: var(--accent); }
.c-seg rect:hover, .c-col:hover .c-fill, .c-bar-row:hover .c-fill { filter: brightness(1.12); }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--text-3); margin-top: 8px; }
.legend .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.legend .sw.line { height: 2px; width: 14px; vertical-align: 3px; }
.tooltip {
  position: fixed; z-index: 50; pointer-events: none; display: none; max-width: 320px;
  background: var(--text); color: var(--bg); padding: 8px 10px; border-radius: var(--radius-sm);
  font-size: 12px; line-height: 1.4; white-space: pre-line; box-shadow: 0 4px 16px rgba(0,0,0,0.18);
}
.tooltip b { font-size: 13px; }

/* ---- insights ---- */
.insight { display: grid; grid-template-columns: 4px minmax(0, 1fr); gap: 14px; overflow: hidden; }
.insight .stripe { background: var(--flat); }
.insight.bad .stripe { background: var(--fail); } .insight.warn .stripe { background: var(--warn); }
.insight.good .stripe { background: var(--pass); } .insight.info .stripe { background: var(--accent); }
.insight .body { padding: 14px 16px 14px 0; display: grid; gap: 8px; }
.insight .head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.insight .head h2 { font-size: 14px; }
.insight .text { color: var(--text-2); font-size: 13px; }
.insight .foot { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.rule-btn { font-size: 12px; cursor: pointer; border: 1px solid var(--border); background: var(--surface); border-radius: 99px; padding: 2px 9px; color: var(--text-3); }
.rule-btn:hover { color: var(--text); background: var(--surface-2); }
.rule { display: none; font-size: 12px; color: var(--text-2); background: var(--surface-2); border-radius: var(--radius-sm); padding: 8px 10px; border-left: 2px solid var(--border-strong); }
.rule.open { display: block; }
.case-link { font-family: var(--mono); font-size: 11px; cursor: pointer; border: 1px solid var(--border); background: var(--surface); border-radius: 4px; padding: 1px 6px; color: var(--accent); }
.case-link:hover { background: var(--accent-bg); }
.empty { padding: 32px; text-align: center; color: var(--text-3); }
.empty code { display: inline-block; margin-top: 8px; background: var(--surface-2); padding: 4px 8px; border-radius: 4px; }

/* ---- regression ---- */
details.diffcase { border-top: 1px solid var(--border); }
details.diffcase:first-of-type { border-top: 0; }
details.diffcase > summary { list-style: none; cursor: pointer; padding: 10px 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
details.diffcase > summary::-webkit-details-marker { display: none; }
details.diffcase > summary:hover { background: var(--surface-2); }
details.diffcase .qtext { flex: 1 1 240px; min-width: 0; color: var(--text-2); font-size: 13px; }
details.diffcase .dbody { padding: 4px 16px 16px; }
.diffcols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px; }
.footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--border); color: var(--text-3); font-size: 12px; }

@media (max-width: 1100px) {
  .grid-3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .app { grid-template-columns: 1fr; }
  .sidebar { position: static; height: auto; flex-direction: row; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 12px; border-right: 0; border-bottom: 1px solid var(--border); }
  .brand { padding: 0 8px 0 0; }
  .nav { flex-direction: row; flex-wrap: wrap; }
  .nav a { padding: 5px 9px; }
  .sidebar-foot { margin-top: 0; margin-left: auto; padding: 0; border-top: 0; }
  .sidebar-foot .kv { display: none; }
  .theme-btn { width: auto; }
  .main { padding: 16px 16px 48px; }
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
  .detail-grid { grid-template-columns: 1fr; }
  .diffcols { grid-template-columns: 1fr; }
  .case-q { max-width: 220px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

# ------------------------------------------------------------------ scripts

_THEME_BOOT = """
(function () {
  try {
    var saved = localStorage.getItem('ragprobe-theme');
    if (saved === 'light' || saved === 'dark') document.documentElement.setAttribute('data-theme', saved);
  } catch (e) {}
})();
"""

_JS = """
(function () {
  'use strict';
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* ---------- navigation ---------- */
  var titles = {};
  $$('.nav a[data-section]').forEach(function (a) { titles[a.getAttribute('data-section')] = a.getAttribute('data-title') || a.textContent; });
  function show(section) {
    if (!Object.prototype.hasOwnProperty.call(titles, section)) section = 'overview';
    $$('.panel').forEach(function (p) { p.classList.toggle('active', p.id === section); });
    $$('.nav a[data-section]').forEach(function (a) { a.classList.toggle('active', a.getAttribute('data-section') === section); });
    var h = $('#section-title'); if (h) h.textContent = titles[section] || section;
    if (history.replaceState) history.replaceState(null, '', '#' + section);
    window.scrollTo(0, 0);
  }
  $$('.nav a[data-section]').forEach(function (a) {
    a.addEventListener('click', function (e) { e.preventDefault(); show(a.getAttribute('data-section')); });
  });
  window.addEventListener('hashchange', function () { show((location.hash || '#overview').slice(1)); });
  show((location.hash || '#overview').slice(1));

  /* ---------- theme ---------- */
  var themeBtn = $('#theme-toggle');
  function themeLabel() {
    var t = document.documentElement.getAttribute('data-theme') || 'auto';
    themeBtn.querySelector('span').textContent = 'Theme: ' + t;
  }
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme') || 'auto';
      var next = cur === 'auto' ? 'light' : cur === 'light' ? 'dark' : 'auto';
      if (next === 'auto') document.documentElement.removeAttribute('data-theme');
      else document.documentElement.setAttribute('data-theme', next);
      try { if (next === 'auto') localStorage.removeItem('ragprobe-theme'); else localStorage.setItem('ragprobe-theme', next); } catch (e) {}
      themeLabel();
    });
    themeLabel();
  }

  /* ---------- tooltip ---------- */
  var tip = $('#tooltip');
  function showTip(text, x, y) {
    tip.textContent = '';
    var lines = String(text).split('\\n');
    lines.forEach(function (line, i) {
      if (i === 0) { var b = document.createElement('b'); b.textContent = line; tip.appendChild(b); }
      else { tip.appendChild(document.createElement('br')); tip.appendChild(document.createTextNode(line)); }
    });
    tip.style.display = 'block';
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = x + 14, top = y + 14;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top + h > window.innerHeight - 8) top = y - h - 14;
    tip.style.left = Math.max(4, left) + 'px'; tip.style.top = Math.max(4, top) + 'px';
  }
  function hideTip() { tip.style.display = 'none'; }
  document.addEventListener('pointermove', function (e) {
    var el = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (el && !el.closest('svg.chart.line')) { showTip(el.getAttribute('data-tip'), e.clientX, e.clientY); }
    else if (!e.target.closest || !e.target.closest('svg.chart.line')) { hideTip(); }
  });
  document.addEventListener('pointerleave', hideTip);

  /* ---------- line charts: crosshair + nearest-x tooltip ---------- */
  function fmt(v, f) {
    if (v === null || v === undefined) return 'n/a';
    if (f === 'percent') return (v * 100).toFixed(1) + '%';
    if (f === 'count') return String(Math.round(v));
    return Number(v).toFixed(3);
  }
  $$('svg.chart.line').forEach(function (svg) {
    var data; try { data = JSON.parse(svg.getAttribute('data-chart')); } catch (e) { return; }
    var cross = svg.querySelector('.c-cross'), focus = svg.querySelector('.c-focus');
    var vb = svg.viewBox.baseVal;
    function nearest(clientX) {
      var rect = svg.getBoundingClientRect();
      var x = (clientX - rect.left) * (vb.width / rect.width);
      var best = 0, bestD = Infinity;
      data.xs.forEach(function (px, i) { var d = Math.abs(px - x); if (d < bestD) { bestD = d; best = i; } });
      return best;
    }
    svg.addEventListener('pointermove', function (e) {
      var i = nearest(e.clientX);
      cross.setAttribute('x1', data.xs[i]); cross.setAttribute('x2', data.xs[i]); cross.style.display = '';
      if (data.ys[i] !== null) { focus.setAttribute('cx', data.xs[i]); focus.setAttribute('cy', data.ys[i]); focus.style.display = ''; }
      else focus.style.display = 'none';
      var text = fmt(data.values[i], data.fmt) + ' ' + data.series + '\\n' + data.labels[i];
      if (data.notes[i]) text += '\\n' + data.notes[i];
      showTip(text, e.clientX, e.clientY);
    });
    svg.addEventListener('pointerleave', function () { cross.style.display = 'none'; focus.style.display = 'none'; hideTip(); });
  });

  /* ---------- cases table ---------- */
  var table = $('#cases-table');
  if (table) {
    var search = $('#case-search'), catSel = $('#case-category'), statusGroup = $('#case-status');
    var groups = $$('tbody.case-group', table);
    var countEl = $('#case-count');
    var state = { q: '', status: 'all', category: 'all' };
    function apply() {
      var visible = 0;
      groups.forEach(function (g) {
        var ok = true;
        if (state.q) ok = (g.getAttribute('data-search') || '').indexOf(state.q) !== -1;
        if (ok && state.status !== 'all') ok = (g.getAttribute('data-status') || '').split(' ').indexOf(state.status) !== -1;
        if (ok && state.category !== 'all') ok = g.getAttribute('data-category') === state.category;
        g.classList.toggle('hidden', !ok);
        if (ok) visible += 1;
      });
      if (countEl) countEl.textContent = visible + ' of ' + groups.length + ' cases';
    }
    if (search) search.addEventListener('input', function () { state.q = search.value.trim().toLowerCase(); apply(); });
    if (catSel) catSel.addEventListener('change', function () { state.category = catSel.value; apply(); });
    if (statusGroup) statusGroup.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-filter]'); if (!b) return;
      state.status = b.getAttribute('data-filter');
      $$('button[data-filter]', statusGroup).forEach(function (o) { o.setAttribute('aria-pressed', String(o === b)); });
      apply();
    });
    groups.forEach(function (g) {
      var row = g.querySelector('tr.case-row');
      row.addEventListener('click', function (e) { if (e.target.closest('a, button')) return; g.classList.toggle('open'); });
      row.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); g.classList.toggle('open'); } });
    });
    $$('th[data-sort]', table).forEach(function (th) {
      th.addEventListener('click', function () {
        var key = th.getAttribute('data-sort'), type = th.getAttribute('data-type') || 'str';
        var dir = th.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
        $$('th[data-sort]', table).forEach(function (o) { o.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', dir);
        var sorted = groups.slice().sort(function (a, b) {
          var av = a.getAttribute('data-' + key) || '', bv = b.getAttribute('data-' + key) || '';
          var c;
          if (type === 'num') { c = (parseFloat(av) || 0) - (parseFloat(bv) || 0); }
          else { c = av < bv ? -1 : av > bv ? 1 : 0; }
          return dir === 'ascending' ? c : -c;
        });
        sorted.forEach(function (g) { table.appendChild(g); });
      });
    });
    window.ragprobeShowCase = function (id) {
      show('cases');
      if (search) { search.value = id; state.q = id.toLowerCase(); }
      state.status = 'all'; state.category = 'all';
      if (catSel) catSel.value = 'all';
      $$('button[data-filter]', statusGroup).forEach(function (o) { o.setAttribute('aria-pressed', String(o.getAttribute('data-filter') === 'all')); });
      apply();
      groups.forEach(function (g) { if (g.getAttribute('data-id') === id) g.classList.add('open'); });
    };
    apply();
  }
  $$('.case-link').forEach(function (b) {
    b.addEventListener('click', function () { if (window.ragprobeShowCase) window.ragprobeShowCase(b.getAttribute('data-case')); });
  });

  /* ---------- insights: rule disclosure ---------- */
  $$('.rule-btn').forEach(function (b) {
    b.addEventListener('click', function () {
      var rule = b.parentElement.parentElement.querySelector('.rule');
      var open = !rule.classList.contains('open');
      rule.classList.toggle('open', open); b.setAttribute('aria-expanded', String(open));
      b.textContent = open ? 'Hide rule' : 'How was this computed?';
    });
  });

  /* ---------- regression filters ---------- */
  var diffGroup = $('#diff-filters');
  if (diffGroup) diffGroup.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-filter]'); if (!b) return;
    var f = b.getAttribute('data-filter');
    $$('button[data-filter]', diffGroup).forEach(function (o) { o.setAttribute('aria-pressed', String(o === b)); });
    $$('details.diffcase').forEach(function (d) { d.classList.toggle('hidden', !(f === 'all' || d.getAttribute('data-status') === f)); });
  });
})();
"""


# ------------------------------------------------------------------ helpers


def _short_time(started_at: str) -> str:
    """``2026-09-18T17:30:23Z`` -> ``09-18 17:30``; anything else passes through."""
    if len(started_at) >= 16 and started_at[4] == "-" and started_at[10] == "T":
        return f"{started_at[5:10]} {started_at[11:16]}"
    return started_at


def _run_label(model: DashboardModel, index: int) -> str:
    point = model.points[index]
    return f"Run {point.label} - {point.started_at}" + (f" - config {point.config_fingerprint}" if point.config_fingerprint else "")


def _tick_labels(model: DashboardModel) -> List[str]:
    """``#3 18:06`` when every run is on the same day, else ``#3 09-18 18:06``."""
    dates = {p.started_at[:10] for p in model.points}
    labels = []
    for p in model.points:
        short = _short_time(p.started_at)
        if len(dates) == 1 and len(short) == 11 and short[5] == " ":
            short = short[6:]
        labels.append(f"{p.label} {short}".strip())
    return labels


def _annotations(model: DashboardModel) -> List[Dict[str, Any]]:
    annotations: List[Dict[str, Any]] = []
    for point in model.points:
        if point.config_changed:
            annotations.append({
                "index": point.index, "kind": "config",
                "text": "Config changed: " + "; ".join(point.changes[:3]) + (" ..." if len(point.changes) > 3 else ""),
            })
        if point.dataset_changed:
            annotations.append({"index": point.index, "kind": "dataset", "text": f"Dataset changed (fingerprint {point.dataset_fingerprint})"})
    return annotations


# ------------------------------------------------------------------ overview


def _kpi_tile(kpi: Kpi, model: DashboardModel) -> str:
    arrow = {"up": "&#9650;", "down": "&#9660;", "flat": "&#9644;", "none": ""}[kpi.direction]
    if kpi.delta is None:
        delta_html = '<span class="delta neutral"><span class="vs">no previous run</span></span>'
    else:
        delta_html = (
            f'<span class="delta {kpi.sentiment}"><span class="arrow">{arrow}</span>'
            f"{esc(fmt_delta(kpi.delta, kpi.fmt))} <span class=\"vs\">vs prev</span></span>"
        )
    note = f'<span class="note">{esc(kpi.note)}</span>' if kpi.note else ""
    return (
        f'<div class="card kpi" data-kpi="{esc(kpi.key)}">'
        f'<span class="label">{esc(kpi.label)}</span>'
        f'<span class="value">{esc(fmt_value(kpi.value, kpi.fmt))}</span>'
        f"{delta_html}{note}"
        f'{sparkline(kpi.series, width=140, height=32, sentiment=kpi.sentiment, label=f"{kpi.label} over {len(kpi.series)} runs")}'
        "</div>"
    )


def _run_log(model: DashboardModel) -> str:
    rows = []
    for point in reversed(model.points):
        changes = "; ".join(point.changes[:2]) + (" ..." if len(point.changes) > 2 else "")
        if point.dataset_changed:
            changes = ("dataset changed; " + changes) if changes else "dataset changed"
        nondeterministic = "" if point.deterministic else ' <span class="pill warn plain">nondeterministic</span>'
        rows.append(
            "<tr>"
            f'<td class="mono">{esc(point.label)}</td>'
            f'<td class="mono">{esc(point.started_at)}</td>'
            f'<td class="mono">{esc(point.config_fingerprint)}</td>'
            f"<td>{esc(point.provider)}{nondeterministic}</td>"
            f'<td class="num">{esc(fmt_pct(point.pass_rate))}</td>'
            f'<td class="num">{esc(fmt_score(point.mean_score))}</td>'
            f'<td class="num">{point.passed}/{point.total}</td>'
            f'<td class="small muted">{esc(changes) or "-"}</td>'
            "</tr>"
        )
    return (
        '<div class="card table-card"><div class="table-scroll"><table>'
        "<thead><tr><th>Run</th><th>Started (UTC)</th><th>Config</th><th>Provider</th>"
        '<th class="num">Pass rate</th><th class="num">Mean score</th><th class="num">Passed</th><th>Changed vs previous</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div></div>"
    )


def _overview(model: DashboardModel, insights: Sequence[Insight]) -> str:
    banners = []
    if model.gate is not None and not model.gate.ok:
        items = "".join(f"<li>{esc(r)}</li>" for r in model.gate.reasons)
        banners.append(f'<div class="banner fail"><strong>Regression gate failed</strong><ul>{items}</ul></div>')
    for warning in model.warnings:
        banners.append(f'<div class="banner warn">{esc(warning)}</div>')
    tiles = "".join(_kpi_tile(kpi, model) for kpi in model.kpis)
    top = [i for i in insights if i.severity in ("bad", "warn")][:3] or list(insights)[:3]
    findings = "".join(
        f'<li><span class="pill {esc(i.severity)}">{esc(i.severity)}</span> <strong>{esc(i.title)}</strong>'
        f'<div class="small muted">{esc(i.body)}</div></li>'
        for i in top
    )
    return (
        "".join(banners)
        + '<div class="section-head"><h2>Latest run</h2>'
        f'<span class="small muted">deltas compare with the previous stored run</span></div>'
        f'<div class="grid-kpi">{tiles}</div>'
        '<div class="section-head"><h2>Top findings</h2><a href="#insights" class="small nav-jump" data-section="insights">All insights</a></div>'
        f'<div class="card"><div class="card-body"><ul style="margin:0;padding-left:0;list-style:none;display:grid;gap:10px">{findings or "<li class=muted>No findings.</li>"}</ul></div></div>'
        f'<div class="section-head"><h2>Run log</h2><span class="small muted">{len(model.points)} run(s) in history, newest first</span></div>'
        + _run_log(model)
    )


# ------------------------------------------------------------------ trends


def _trends(model: DashboardModel) -> str:
    labels = _tick_labels(model)
    annotations = _annotations(model)
    tooltip_labels = [_run_label(model, i) for i in range(len(model.points))]
    cards = []
    metrics = [("pass_rate", "Pass rate", "percent"), ("mean_score", "Mean score", "score")]
    for family, _prefix, label in RETRIEVAL_FAMILIES:
        key = model.retrieval_key(family)
        metrics.append((family, label if "@" not in key else f"{label}@{key.split('@', 1)[1]}", "score"))
    for key, label, fmt in metrics:
        series = model.trend(key)
        latest = series[-1] if series else None
        chart = line_chart(
            series, tooltip_labels, fmt=fmt, series=label, annotations=annotations,
            chart_id=f"trend-{key}", tick_labels=labels,
        )
        cards.append(
            f'<div class="card"><div class="card-head"><h2>{esc(label)}</h2>'
            f'<span class="value">{esc(fmt_value(latest, fmt))}</span></div>'
            f'<div class="card-body chart-wrap">{chart}</div></div>'
        )
    legend = (
        '<div class="legend"><span><span class="sw line" style="background:var(--series)"></span>metric per run</span>'
        '<span><span class="sw" style="background:var(--warn)"></span>config fingerprint changed</span>'
        '<span><span class="sw" style="background:var(--accent)"></span>dataset fingerprint changed</span>'
        "<span>hover for the run timestamp and what changed</span></div>"
    )
    return (
        '<div class="section-head"><h2>Metrics over run history</h2>'
        f'<span class="small muted">{len(model.points)} run(s), oldest to newest; y-axis is zoomed to the data</span></div>'
        + legend + f'<div class="grid-2" style="margin-top:12px">{"".join(cards)}</div>'
    )


# ------------------------------------------------------------------ breakdown


def _breakdown(model: DashboardModel) -> str:
    cat_rows = [
        {
            "label": c.name, "value": c.pass_rate,
            "tip": f"{c.name}\n{c.passed}/{c.total} passing ({fmt_pct(c.pass_rate)})\nmean score {c.mean_score:.3f}"
            + (f"\nprevious run: {fmt_pct(c.previous_pass_rate)}" if c.previous_pass_rate is not None else ""),
            "cls": "" if c.pass_rate >= 1.0 else ("fail" if c.pass_rate < 0.5 else "warn"),
        }
        for c in model.categories
    ]
    check_rows = [
        {
            "label": c.name, "note": "(advisory)" if c.advisory else "",
            "segments": [
                {"label": "fail", "count": c.failed, "cls": "fail"},
                {"label": "pass", "count": c.passed, "cls": "pass"},
                {"label": "skipped (not applicable)", "count": c.skipped, "cls": "skip"},
            ],
        }
        for c in model.checks
    ]
    hist = [
        {"label": f"{b.low:.1f}", "count": b.count, "tip": f"score {b.low:.1f} to {b.high:.1f}\n{b.count} case(s)" + ("\n" + ", ".join(b.cases[:6]) + (" ..." if len(b.cases) > 6 else "") if b.cases else "")}
        for b in model.histogram
    ]
    checks_legend = (
        '<div class="legend"><span><span class="sw" style="background:var(--fail)"></span>fail</span>'
        '<span><span class="sw" style="background:var(--pass)"></span>pass</span>'
        '<span><span class="sw" style="background:var(--axis)"></span>skipped</span>'
        "<span>sorted by failures; advisory checks never gate</span></div>"
    )
    return (
        '<div class="section-head"><h2>Where the latest run fails</h2>'
        '<span class="small muted">categories sorted worst first</span></div>'
        '<div class="grid-2">'
        '<div class="card"><div class="card-head"><h2>Pass rate by category</h2></div>'
        f'<div class="card-body chart-wrap">{hbar_chart(cat_rows, fmt="percent")}'
        '<div class="legend"><span>bar colour: blue at 100%, amber below, red under 50%</span></div></div></div>'
        '<div class="card"><div class="card-head"><h2>Check outcomes</h2></div>'
        f'<div class="card-body chart-wrap">{stacked_hbar(check_rows)}{checks_legend}</div></div>'
        '<div class="card"><div class="card-head"><h2>Score distribution</h2>'
        f'<span class="small muted">{len(model.rows)} cases, bins of 0.1</span></div>'
        f'<div class="card-body chart-wrap">{histogram(hist)}</div></div>'
        '<div class="card"><div class="card-head"><h2>Category detail</h2></div>'
        '<div class="table-scroll"><table><thead><tr><th>Category</th><th class="num">Passed</th>'
        '<th class="num">Pass rate</th><th class="num">Prev</th><th class="num">Mean score</th></tr></thead><tbody>'
        + "".join(
            f"<tr><td>{esc(c.name)}</td><td class='num'>{c.passed}/{c.total}</td>"
            f"<td class='num'>{esc(fmt_pct(c.pass_rate))}</td><td class='num muted'>{esc(fmt_pct(c.previous_pass_rate))}</td>"
            f"<td class='num'>{c.mean_score:.3f}</td></tr>"
            for c in model.categories
        )
        + "</tbody></table></div></div></div>"
    )


# ------------------------------------------------------------------ cases


def _case_detail(row: CaseRow, model: DashboardModel) -> str:
    case = row.case
    golden = case.get("golden") or {}
    expected_answer = golden.get("expected_answer")
    keywords = []
    if golden.get("required_keywords"):
        keywords.append("required: " + ", ".join(f"<code>{esc(k)}</code>" for k in golden["required_keywords"]))
    if golden.get("forbidden_keywords"):
        keywords.append("forbidden: " + ", ".join(f"<code>{esc(k)}</code>" for k in golden["forbidden_keywords"]))
    if golden.get("should_refuse"):
        keywords.append("must refuse")
    if not golden:
        expected_html = '<p class="muted small">Golden-set assertions were not recorded in this results file (older schema).</p>'
    else:
        expected_html = (
            f'<div class="answer expected">{esc(expected_answer) if expected_answer else "<em class=muted>No reference answer in the golden set; the case asserts on keywords, refusal and grounding.</em>"}</div>'
            + (f'<p class="small muted" style="margin-top:6px">{" &middot; ".join(keywords)}</p>' if keywords else "")
            + (f'<p class="small muted" style="margin-top:6px"><strong>Notes:</strong> {esc(golden["notes"])}</p>' if golden.get("notes") else "")
        )
    attrib_html = ""
    if row.attribution is not None:
        attrib_html = (
            f'<div class="full"><div class="kv-label">Attribution</div><div class="attrib">'
            f'<span class="pill {"fail" if row.attribution.kind in (ATTRIBUTION_RETRIEVAL, ATTRIBUTION_ERROR) else "warn"} plain">{esc(row.attribution.kind)}</span>'
            f"<span>{esc(row.attribution.reason)}.</span></div></div>"
        )
    error_html = f'<div class="full banner fail">This case raised an exception: <code>{esc(case["error"])}</code></div>' if case.get("error") else ""
    metrics = "".join(
        f'<span class="chip">{esc(name)} <b>{fmt_score(value)}</b></span>'
        for name, value in sorted((case.get("retrieval") or {}).items())
    )
    hist = row.history
    hist_tags = "".join(
        f'<span class="tag {"" if snap.passed else "fail"}" title="{esc(_run_label(model, i))}">{esc(model.points[i].label)} {snap.score:.2f}</span>'
        if snap else f'<span class="tag muted" title="{esc(_run_label(model, i))}">{esc(model.points[i].label)} absent</span>'
        for i, snap in enumerate(hist.snapshots)
    )
    flake_note = (
        f"{hist.flips_same_config} flip(s) under an unchanged config (flaky)" if hist.flips_same_config
        else (f"{hist.flips_config_change} flip(s), all across config changes" if hist.flips_config_change else "no pass/fail flips")
    )
    return (
        '<div class="detail-grid">'
        f"{error_html}"
        f'<div class="full"><div class="kv-label">Question</div><p>{esc(case.get("question"))}</p></div>'
        f'<div><div class="kv-label">Expected</div>{expected_html}</div>'
        f'<div><div class="kv-label">Actual answer</div><div class="answer">{esc(case.get("answer")) or "<em class=muted>(empty)</em>"}</div></div>'
        f"{attrib_html}"
        f'<div class="full"><div class="kv-label">Checks</div>{checks_table(case.get("checks") or [])}</div>'
        f'<div class="full"><div class="kv-label">Retrieval metrics</div><div class="metric-chips">{metrics or "<span class=muted>none</span>"}</div></div>'
        f'<div class="full"><div class="kv-label">Retrieved chunks</div>{chunk_list(case.get("retrieved") or [], case.get("expected_chunks") or [])}</div>'
        f'<div class="full"><div class="kv-label">Score across history</div><div class="history-row">'
        f'{sparkline(hist.scores, width=240, height=48, label=f"{row.id} score over {len(hist.scores)} runs")}'
        f'<div><div class="small muted">{esc(flake_note)}</div><div class="history-list" style="margin-top:6px">{hist_tags}</div></div>'
        "</div></div></div>"
    )


def _case_group(row: CaseRow, model: DashboardModel) -> str:
    case = row.case
    status = "pass" if row.passed else "fail"
    tokens = [status]
    if row.change_status:
        tokens.append(row.change_status)
    failing = case.get("failed_checks") or []
    fails_html = "".join(f'<span class="tag">{esc(n)}</span>' for n in failing) or '<span class="muted">-</span>'
    hit = next((v for k, v in (case.get("retrieval") or {}).items() if str(k).startswith("hit_rate@")), None)
    delta = row.score_delta_prev
    delta_cls = "neutral" if delta is None or abs(delta) < model.epsilon else ("good" if delta > 0 else "bad")
    delta_text = "-" if delta is None else ("0.000" if abs(delta) < 0.0005 else fmt_delta(delta, "score"))
    search_blob = " ".join(
        str(x) for x in (case.get("id"), case.get("question"), case.get("category"), case.get("answer"), " ".join(failing))
    ).lower()
    change_pill = f' <span class="pill {esc(row.change_status)}">{esc(row.change_status)}</span>' if row.change_status and row.change_status != STATUS_FLAT else ""
    return (
        f'<tbody class="case-group" data-id="{esc(row.id)}" data-status="{" ".join(tokens)}" '
        f'data-category="{esc(case.get("category", "general"))}" data-score="{esc(case.get("score"))}" '
        f'data-delta="{esc(delta if delta is not None else "")}" data-fails="{len(failing)}" '
        f'data-hit="{esc(hit if hit is not None else "")}" data-flips="{row.history.flips}" '
        f'data-search="{esc(search_blob)}">'
        f'<tr class="case-row" tabindex="0" aria-label="{esc(row.id)}">'
        f'<td><span class="caret">&#9654;</span><span class="pill {status}">{status}</span>{change_pill}</td>'
        f'<td><span class="case-id">{esc(row.id)}</span><span class="case-q">{esc(case.get("question"))}</span></td>'
        f'<td><span class="tag">{esc(case.get("category", "general"))}</span></td>'
        f'<td class="num">{fmt_score(case.get("score"), 3)}</td>'
        f'<td class="num delta-cell {delta_cls}">{esc(delta_text)}</td>'
        f'<td><div class="fails">{fails_html}</div></td>'
        f'<td class="num">{fmt_score(hit, 1) if hit is not None else "n/a"}</td>'
        f'<td>{sparkline(row.history.scores, width=100, height=26, label=f"{row.id} score history")}</td>'
        "</tr>"
        f'<tr class="case-detail"><td colspan="8">{_case_detail(row, model)}</td></tr>'
        "</tbody>"
    )


def _cases(model: DashboardModel) -> str:
    categories: List[str] = []
    for row in model.rows:
        c = str(row.case.get("category", "general"))
        if c not in categories:
            categories.append(c)
    counts = {
        "all": len(model.rows),
        "pass": sum(1 for r in model.rows if r.passed),
        "fail": sum(1 for r in model.rows if not r.passed),
        STATUS_REGRESSED: sum(1 for r in model.rows if r.change_status == STATUS_REGRESSED),
        STATUS_IMPROVED: sum(1 for r in model.rows if r.change_status == STATUS_IMPROVED),
    }
    compare = f" vs {model.comparison_label}" if model.comparison_label else ""
    chips = []
    for key, label in (("all", "All"), ("pass", "Pass"), ("fail", "Fail"), (STATUS_REGRESSED, "Regressed"), (STATUS_IMPROVED, "Improved")):
        pressed = "true" if key == "all" else "false"
        title = f' title="{esc(label + compare)}"' if key in (STATUS_REGRESSED, STATUS_IMPROVED) else ""
        chips.append(
            f'<button class="fbtn" data-filter="{key}" aria-pressed="{pressed}"{title}>'
            f'{label}<span class="n">{counts[key]}</span></button>'
        )
    options = '<option value="all">All categories</option>' + "".join(f'<option value="{esc(c)}">{esc(c)}</option>' for c in categories)
    head = (
        "<thead><tr>"
        '<th data-sort="status" data-type="str">Status<span class="dir">&#9662;</span></th>'
        '<th data-sort="id" data-type="str">Case<span class="dir">&#9662;</span></th>'
        '<th data-sort="category" data-type="str">Category<span class="dir">&#9662;</span></th>'
        '<th class="num" data-sort="score" data-type="num">Score<span class="dir">&#9662;</span></th>'
        '<th class="num" data-sort="delta" data-type="num" title="score change versus the previous stored run">&Delta; prev<span class="dir">&#9662;</span></th>'
        '<th data-sort="fails" data-type="num">Failing checks<span class="dir">&#9662;</span></th>'
        '<th class="num" data-sort="hit" data-type="num" title="hit rate@k for this case">Hit<span class="dir">&#9662;</span></th>'
        '<th data-sort="flips" data-type="num" title="score per run; sort by pass/fail flips">History<span class="dir">&#9662;</span></th>'
        "</tr></thead>"
    )
    return (
        '<div class="section-head"><h2>Cases in the latest run</h2>'
        f'<span class="small muted">regressed / improved chips compare with the {esc(model.comparison_label or "previous run")}</span></div>'
        '<div class="toolbar">'
        '<input type="search" id="case-search" placeholder="Search id, question, answer, check" aria-label="Search cases">'
        f'<div class="fgroup" id="case-status" role="group" aria-label="Status filter">{"".join(chips)}</div>'
        f'<select id="case-category" aria-label="Category filter">{options}</select>'
        '<span class="spacer"></span><span class="result-count" id="case-count"></span></div>'
        f'<div class="card table-card"><div class="table-scroll"><table id="cases-table">{head}'
        + "".join(_case_group(row, model) for row in model.rows)
        + "</table></div></div>"
    )


# ------------------------------------------------------------------ regression


def _regression(model: DashboardModel) -> str:
    diff = model.diff
    if diff is None:
        return (
            '<div class="card"><div class="empty"><p><strong>No baseline to compare against.</strong></p>'
            "<p>Record one and re-render the dashboard; this panel then shows what regressed, degraded and improved.</p>"
            "<code>ragprobe baseline</code> <code>ragprobe dashboard</code></div></div>"
        )
    counts = diff.counts()
    parts: List[str] = []
    if model.gate is not None:
        if model.gate.ok:
            parts.append('<div class="banner pass">Gate passed: no blocking regressions against the baseline.</div>')
        else:
            items = "".join(f"<li>{esc(r)}</li>" for r in model.gate.reasons)
            parts.append(f'<div class="banner fail"><strong>Gate failed</strong><ul>{items}</ul></div>')
    for warning in diff.warnings:
        parts.append(f'<div class="banner warn">{esc(warning)}</div>')
    tile_kind = {STATUS_REGRESSED: "bad", STATUS_DEGRADED: "warn", STATUS_IMPROVED: "good", STATUS_FLAT: "neutral", STATUS_NEW: "neutral", STATUS_REMOVED: "warn"}
    tiles = "".join(
        f'<div class="card kpi"><span class="label">{esc(status.capitalize())}</span>'
        f'<span class="value" style="color:var(--{ {"bad": "fail", "warn": "warn", "good": "pass", "neutral": "text"}[tile_kind[status]] if counts[status] else "text-3"})">{counts[status]}</span></div>'
        for status in (STATUS_REGRESSED, STATUS_DEGRADED, STATUS_IMPROVED, STATUS_FLAT, STATUS_NEW, STATUS_REMOVED)
    )
    parts.append(f'<div class="grid-kpi">{tiles}</div>')
    base, curr = diff.baseline_summary, diff.current_summary
    summary_rows = []
    for label, key, formatter in (("Pass rate", "pass_rate", fmt_pct), ("Mean score", "mean_score", fmt_score), ("Passed", "passed", lambda v: "n/a" if v is None else str(int(v))), ("Failed", "failed", lambda v: "n/a" if v is None else str(int(v)))):
        before, after = base.get(key), curr.get(key)
        try:
            delta_text = f"{float(after) - float(before):+.3f}"
        except (TypeError, ValueError):
            delta_text = "n/a"
        summary_rows.append(f"<tr><td>{label}</td><td class='num'>{esc(formatter(before))}</td><td class='num'>{esc(formatter(after))}</td><td class='num'>{delta_text}</td></tr>")
    meta = diff.baseline_meta
    parts.append(
        '<div class="grid-2" style="margin-top:16px"><div class="card table-card"><table><thead><tr><th>Measure</th><th class="num">Baseline</th><th class="num">Current</th><th class="num">Delta</th></tr></thead>'
        f"<tbody>{''.join(summary_rows)}</tbody></table></div>"
        '<div class="card"><div class="card-head"><h2>Comparison</h2></div><div class="card-body small">'
        f'<div class="sidebar-foot" style="border:0;padding:0"><div class="kv"><b>Baseline</b><span class="mono">{esc(meta.get("started_at"))} config {esc(meta.get("config_fingerprint"))}</span>'
        f'<b>Current</b><span class="mono">{esc(diff.current_meta.get("started_at"))} config {esc(diff.current_meta.get("config_fingerprint"))}</span>'
        f'<b>Epsilon</b><span>{model.epsilon} (score moves smaller than this are flat)</span></div></div></div></div></div>'
    )
    chips = '<button class="fbtn" data-filter="all" aria-pressed="true">All</button>' + "".join(
        f'<button class="fbtn" data-filter="{s}" aria-pressed="false">{s.capitalize()}<span class="n">{counts[s]}</span></button>'
        for s in (STATUS_REGRESSED, STATUS_DEGRADED, STATUS_IMPROVED, STATUS_NEW, STATUS_REMOVED, STATUS_FLAT)
    )
    parts.append(f'<div class="section-head"><h2>Changed cases</h2><span class="small muted">before and after, side by side</span></div><div class="toolbar"><div class="fgroup" id="diff-filters">{chips}</div></div>')
    items = []
    for case in diff.cases:
        d = case.to_dict()
        status = str(d.get("status"))
        delta = d.get("score_delta")
        transitions = ""
        if d.get("newly_failing"):
            transitions += '<p class="small muted">Now failing: ' + ", ".join(f"<code>{esc(n)}</code>" for n in d["newly_failing"]) + "</p>"
        if d.get("newly_passing"):
            transitions += '<p class="small muted">Now passing: ' + ", ".join(f"<code>{esc(n)}</code>" for n in d["newly_passing"]) + "</p>"
        items.append(
            f'<details class="diffcase" data-status="{esc(status)}"{" open" if status == STATUS_REGRESSED else ""}>'
            f'<summary><span class="pill {esc(status)}">{esc(status)}</span><span class="case-id">{esc(d.get("id"))}</span>'
            f'<span class="qtext">{esc(d.get("question"))}</span><span class="mono">{"" if delta is None else f"{delta:+.3f}"}</span></summary>'
            f'<div class="dbody"><p class="small muted">{esc(d.get("reason"))}</p>{transitions}<div class="diffcols">'
            f'<div><div class="kv-label">Baseline answer</div><div class="answer">{esc(d.get("baseline_answer")) or "<em class=muted>(none)</em>"}</div></div>'
            f'<div><div class="kv-label">Current answer</div><div class="answer">{esc(d.get("current_answer")) or "<em class=muted>(none)</em>"}</div></div>'
            "</div></div></details>"
        )
    parts.append(f'<div class="card">{"".join(items)}</div>')
    return "".join(parts)


# ------------------------------------------------------------------ insights


def _insights(insights: Sequence[Insight]) -> str:
    cards = []
    for insight in insights:
        cases = "".join(f'<button class="case-link" data-case="{esc(c)}" type="button">{esc(c)}</button>' for c in insight.cases[:8])
        more = f'<span class="small muted">+{len(insight.cases) - 8} more</span>' if len(insight.cases) > 8 else ""
        cards.append(
            f'<div class="card insight {esc(insight.severity)}" data-kind="{esc(insight.kind)}"><div class="stripe"></div><div class="body">'
            f'<div class="head"><span class="pill {esc(insight.severity)}">{esc(insight.severity)}</span><h2>{esc(insight.title)}</h2></div>'
            f'<p class="text">{esc(insight.body)}</p>'
            f'<div class="foot"><button class="rule-btn" type="button" aria-expanded="false" title="{esc(insight.rule)}">How was this computed?</button>{cases}{more}</div>'
            f'<div class="rule">{esc(insight.rule)}</div>'
            "</div></div>"
        )
    return (
        '<div class="section-head"><h2>Auto-generated findings</h2>'
        '<span class="small muted">each finding shows the rule that produced it; treat them as triage hints</span></div>'
        f'<div style="display:grid;gap:12px">{"".join(cards)}</div>'
    )


# ------------------------------------------------------------------ page


def render_dashboard(model: DashboardModel, title: str = "RAGProbe Dashboard") -> str:
    """Render the complete, self-contained dashboard page for ``model``."""
    insights = generate_insights(model)
    latest = model.latest
    latest_point = model.latest_point
    pipeline = latest.get("pipeline") or {}
    nav_counts = {
        "cases": str(len(model.rows)),
        "regression": str(model.diff.counts()[STATUS_REGRESSED]) if model.diff else "",
        "insights": str(sum(1 for i in insights if i.severity in ("bad", "warn"))),
        "trends": str(len(model.points)),
    }
    nav = "".join(
        f'<a href="#{key}" data-section="{key}" data-title="{label}">{label}'
        + (f'<span class="count">{nav_counts[key]}</span>' if nav_counts.get(key) else "")
        + "</a>"
        for key, label in SECTIONS
    )
    panels = {
        "overview": _overview(model, insights),
        "trends": _trends(model),
        "breakdown": _breakdown(model),
        "cases": _cases(model),
        "regression": _regression(model),
        "insights": _insights(insights),
    }
    sections = "".join(
        f'<section id="{key}" class="panel{" active" if key == "overview" else ""}" aria-label="{label}">{panels[key]}</section>'
        for key, label in SECTIONS
    )
    chips = (
        f'<span class="chip">Latest <code>{esc(latest_point.started_at)}</code></span>'
        f'<span class="chip">Provider <code>{esc(latest_point.provider)}</code></span>'
        f'<span class="chip">Config <code>{esc(latest_point.config_fingerprint)}</code></span>'
        f'<span class="chip">Dataset <code>{esc(latest_point.dataset_fingerprint)}</code></span>'
        f'<span class="chip">Corpus <code>{esc(pipeline.get("documents"))} docs / {esc(pipeline.get("chunks"))} chunks</code></span>'
    )
    logo = (
        '<span class="mark"><svg viewBox="0 0 14 14" aria-hidden="true"><path d="M2 10 L5.5 6 L8 8.5 L12 3" fill="none" '
        'stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="Evaluation history, trends, breakdowns and regression analysis for a RAG pipeline.">
<script>{_THEME_BOOT}</script>
<style>{_CSS}</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
  <div class="brand">{logo}RAGProbe <span class="sub">Dashboard</span></div>
  <nav class="nav" aria-label="Sections">{nav}</nav>
  <div class="sidebar-foot">
    <button class="theme-btn" id="theme-toggle" type="button" aria-label="Cycle colour theme"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M7 1.5 A5.5 5.5 0 0 1 7 12.5 z" fill="currentColor"/></svg><span>Theme: auto</span></button>
    <div class="kv"><b>Runs</b><span>{len(model.points)}</span><b>Latest</b><span class="mono">{esc(_short_time(latest_point.started_at))}</span><b>Version</b><span class="mono">{esc(latest.get('ragprobe_version') or __version__)}</span></div>
  </div>
</aside>
<main class="main">
  <header class="topbar">
    <div class="title"><h1 id="section-title">Overview</h1><span class="muted">{esc(title)} &middot; {len(model.points)} stored run(s)</span></div>
    <div class="chips">{chips}</div>
  </header>
  {sections}
  <footer class="footer">Generated by RAGProbe {esc(__version__)}. Self-contained: no external scripts, styles or fonts are loaded; charts are inline SVG.</footer>
</main>
</div>
<div class="tooltip" id="tooltip" role="tooltip"></div>
<script>{_JS}</script>
</body>
</html>
"""


def write_dashboard(path: Path, model: DashboardModel, title: str = "RAGProbe Dashboard") -> Path:
    """Render ``model`` to ``path`` (creating parent directories) and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dashboard(model, title=title), encoding="utf-8")
    return path
