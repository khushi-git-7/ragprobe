#!/usr/bin/env python
"""Render the RAGProbe landing page (site/index.html) from the run history.

This is the front door of the GitHub Pages site: a short, opinionated page
that says what RAGProbe is, shows live numbers from the latest recorded run,
and links to the dashboard, the latest report and the repository.

It is deliberately outside the ``ragprobe`` package. The library stays a
testing tool; this script is presentation. It depends on the standard library
only, reads the history files directly (the same JSON ``ragprobe run`` writes)
and never makes a network request: the page it produces embeds its own CSS and
SVG and links only to sibling pages and the repository.

Usage::

    python scripts/build_site.py --history-dir reports/history --out site/index.html
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_URL = "https://github.com/khushi-git-7/ragprobe"
TITLE = "RAGProbe"
TAGLINE = "A regression gate for RAG pipelines."


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def esc(value: Any) -> str:
    """HTML-escape anything that came from a results file or the command line."""
    return html.escape("" if value is None else str(value), quote=True)


def is_run(document: Any) -> bool:
    """A results document has a summary and a list of cases; nothing else is trusted."""
    return (
        isinstance(document, dict)
        and isinstance(document.get("summary"), dict)
        and isinstance(document.get("cases"), list)
    )


def load_runs(history_dir: Path) -> List[Dict[str, Any]]:
    """Every usable run in the directory, oldest first by file name.

    File names written by the history store start with a sequence number, so a
    name sort is a time sort. Unreadable or foreign files are skipped with a
    note on stderr; a landing page must never fail because one shard is bad.
    """
    runs: List[Dict[str, Any]] = []
    if not history_dir.is_dir():
        return runs
    for path in sorted(history_dir.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print("skipping " + str(path) + ": " + str(exc), file=sys.stderr)
            continue
        if not is_run(document):
            print("skipping " + str(path) + ": not a results document", file=sys.stderr)
            continue
        runs.append(document)
    return runs


def fmt_pct(value: Optional[float]) -> str:
    return "-" if value is None else "{:.1f}%".format(float(value) * 100)


def fmt_num(value: Optional[float]) -> str:
    return "-" if value is None else "{:.3f}".format(float(value))


def stats(runs: List[Dict[str, Any]]) -> Dict[str, str]:
    """The numbers on the stats strip, all from the latest run; '-' when unknown."""
    if not runs:
        return {}
    latest = runs[-1]
    summary = latest.get("summary") or {}
    retrieval = summary.get("retrieval") or {}
    pipeline = latest.get("pipeline") or {}
    hit_rate = next((v for k, v in retrieval.items() if k.startswith("hit_rate@")), None)
    k_label = next((k.split("@", 1)[1] for k in retrieval if "@" in k), None)
    categories = summary.get("by_category") or {}
    return {
        "cases": str(summary.get("total", len(latest.get("cases") or []))),
        "pass_rate": fmt_pct(summary.get("pass_rate")),
        "runs": str(len(runs)),
        "hit_rate": fmt_pct(hit_rate),
        "mrr": fmt_num(retrieval.get("mrr")),
        "k": k_label or "k",
        "documents": str(pipeline.get("documents", "-")),
        "chunks": str(pipeline.get("chunks", "-")),
        "categories": str(len(categories)) if categories else "-",
        "provider": str(latest.get("provider") or "-"),
        "started_at": str(latest.get("started_at") or "-"),
    }


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------
CSS = """
:root{--bg:#f3f1e8;--surface:#fffdf7;--ink:#161616;--muted:#5a5a55;--line:#161616;
--orange:#e8541e;--yellow:#f4b400;--blue:#2b5be0;--shadow:6px 6px 0 var(--ink);--radius:10px;
--font:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}
:root:not([data-theme="light"]){color-scheme:light dark}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141416;--surface:#1e1e22;--ink:#f3f1e8;--muted:#b3b0a6;--line:#f3f1e8;--shadow:6px 6px 0 var(--ink)}}
:root[data-theme="dark"]{--bg:#141416;--surface:#1e1e22;--ink:#f3f1e8;--muted:#b3b0a6;--line:#f3f1e8;--shadow:6px 6px 0 var(--ink)}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);font-size:17px;line-height:1.55}
a{color:inherit}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
header.top{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px 0}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;letter-spacing:-.02em;font-size:20px;text-decoration:none}
.brand .mark{width:30px;height:30px;border:2px solid var(--line);border-radius:8px;background:var(--yellow);display:grid;place-items:center;font-size:14px;font-weight:900;color:#161616}
nav.links{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
nav.links a,.btn{display:inline-block;padding:9px 14px;border:2px solid var(--line);border-radius:var(--radius);background:var(--surface);text-decoration:none;font-weight:700;font-size:15px;box-shadow:3px 3px 0 var(--ink);transition:transform .08s,box-shadow .08s}
nav.links a:hover,.btn:hover{transform:translate(-1px,-1px);box-shadow:4px 4px 0 var(--ink)}
nav.links a:active,.btn:active{transform:translate(2px,2px);box-shadow:1px 1px 0 var(--ink)}
.btn.primary{background:var(--orange);color:#fff}
.btn.big{padding:14px 22px;font-size:17px;box-shadow:var(--shadow)}
.btn.big:hover{box-shadow:7px 7px 0 var(--ink)}
button.theme{font:inherit;cursor:pointer}
.pill{display:inline-block;padding:3px 10px;border:2px solid var(--line);border-radius:999px;background:var(--yellow);color:#161616;font-size:13px;font-weight:800;letter-spacing:.02em;text-transform:uppercase;transform:rotate(-2deg)}
.pill.blue{background:var(--blue);color:#fff}
.pill.orange{background:var(--orange);color:#fff}
.hero{display:grid;grid-template-columns:1.15fr .85fr;gap:36px;align-items:center;padding:36px 0 28px}
.hero h1{font-size:clamp(40px,6vw,66px);line-height:1.02;letter-spacing:-.035em;margin:14px 0 14px;font-weight:900}
.hero h1 .u{background:linear-gradient(transparent 62%,var(--yellow) 62%)}
.hero p.lead{font-size:20px;max-width:34em;margin:0 0 22px;color:var(--muted)}
.cta{display:flex;gap:14px;flex-wrap:wrap}
.art{border:2px solid var(--line);border-radius:14px;background:var(--surface);box-shadow:var(--shadow);padding:14px}
.art svg{display:block;width:100%;height:auto}
.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:26px 0 8px}
.stat{border:2px solid var(--line);border-radius:var(--radius);background:var(--surface);padding:14px 16px;box-shadow:4px 4px 0 var(--ink)}
.stat .v{font-size:32px;font-weight:900;letter-spacing:-.03em;line-height:1;font-family:var(--mono)}
.stat .l{font-size:13px;color:var(--muted);margin-top:6px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.note{font-size:14px;color:var(--muted);margin:6px 0 0}
section{padding:40px 0 8px}
section h2{font-size:clamp(28px,4vw,40px);letter-spacing:-.03em;line-height:1.1;margin:8px 0 18px;font-weight:900}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}
.card{border:2px solid var(--line);border-radius:14px;background:var(--surface);padding:22px;box-shadow:var(--shadow)}
.card h3{margin:10px 0 8px;font-size:22px;letter-spacing:-.02em}
.card p{margin:0;color:var(--muted)}
.card code,.steps code,.honest code{font-family:var(--mono);font-size:.9em;background:rgba(127,127,127,.14);padding:1px 6px;border-radius:5px}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;counter-reset:step}
.step{border:2px solid var(--line);border-radius:14px;background:var(--surface);padding:18px;box-shadow:4px 4px 0 var(--ink);position:relative}
.step:before{counter-increment:step;content:counter(step);position:absolute;top:-14px;left:14px;width:30px;height:30px;border:2px solid var(--line);border-radius:999px;background:var(--blue);color:#fff;font-weight:900;display:grid;place-items:center;font-size:14px}
.step h4{margin:8px 0 6px;font-size:18px}
.step pre{margin:8px 0 0;padding:10px 12px;border:2px solid var(--line);border-radius:8px;background:var(--bg);font-family:var(--mono);font-size:13.5px;white-space:pre-wrap;word-break:break-word}
.step p{margin:0;color:var(--muted);font-size:15px}
.honest{border:2px solid var(--line);border-radius:14px;background:var(--surface);box-shadow:var(--shadow);padding:22px 24px}
.honest ul{margin:8px 0 0;padding-left:22px}
.honest li{margin:8px 0}
.honest li b{font-weight:800}
footer{margin-top:44px;padding:26px 0 40px;border-top:2px solid var(--line);font-size:15px;color:var(--muted)}
footer .row{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;justify-content:space-between}
footer a{font-weight:700}
@media (max-width:820px){.hero{grid-template-columns:1fr;gap:22px}.art{order:-1}}
@media (max-width:480px){body{font-size:16px}.wrap{padding:0 16px}.btn.big{width:100%;text-align:center}.stat .v{font-size:26px}}
"""

JS = """
(function(){
  var KEY='ragprobe-site-theme';var root=document.documentElement;var order=['auto','light','dark'];
  function read(){try{return localStorage.getItem(KEY)||'auto'}catch(e){return 'auto'}}
  function apply(v){if(v==='auto'){root.removeAttribute('data-theme')}else{root.setAttribute('data-theme',v)}
    var b=document.getElementById('theme');if(b){b.textContent='Theme: '+v}}
  apply(read());
  var btn=document.getElementById('theme');
  if(btn){btn.addEventListener('click',function(){var cur=read();var next=order[(order.indexOf(cur)+1)%order.length];
    try{localStorage.setItem(KEY,next)}catch(e){}apply(next)})}
})();
"""

ART = """
<svg viewBox="0 0 520 330" role="img" aria-label="Bars for retrieval scores, a probe needle, and a diff arrow">
  <defs>
    <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
      <path d="M20 0H0V20" fill="none" stroke="currentColor" stroke-opacity=".12" stroke-width="1"/>
    </pattern>
  </defs>
  <rect x="0" y="0" width="520" height="330" rx="10" fill="url(#grid)"/>
  <g stroke="currentColor" stroke-width="3" fill="none">
    <line x1="52" y1="270" x2="470" y2="270"/>
    <line x1="52" y1="270" x2="52" y2="48"/>
  </g>
  <g stroke="currentColor" stroke-width="3">
    <rect x="86" y="118" width="46" height="152" rx="4" fill="#2b5be0"/>
    <rect x="156" y="88" width="46" height="182" rx="4" fill="#2b5be0"/>
    <rect x="226" y="150" width="46" height="120" rx="4" fill="#f4b400"/>
    <rect x="296" y="198" width="46" height="72" rx="4" fill="#e8541e"/>
    <rect x="366" y="102" width="46" height="168" rx="4" fill="#2b5be0"/>
  </g>
  <g stroke="currentColor" stroke-width="3" stroke-dasharray="8 7" fill="none">
    <line x1="52" y1="126" x2="470" y2="126"/>
  </g>
  <text x="460" y="118" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13" font-weight="700" text-anchor="end" fill="currentColor">baseline</text>
  <g transform="translate(319 168) rotate(-28)">
    <rect x="-6" y="-70" width="12" height="70" rx="6" fill="#f4b400" stroke="currentColor" stroke-width="3"/>
    <circle cx="0" cy="-78" r="10" fill="#fffdf7" stroke="currentColor" stroke-width="3"/>
    <path d="M0 0 L0 24" stroke="currentColor" stroke-width="3"/>
  </g>
  <g transform="translate(330 60)">
    <rect x="0" y="0" width="150" height="40" rx="8" fill="#e8541e" stroke="currentColor" stroke-width="3"/>
    <text x="75" y="26" font-family="ui-sans-serif,system-ui,sans-serif" font-size="16" font-weight="800" text-anchor="middle" fill="#fff">regressed -0.17</text>
    <path d="M300 20 L280 8 L280 32 Z" transform="translate(-303 0)" fill="#fffdf7" stroke="currentColor" stroke-width="3"/>
  </g>
  <g font-family="ui-monospace,Menlo,Consolas,monospace" font-size="12" fill="currentColor" text-anchor="middle">
    <text x="109" y="292">P@k</text><text x="179" y="292">R@k</text><text x="249" y="292">MRR</text>
    <text x="319" y="292">ground</text><text x="389" y="292">hit</text>
  </g>
</svg>
"""


def stat_cell(value: str, label: str) -> str:
    return '<div class="stat"><div class="v">' + esc(value) + '</div><div class="l">' + esc(label) + "</div></div>"


def render_stats(numbers: Dict[str, str], dashboard_href: Optional[str]) -> str:
    if not numbers:
        return (
            '<div class="strip"><div class="stat"><div class="v">0</div>'
            '<div class="l">runs recorded</div></div></div>'
            '<p class="note">No runs recorded yet. The first push to main fills this in.</p>'
        )
    cells = [
        stat_cell(numbers["cases"], "golden cases"),
        stat_cell(numbers["pass_rate"], "latest pass rate"),
        stat_cell(numbers["hit_rate"], "hit rate@" + numbers["k"]),
        stat_cell(numbers["mrr"], "MRR"),
        stat_cell(numbers["documents"] + " / " + numbers["chunks"], "docs / chunks"),
        stat_cell(numbers["runs"], "runs in history"),
    ]
    note = (
        "Latest run " + esc(numbers["started_at"]) + " with the " + esc(numbers["provider"]) + " provider, across "
        + esc(numbers["categories"]) + " categories."
    )
    if dashboard_href:
        note += ' Every number here comes from the same history the <a href="' + esc(dashboard_href) + '">dashboard</a> reads.'
    return '<div class="strip">' + "".join(cells) + '</div><p class="note">' + note + "</p>"


def render(
    numbers: Dict[str, str],
    dashboard_href: Optional[str],
    report_href: Optional[str],
    repo_url: str,
    title: str = TITLE,
) -> str:
    """The whole page as one self-contained HTML string."""
    dash_link = dashboard_href or (repo_url + "#dashboard")
    readme = repo_url + "#readme"
    nav = [
        '<a href="' + esc(dash_link) + '">Dashboard</a>',
    ]
    if report_href:
        nav.append('<a href="' + esc(report_href) + '">Latest report</a>')
    nav.append('<a href="' + esc(repo_url) + '">GitHub</a>')
    nav.append('<button class="theme" id="theme" type="button">Theme: auto</button>')

    parts: List[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en"><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append("<title>" + esc(title) + " - " + esc(TAGLINE) + "</title>")
    parts.append('<meta name="description" content="' + esc(title + ": an evaluation and regression-testing harness for RAG pipelines and LLM features.") + '">')
    parts.append("<style>" + CSS + "</style></head><body>")
    parts.append('<div class="wrap">')

    parts.append('<header class="top"><a class="brand" href="./"><span class="mark">R</span>' + esc(title) + "</a>")
    parts.append('<nav class="links">' + "".join(nav) + "</nav></header>")

    parts.append('<section class="hero" id="top"><div>')
    parts.append('<span class="pill">Offline by default</span>')
    parts.append("<h1>Prompt changes are code changes.<br><span class=\"u\">Test them like it.</span></h1>")
    parts.append(
        '<p class="lead">' + esc(title) + " runs a golden dataset through a RAG pipeline, scores retrieval and "
        "answer quality, records a baseline, and fails CI when a change regresses a case. No API key needed to run "
        "the whole thing.</p>"
    )
    parts.append('<div class="cta"><a class="btn primary big" href="' + esc(dash_link) + '">Open the dashboard</a>')
    parts.append('<a class="btn big" href="' + esc(repo_url) + '">Source on GitHub</a></div>')
    parts.append('</div><div class="art">' + ART + "</div></section>")

    parts.append('<section id="numbers"><span class="pill blue">Live numbers</span>')
    parts.append("<h2>From the latest run on main</h2>")
    parts.append(render_stats(numbers, dashboard_href))
    parts.append("</section>")

    parts.append('<section id="what"><span class="pill orange">What it does</span>')
    parts.append("<h2>Three things a RAG system usually goes without</h2>")
    parts.append('<div class="cards">')
    parts.append(
        '<div class="card"><span class="pill">01</span><h3>A golden dataset with metrics</h3>'
        "<p>Questions with expected source chunks, required and forbidden keywords, and refusal rules. Retrieval is "
        "scored with <code>precision@k</code>, <code>recall@k</code>, hit rate and MRR, computed the strict way: "
        "precision divides by k, and an undefined metric is <code>null</code>, not zero.</p></div>"
    )
    parts.append(
        '<div class="card"><span class="pill">02</span><h3>Evaluators that can say no</h3>'
        "<p>Keyword presence, forbidden terms, refusal behaviour in both directions, citation validity, and an "
        "offline grounding check for unsupported claims. An LLM judge is available and reported separately, because "
        "a nondeterministic evaluator must never be the thing that fails the build.</p></div>"
    )
    parts.append(
        '<div class="card"><span class="pill">03</span><h3>A baseline and a diff</h3>'
        "<p><code>ragprobe baseline</code> records what good looks like. <code>ragprobe diff</code> re-runs and "
        "classifies every case as regressed, degraded, improved, flat, new or removed, and exits non-zero when the "
        "gate fails. Deleting a failing case counts as a failure too.</p></div>"
    )
    parts.append("</div></section>")

    parts.append('<section id="how"><span class="pill blue">How it works</span>')
    parts.append("<h2>Four commands, one gate</h2>")
    parts.append('<div class="steps">')
    parts.append('<div class="step"><h4>Run</h4><pre>ragprobe run --html</pre><p>Ingest the corpus, answer every golden case, score it, write results and a report. The run is appended to the history.</p></div>')
    parts.append('<div class="step"><h4>Baseline</h4><pre>ragprobe baseline</pre><p>Promote the current behaviour to the regression contract. Commit the file.</p></div>')
    parts.append('<div class="step"><h4>Change</h4><pre>ragprobe diff --max-sentences 1</pre><p>Edit a prompt, tune top-k, re-chunk. Here a CLI override simulates the change.</p></div>')
    parts.append('<div class="step"><h4>Diff</h4><pre>exit 1  GATE FAILED\nregressed 1  improved 7</pre><p>Every case classified against the baseline. A regressed case fails CI; drift is reported without failing it unless you ask.</p></div>')
    parts.append("</div></section>")

    parts.append('<section id="honest"><span class="pill orange">Honest by design</span>')
    parts.append("<h2>The parts most demos leave out</h2>")
    parts.append('<div class="honest"><ul>')
    parts.append(
        "<li><b>Two golden cases fail on purpose.</b> They are real defects the harness found in its own pipeline, "
        "kept as documented failures instead of deleted. One has perfect retrieval metrics and a wrong answer, which "
        "is the reason answers are scored as well as retrieval.</li>"
    )
    parts.append(
        "<li><b>The stub provider is deterministic, and that is the point.</b> Same input, same output, on any "
        "machine, so a baseline means something. Live mode against a real model is opt-in through "
        "<code>RAGPROBE_PROVIDER</code>.</li>"
    )
    parts.append(
        "<li><b>LLM-as-judge has known weaknesses</b> - non-determinism, position bias, self-preference, verbosity "
        "bias, shared blind spots. The README lists them, and the judge is advisory because of them.</li>"
    )
    parts.append(
        "<li><b>Exit codes mean something.</b> <code>0</code> passed, <code>1</code> a gate failed, <code>2</code> "
        "usage error or unusable input. CI can tell a regression from a typo.</li>"
    )
    parts.append(
        "<li><b>The diff checks itself.</b> It warns when the dataset changed, when the config fingerprint did not "
        "change (your edit did not take effect), or when the two runs used different providers.</li>"
    )
    parts.append("</ul></div></section>")

    parts.append('<footer><div class="row"><div>' + esc(title) + " - PyYAML is the only runtime dependency. "
                 "Charts and pages are generated in Python with no external assets.</div>")
    parts.append(
        '<div><a href="' + esc(readme) + '">README</a> &middot; <a href="' + esc(repo_url + "/blob/main/datasets/golden_set.yaml")
        + '">Golden set</a> &middot; <a href="' + esc(repo_url + "/actions") + '">CI</a></div></div></footer>'
    )
    parts.append("</div><script>" + JS + "</script></body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------
def build(history_dir: Path, out: Path, dashboard: Optional[str], report: Optional[str], repo_url: str) -> Path:
    """Render the page to ``out`` and return the path.

    ``dashboard`` and ``report`` are hrefs relative to the page. They are only
    linked when the target file exists next to the page (or when it is an
    absolute URL), so a site published without a dashboard has no dead link.
    """
    runs = load_runs(history_dir)
    numbers = stats(runs)

    def usable(href: Optional[str]) -> Optional[str]:
        if not href:
            return None
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return href if (out.parent / href).is_file() else None

    page = render(numbers, usable(dashboard), usable(report), repo_url)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render the RAGProbe landing page from the run history.")
    parser.add_argument("--history-dir", default="reports/history", help="directory of stored runs")
    parser.add_argument("--out", default="site/index.html", help="output HTML path")
    parser.add_argument("--dashboard", default="dashboard.html", help="href of the dashboard, relative to --out")
    parser.add_argument("--report", default="report.html", help="href of the latest report, relative to --out")
    parser.add_argument("--repo-url", default=REPO_URL, help="repository URL for the source links")
    args = parser.parse_args(argv)

    out = build(Path(args.history_dir), Path(args.out), args.dashboard, args.report, args.repo_url)
    runs = len(load_runs(Path(args.history_dir)))
    print("site -> " + str(out) + " (" + str(runs) + " run(s) in history)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
