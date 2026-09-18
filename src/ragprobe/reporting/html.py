"""Self-contained HTML report.

One file, no external assets, no CDN. That matters more than it sounds: CI artifact
viewers, air-gapped environments and email attachments all break the moment a report
depends on a network fetch. Everything - CSS, the small amount of JS, the data - is
inlined, so the file can be downloaded from a build artifact and opened offline.

Written with plain string building rather than a template engine to keep the base
install dependency-free.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ragprobe.regression.diff import (
    STATUS_DEGRADED,
    STATUS_FLAT,
    STATUS_IMPROVED,
    STATUS_NEW,
    STATUS_REGRESSED,
    STATUS_REMOVED,
    DiffReport,
)

_CSS = """
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-2: #f0f2f5;
  --border: #d9dde3;
  --text: #16191d;
  --text-dim: #5c6570;
  --accent: #2f5bd7;
  --pass: #1a7f4b;
  --pass-bg: #e6f4ec;
  --fail: #c0392b;
  --fail-bg: #fbeaea;
  --warn: #9a6700;
  --warn-bg: #fff6e0;
  --flat: #6b7280;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
}
:root:not([data-theme="light"]) { }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0f1216;
    --surface: #171b21;
    --surface-2: #1e242c;
    --border: #2b323b;
    --text: #e6e9ed;
    --text-dim: #9aa4b1;
    --accent: #7ea2ff;
    --pass: #4ade80;
    --pass-bg: #13301f;
    --fail: #f87171;
    --fail-bg: #331616;
    --warn: #fbbf24;
    --warn-bg: #332813;
    --flat: #9aa4b1;
  }
}
:root[data-theme="dark"] {
  --bg: #0f1216;
  --surface: #171b21;
  --surface-2: #1e242c;
  --border: #2b323b;
  --text: #e6e9ed;
  --text-dim: #9aa4b1;
  --accent: #7ea2ff;
  --pass: #4ade80;
  --pass-bg: #13301f;
  --fail: #f87171;
  --fail-bg: #331616;
  --warn: #fbbf24;
  --warn-bg: #332813;
  --flat: #9aa4b1;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
}
.wrap { max-width: 1080px; margin: 0 auto; padding: 32px 16px 80px; }
header.page { border-bottom: 1px solid var(--border); padding-bottom: 20px; margin-bottom: 24px; }
h1 { font-size: 1.6rem; margin: 0 0 6px; letter-spacing: -0.01em; }
h2 { font-size: 1.1rem; margin: 32px 0 12px; }
.sub { color: var(--text-dim); font-size: 0.87rem; margin: 0; }
.meta { display: flex; flex-wrap: wrap; gap: 8px 20px; margin-top: 12px; font-size: 0.82rem; color: var(--text-dim); }
.meta code { font-family: var(--mono); background: var(--surface-2); padding: 1px 6px; border-radius: 4px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.card .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-dim); }
.card .value { font-size: 1.5rem; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
.card.pass .value { color: var(--pass); }
.card.fail .value { color: var(--fail); }
table { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); font-size: 0.87rem; }
th { background: var(--surface-2); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); }
tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); }
.banner { border-radius: 10px; padding: 12px 16px; margin-bottom: 14px; font-size: 0.88rem; border: 1px solid; }
.banner.warn { background: var(--warn-bg); border-color: var(--warn); color: var(--warn); }
.banner.fail { background: var(--fail-bg); border-color: var(--fail); color: var(--fail); }
.banner.pass { background: var(--pass-bg); border-color: var(--pass); color: var(--pass); }
.banner ul { margin: 6px 0 0; padding-left: 20px; }
.pill { display: inline-block; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 8px; border-radius: 99px; }
.pill.pass { background: var(--pass-bg); color: var(--pass); }
.pill.fail { background: var(--fail-bg); color: var(--fail); }
.pill.skip { background: var(--surface-2); color: var(--text-dim); }
.pill.regressed { background: var(--fail-bg); color: var(--fail); }
.pill.degraded { background: var(--warn-bg); color: var(--warn); }
.pill.improved { background: var(--pass-bg); color: var(--pass); }
.pill.flat { background: var(--surface-2); color: var(--flat); }
.pill.new { background: var(--surface-2); color: var(--accent); }
.pill.removed { background: var(--warn-bg); color: var(--warn); }
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0; }
.filters button {
  font: inherit; font-size: 0.8rem; cursor: pointer; padding: 5px 12px; border-radius: 99px;
  border: 1px solid var(--border); background: var(--surface); color: var(--text-dim);
}
.filters button[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
details.case { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; }
details.case > summary {
  cursor: pointer; padding: 11px 14px; display: flex; align-items: center; gap: 10px;
  flex-wrap: wrap; list-style: none;
}
details.case > summary::-webkit-details-marker { display: none; }
details.case > summary::before { content: "\\25B8"; color: var(--text-dim); font-size: 0.8rem; }
details.case[open] > summary::before { content: "\\25BE"; }
details.case .qid { font-family: var(--mono); font-size: 0.8rem; color: var(--text-dim); }
details.case .qtext { flex: 1 1 260px; min-width: 0; }
details.case .score { font-family: var(--mono); font-size: 0.82rem; color: var(--text-dim); }
.body { padding: 4px 14px 16px; border-top: 1px solid var(--border); }
.kv { margin: 12px 0 4px; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); }
.answer { background: var(--surface-2); border-radius: 8px; padding: 10px 12px; font-size: 0.9rem; white-space: pre-wrap; }
.chunk { border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; margin-bottom: 6px; }
.chunk.expected { border-color: var(--pass); background: var(--pass-bg); }
.chunk .chead { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; font-size: 0.8rem; }
.chunk .cid { font-family: var(--mono); font-weight: 600; }
.chunk .ctext { font-size: 0.84rem; color: var(--text-dim); margin-top: 5px; max-height: 6.5em; overflow: hidden; }
.diffcols { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 720px) { .diffcols { grid-template-columns: 1fr; } }
.diffcol .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); margin-bottom: 4px; }
.muted { color: var(--text-dim); font-size: 0.83rem; }
footer.page { margin-top: 44px; padding-top: 16px; border-top: 1px solid var(--border); color: var(--text-dim); font-size: 0.8rem; }
.hidden { display: none !important; }
"""

_JS = """
(function () {
  function wire(groupId, listSelector) {
    var group = document.getElementById(groupId);
    if (!group) return;
    group.addEventListener('click', function (event) {
      var button = event.target.closest('button[data-filter]');
      if (!button) return;
      var filter = button.getAttribute('data-filter');
      group.querySelectorAll('button[data-filter]').forEach(function (other) {
        other.setAttribute('aria-pressed', String(other === button));
      });
      document.querySelectorAll(listSelector).forEach(function (row) {
        var match = filter === 'all' || (row.getAttribute('data-status') || '').split(' ').indexOf(filter) !== -1;
        row.classList.toggle('hidden', !match);
      });
    });
  }
  wire('case-filters', '[data-case-row]');
  wire('diff-filters', '[data-diff-row]');
})();
"""


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _fmt(value: Optional[float], digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _card(label: str, value: str, kind: str = "") -> str:
    return (
        f'<div class="card {kind}"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div></div>'
    )


def _check_pill(check: Mapping[str, Any]) -> str:
    if not check.get("applicable", True):
        return '<span class="pill skip">skip</span>'
    return (
        '<span class="pill pass">pass</span>'
        if check.get("passed")
        else '<span class="pill fail">fail</span>'
    )


def _render_checks(checks: Sequence[Mapping[str, Any]]) -> str:
    if not checks:
        return '<p class="muted">No checks were recorded (the case errored before evaluation).</p>'
    rows = []
    for check in checks:
        advisory = (check.get("metadata") or {}).get("advisory")
        name = _esc(check.get("name"))
        if advisory:
            name += ' <span class="muted">(advisory)</span>'
        rows.append(
            "<tr>"
            f"<td>{_check_pill(check)}</td>"
            f"<td>{name}</td>"
            f'<td class="num">{_fmt(check.get("score"), 2)}</td>'
            f"<td>{_esc(check.get('detail'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th></th><th>Check</th>"
        '<th class="num">Score</th><th>Detail</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_chunks(retrieved: Sequence[Mapping[str, Any]], expected: Sequence[str]) -> str:
    if not retrieved:
        return '<p class="muted">Nothing was retrieved for this question.</p>'
    expected_anchors = {str(chunk).split("~", 1)[0] for chunk in expected}
    blocks = []
    for chunk in retrieved:
        chunk_id = str(chunk.get("chunk_id", ""))
        is_expected = chunk_id.split("~", 1)[0] in expected_anchors
        label = (
            '<span class="pill pass">expected</span>'
            if is_expected
            else '<span class="pill skip">not in golden set</span>'
        )
        blocks.append(
            f'<div class="chunk {"expected" if is_expected else ""}">'
            f'<div class="chead"><span class="cid">{_esc(chunk_id)}</span>'
            f'<span class="muted">rank {_esc(chunk.get("rank"))} &middot; '
            f'score {_fmt(chunk.get("score"))}</span>{label}</div>'
            f'<div class="ctext">{_esc(chunk.get("text"))}</div></div>'
        )
    missing = sorted(
        anchor
        for anchor in expected_anchors
        if anchor not in {str(c.get("chunk_id", "")).split("~", 1)[0] for c in retrieved}
    )
    if missing:
        blocks.append(
            '<p class="muted">Expected but not retrieved: '
            + ", ".join(f"<code>{_esc(item)}</code>" for item in missing)
            + "</p>"
        )
    return "".join(blocks)


def _render_faithfulness(faithfulness: Mapping[str, Any]) -> str:
    heuristic = faithfulness.get("heuristic") or {}
    judge = faithfulness.get("judge")
    if not heuristic:
        return ""
    parts = [
        '<div class="kv">Faithfulness</div>',
        f'<p class="muted">Heuristic grounding score '
        f'<strong>{_fmt(heuristic.get("score"), 2)}</strong> over '
        f'{len(heuristic.get("claims") or [])} claim(s).',
    ]
    if judge:
        parts.append(
            f' LLM judge ({_esc(judge.get("provider"))}) scored '
            f'<strong>{_fmt(judge.get("score"), 2)}</strong>'
        )
        disagreement = faithfulness.get("disagreement")
        if disagreement is not None:
            parts.append(f", disagreement {_fmt(disagreement, 2)}")
        if not judge.get("deterministic", True):
            parts.append(' <span class="pill skip">nondeterministic</span>')
        parts.append(".")
    parts.append("</p>")

    unsupported = heuristic.get("unsupported_claims") or []
    if unsupported:
        parts.append('<p class="muted">Ungrounded claim(s):</p><ul class="muted">')
        for claim in unsupported:
            parts.append(f"<li>{_esc(claim)}</li>")
        parts.append("</ul>")
    return "".join(parts)


def _render_case(case: Mapping[str, Any]) -> str:
    passed = bool(case.get("passed"))
    status_tokens = ["pass" if passed else "fail", _esc(case.get("category", "general"))]
    pill = (
        '<span class="pill pass">pass</span>'
        if passed
        else '<span class="pill fail">fail</span>'
    )
    error_html = ""
    if case.get("error"):
        error_html = (
            f'<div class="banner fail">This case raised an exception: '
            f'<code>{_esc(case["error"])}</code></div>'
        )

    retrieval_rows = "".join(
        f'<tr><td>{_esc(name)}</td><td class="num">{_fmt(value)}</td></tr>'
        for name, value in sorted((case.get("retrieval") or {}).items())
    )

    return (
        f'<details class="case" data-case-row data-status="{" ".join(status_tokens)}">'
        f"<summary>{pill}"
        f'<span class="qid">{_esc(case.get("id"))}</span>'
        f'<span class="qtext">{_esc(case.get("question"))}</span>'
        f'<span class="score">{_fmt(case.get("score"), 2)}</span></summary>'
        f'<div class="body">{error_html}'
        f'<div class="kv">Answer</div><div class="answer">{_esc(case.get("answer")) or "<em>(empty)</em>"}</div>'
        f'<div class="kv">Checks</div>{_render_checks(case.get("checks") or [])}'
        f'<div class="kv">Retrieval metrics</div>'
        f'<table><thead><tr><th>Metric</th><th class="num">Value</th></tr></thead>'
        f"<tbody>{retrieval_rows}</tbody></table>"
        f'<div class="kv">Retrieved chunks</div>{_render_chunks(case.get("retrieved") or [], case.get("expected_chunks") or [])}'
        f'{_render_faithfulness(case.get("faithfulness") or {})}'
        "</div></details>"
    )


def _render_diff_case(case: Mapping[str, Any]) -> str:
    status = str(case.get("status", STATUS_FLAT))
    delta = case.get("score_delta")
    delta_text = "" if delta is None else f"{delta:+.3f}"
    transitions = []
    if case.get("newly_failing"):
        transitions.append(
            '<p class="muted">Now failing: '
            + ", ".join(f"<code>{_esc(n)}</code>" for n in case["newly_failing"])
            + "</p>"
        )
    if case.get("newly_passing"):
        transitions.append(
            '<p class="muted">Now passing: '
            + ", ".join(f"<code>{_esc(n)}</code>" for n in case["newly_passing"])
            + "</p>"
        )
    return (
        f'<details class="case" data-diff-row data-status="{_esc(status)}"'
        f'{" open" if status == STATUS_REGRESSED else ""}>'
        f'<summary><span class="pill {_esc(status)}">{_esc(status)}</span>'
        f'<span class="qid">{_esc(case.get("id"))}</span>'
        f'<span class="qtext">{_esc(case.get("question"))}</span>'
        f'<span class="score">{_esc(delta_text)}</span></summary>'
        f'<div class="body"><p class="muted">{_esc(case.get("reason"))}</p>'
        + "".join(transitions)
        + '<div class="diffcols">'
        f'<div class="diffcol"><div class="label">Baseline answer</div>'
        f'<div class="answer">{_esc(case.get("baseline_answer")) or "<em>(none)</em>"}</div></div>'
        f'<div class="diffcol"><div class="label">Current answer</div>'
        f'<div class="answer">{_esc(case.get("current_answer")) or "<em>(none)</em>"}</div></div>'
        "</div></div></details>"
    )


def _render_diff_section(diff: DiffReport, gate=None) -> str:
    counts = diff.counts()
    parts: List[str] = ['<h2 id="diff">Regression diff</h2>']

    if gate is not None:
        if gate.ok:
            parts.append('<div class="banner pass">Gate passed: no blocking regressions.</div>')
        else:
            items = "".join(f"<li>{_esc(reason)}</li>" for reason in gate.reasons)
            parts.append(f'<div class="banner fail"><strong>Gate failed</strong><ul>{items}</ul></div>')

    for warning in diff.warnings:
        parts.append(f'<div class="banner warn">{_esc(warning)}</div>')

    parts.append(
        '<div class="cards">'
        + _card("Regressed", str(counts[STATUS_REGRESSED]), "fail" if counts[STATUS_REGRESSED] else "")
        + _card("Degraded", str(counts[STATUS_DEGRADED]))
        + _card("Improved", str(counts[STATUS_IMPROVED]), "pass" if counts[STATUS_IMPROVED] else "")
        + _card("Flat", str(counts[STATUS_FLAT]))
        + _card("New", str(counts[STATUS_NEW]))
        + _card("Removed", str(counts[STATUS_REMOVED]))
        + "</div>"
    )

    base_summary = diff.baseline_summary
    curr_summary = diff.current_summary
    parts.append(
        "<table><thead><tr><th>Measure</th><th class='num'>Baseline</th>"
        "<th class='num'>Current</th><th class='num'>Delta</th></tr></thead><tbody>"
    )
    for label, key, formatter in (
        ("Pass rate", "pass_rate", _pct),
        ("Mean score", "mean_score", lambda v: _fmt(v, 3)),
        ("Passed", "passed", lambda v: "n/a" if v is None else str(int(v))),
        ("Failed", "failed", lambda v: "n/a" if v is None else str(int(v))),
    ):
        before = base_summary.get(key)
        after = curr_summary.get(key)
        if before is None and after is None:
            continue
        try:
            delta_value = f"{float(after) - float(before):+.3f}"
        except (TypeError, ValueError):
            delta_value = "n/a"
        parts.append(
            f"<tr><td>{_esc(label)}</td><td class='num'>{_esc(formatter(before))}</td>"
            f"<td class='num'>{_esc(formatter(after))}</td>"
            f"<td class='num'>{_esc(delta_value)}</td></tr>"
        )
    parts.append("</tbody></table>")

    parts.append(
        '<div class="filters" id="diff-filters">'
        '<button data-filter="all" aria-pressed="true">All</button>'
        f'<button data-filter="{STATUS_REGRESSED}" aria-pressed="false">Regressed</button>'
        f'<button data-filter="{STATUS_DEGRADED}" aria-pressed="false">Degraded</button>'
        f'<button data-filter="{STATUS_IMPROVED}" aria-pressed="false">Improved</button>'
        f'<button data-filter="{STATUS_FLAT}" aria-pressed="false">Flat</button>'
        f'<button data-filter="{STATUS_NEW}" aria-pressed="false">New</button>'
        f'<button data-filter="{STATUS_REMOVED}" aria-pressed="false">Removed</button>'
        "</div>"
    )
    parts.extend(_render_diff_case(case.to_dict()) for case in diff.cases)
    return "".join(parts)


def render_report(
    run: Mapping[str, Any],
    diff: Optional[DiffReport] = None,
    gate: Optional[Any] = None,
    title: str = "RAGProbe report",
) -> str:
    """Build the complete HTML document."""
    summary = run.get("summary") or {}
    pipeline = run.get("pipeline") or {}
    retrieval = summary.get("retrieval") or {}
    cases = run.get("cases") or []

    categories: List[str] = []
    for case in cases:
        category = str(case.get("category", "general"))
        if category not in categories:
            categories.append(category)

    determinism_note = (
        ""
        if run.get("deterministic")
        else '<div class="banner warn">This run used a nondeterministic provider. '
        "Re-running the same commit may produce different results, so treat small "
        "deltas as noise rather than signal.</div>"
    )

    cards = (
        '<div class="cards">'
        + _card("Cases", str(summary.get("total", 0)))
        + _card("Passed", str(summary.get("passed", 0)), "pass")
        + _card("Failed", str(summary.get("failed", 0)), "fail" if summary.get("failed") else "")
        + _card("Pass rate", _pct(summary.get("pass_rate")))
        + _card("Mean score", _fmt(summary.get("mean_score"), 3))
        + "</div>"
    )

    retrieval_rows = "".join(
        f'<tr><td>{_esc(name)}</td><td class="num">{_fmt(value)}</td></tr>'
        for name, value in sorted(retrieval.items())
    )
    retrieval_table = (
        "<table><thead><tr><th>Metric</th><th class='num'>Value</th></tr></thead>"
        f"<tbody>{retrieval_rows}</tbody></table>"
        if retrieval_rows
        else '<p class="muted">No retrieval metrics were defined for this run.</p>'
    )

    category_rows = "".join(
        f"<tr><td>{_esc(name)}</td>"
        f"<td class='num'>{stats.get('passed', 0)}/{stats.get('total', 0)}</td>"
        f"<td class='num'>{_pct(stats.get('pass_rate'))}</td>"
        f"<td class='num'>{_fmt(stats.get('mean_score'), 3)}</td></tr>"
        for name, stats in (summary.get("by_category") or {}).items()
    )

    filter_buttons = (
        '<div class="filters" id="case-filters">'
        '<button data-filter="all" aria-pressed="true">All</button>'
        '<button data-filter="fail" aria-pressed="false">Failing</button>'
        '<button data-filter="pass" aria-pressed="false">Passing</button>'
        + "".join(
            f'<button data-filter="{_esc(category)}" aria-pressed="false">{_esc(category)}</button>'
            for category in categories
        )
        + "</div>"
    )

    diff_section = _render_diff_section(diff, gate) if diff is not None else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<header class="page">
  <h1>{_esc(title)}</h1>
  <p class="sub">Evaluation and regression report for a RAG pipeline.</p>
  <div class="meta">
    <span>Run <code>{_esc(run.get('started_at'))}</code></span>
    <span>Provider <code>{_esc(run.get('provider'))}</code></span>
    <span>Config <code>{_esc(run.get('config_fingerprint'))}</code></span>
    <span>Dataset <code>{_esc(run.get('dataset_fingerprint'))}</code></span>
    <span>Corpus <code>{_esc(pipeline.get('documents'))} docs / {_esc(pipeline.get('chunks'))} chunks</code></span>
    <span>RAGProbe <code>{_esc(run.get('ragprobe_version'))}</code></span>
  </div>
</header>
{determinism_note}
<h2>Summary</h2>
{cards}
<h2>Retrieval metrics</h2>
{retrieval_table}
{'<h2>By category</h2><table><thead><tr><th>Category</th><th class="num">Passed</th><th class="num">Pass rate</th><th class="num">Mean score</th></tr></thead><tbody>' + category_rows + '</tbody></table>' if category_rows else ''}
<h2>Cases</h2>
{filter_buttons}
{''.join(_render_case(case) for case in cases)}
{diff_section}
<footer class="page">
  Generated by RAGProbe {_esc(run.get('ragprobe_version'))}. This file is self-contained:
  no external scripts, styles or fonts are loaded.
</footer>
</div>
<script>{_JS}</script>
</body>
</html>
"""


def write_report(
    path: Path,
    run: Mapping[str, Any],
    diff: Optional[DiffReport] = None,
    gate: Optional[Any] = None,
    title: str = "RAGProbe report",
) -> Path:
    """Render and write the report, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(run, diff=diff, gate=gate, title=title), encoding="utf-8")
    return path
