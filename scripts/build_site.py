#!/usr/bin/env python
"""Render the RAGProbe landing page (site/index.html) from the run history.

The front door of the GitHub Pages site: a dark, animated product page that
presents RAGProbe as what it is - a security *and* evaluation harness for LLM
apps. A hero with an animated radar/shield, the security findings as real
inline-SVG charts, and a regression-gate section wired to the live numbers from
the most recent run.

It depends on the standard library only, reads the history files directly (the
same JSON ``ragprobe run`` writes) and never makes a network request: all CSS,
JS and SVG are inlined, and the page links only to sibling pages (the dashboard,
the security scorecard, the report) and the repository. No web fonts, scripts or
images are fetched, so it renders offline from a build artifact.

Usage::

    python scripts/build_site.py --history-dir reports/history --out site/index.html
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_URL = "https://github.com/khushi-git-7/ragprobe"
TITLE = "RAGProbe"
TAGLINE = "Security & evaluation harness for LLM apps."
INSTALL = "pip install git+https://github.com/khushi-git-7/ragprobe"


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def esc(value: Any) -> str:
    """HTML-escape anything that came from a results file, git or the command line."""
    return html.escape("" if value is None else str(value), quote=True)


def is_run(document: Any) -> bool:
    """A results document has a summary and a list of cases; nothing else is trusted."""
    return (
        isinstance(document, dict)
        and isinstance(document.get("summary"), dict)
        and isinstance(document.get("cases"), list)
    )


def load_runs(history_dir: Path) -> List[Dict[str, Any]]:
    """Every usable run in the directory, oldest first by file name."""
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
    """The live numbers, all from the latest run; '-' when unknown."""
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


def recent_commits(limit: int = 6) -> List[str]:
    """The last ``limit`` commit subjects, or an empty list when git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "log", "--format=%s", "-" + str(limit)],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------
CSS = """
:root{
  --bg:#07090d;--panel:#0e1219;--panel-2:#121823;--border:#1c2430;--border-2:#273243;
  --ink:#eef2f8;--muted:#9aa6b6;--faint:#5f6b7c;--accent:#ff5a1f;--accent-2:#ffb547;--glow:rgba(255,90,31,.35);
  --good:#38e08a;--bad:#ff5a6a;--s1:#4f9bff;--s2:#ff7a45;--track:#161d28;
  --font:"Inter","Segoe UI",system-ui,-apple-system,sans-serif;--mono:"JetBrains Mono","SF Mono","Consolas",monospace;
  color-scheme:dark;
}
:root[data-theme="light"]{
  --bg:#f5f6f8;--panel:#fff;--panel-2:#f6f7f9;--border:#e3e6ea;--border-2:#d5d9df;
  --ink:#101418;--muted:#55606d;--faint:#8b95a1;--accent:#e5490f;--accent-2:#d98300;--glow:rgba(229,73,15,.18);
  --good:#15a35b;--bad:#e5484d;--s1:#2a78d6;--s2:#eb6834;--track:#e9eaee;color-scheme:light;
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}
.shell{max-width:1120px;margin:0 auto;padding:0 24px}
h1,h2,h3{letter-spacing:-.03em;line-height:1.05;margin:0;font-weight:800}
a{color:inherit;text-decoration:none}
.mono{font-family:var(--mono)}
.eyebrow{font-family:var(--mono);font-size:12.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-weight:600}
.bgfx{position:fixed;inset:0;z-index:-1;pointer-events:none;background:radial-gradient(900px 500px at 70% -10%,var(--glow),transparent 60%),radial-gradient(700px 500px at 0 10%,rgba(79,155,255,.10),transparent 55%)}
.bgfx::after{content:"";position:absolute;inset:-100px;opacity:.45;background-image:linear-gradient(var(--border) 1px,transparent 1px),linear-gradient(90deg,var(--border) 1px,transparent 1px);background-size:54px 54px;-webkit-mask-image:radial-gradient(circle at 60% 0,#000,transparent 72%);mask-image:radial-gradient(circle at 60% 0,#000,transparent 72%);animation:drift 22s linear infinite}
@keyframes drift{to{transform:translate(54px,54px)}}
nav{position:sticky;top:0;z-index:50;backdrop-filter:blur(12px);background:color-mix(in srgb,var(--bg) 72%,transparent);border-bottom:1px solid var(--border)}
nav .shell{display:flex;align-items:center;gap:20px;height:64px}
.logo{display:flex;align-items:center;gap:10px;font-weight:800;font-size:17px}
.mark{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#0a0a0a;display:grid;place-items:center;font-weight:900;font-size:16px;box-shadow:0 0 24px -4px var(--glow)}
nav .links{margin-left:auto;display:flex;gap:2px}
nav .links a{padding:8px 13px;border-radius:9px;color:var(--muted);font-weight:500;font-size:14.5px}
nav .links a:hover{background:var(--panel);color:var(--ink)}
.tg{width:36px;height:36px;border-radius:10px;border:1px solid var(--border-2);background:var(--panel);color:var(--ink);cursor:pointer;display:grid;place-items:center}
:root[data-theme="light"] .tg .moon{display:none}:root:not([data-theme="light"]) .tg .sun{display:none}
.btn{display:inline-flex;align-items:center;gap:9px;padding:13px 22px;border-radius:12px;font-weight:700;font-size:15px;cursor:pointer;border:1px solid transparent;background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#0a0a0a;box-shadow:0 10px 40px -12px var(--glow);transition:filter .15s,transform .15s}
.btn:hover{filter:brightness(1.07);transform:translateY(-2px)}
.btn.ghost{background:transparent;border-color:var(--border-2);color:var(--ink);box-shadow:none}
.btn.ghost:hover{border-color:var(--accent);color:var(--accent)}
.hero{padding:88px 0 60px;display:grid;grid-template-columns:1.1fr .9fr;gap:48px;align-items:center}
.pill{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--border-2);background:var(--panel);border-radius:999px;padding:6px 13px;font-size:12.5px;color:var(--muted);font-family:var(--mono)}
.pill .d{width:7px;height:7px;border-radius:50%;background:var(--good);box-shadow:0 0 10px var(--good);animation:blink 1.6s ease-in-out infinite}
@keyframes blink{50%{opacity:.3}}
.hero h1{font-size:58px;margin:20px 0 18px}
.hero h1 .hl{background:linear-gradient(135deg,var(--accent),var(--accent-2));-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{font-size:18.5px;color:var(--muted);margin:0 0 28px;max-width:48ch}
.cta{display:flex;gap:14px;flex-wrap:wrap}
.scene{position:relative;height:360px;display:grid;place-items:center}
.radar{position:absolute;width:300px;height:300px;border-radius:50%;border:1px solid var(--border-2);opacity:.5}
.radar.r2{width:220px;height:220px}.radar.r3{width:140px;height:140px}
.sweep{position:absolute;width:300px;height:300px;border-radius:50%;background:conic-gradient(from 0deg,transparent 0 300deg,color-mix(in srgb,var(--accent) 45%,transparent) 340deg,transparent 360deg);animation:spin 4s linear infinite;-webkit-mask:radial-gradient(circle,transparent 30%,#000 31%);mask:radial-gradient(circle,transparent 30%,#000 31%)}
@keyframes spin{to{transform:rotate(360deg)}}
.shield{position:relative;z-index:3;color:var(--good);filter:drop-shadow(0 0 16px rgba(56,224,138,.55));animation:breathe 3s ease-in-out infinite}
@keyframes breathe{50%{transform:scale(1.06)}}
.ring{position:absolute;z-index:2;width:120px;height:120px;border-radius:50%;border:2px solid var(--good);opacity:0;animation:ping 3s ease-out infinite}
@keyframes ping{0%{transform:scale(.5);opacity:.6}80%,100%{transform:scale(2.1);opacity:0}}
.threat{position:absolute;z-index:1;width:10px;height:10px;border-radius:50%;background:var(--bad);box-shadow:0 0 10px var(--bad);animation:fly 3s ease-in infinite}
.threat::after{content:"";position:absolute;right:8px;top:3px;width:22px;height:2px;background:linear-gradient(90deg,transparent,var(--bad));border-radius:2px}
@keyframes fly{0%{transform:translate(var(--sx),var(--sy)) scale(1);opacity:0}12%{opacity:1}72%{transform:translate(calc(var(--sx)*.16),calc(var(--sy)*.16)) scale(1);opacity:1}84%{transform:translate(calc(var(--sx)*.11),calc(var(--sy)*.11)) scale(.4);opacity:0}100%{opacity:0}}
.hstats{position:absolute;bottom:-4px;display:flex;gap:26px}
.hstats div{text-align:center}.hstats .n{font-size:24px;font-weight:850}.hstats .l{font-size:11px;color:var(--faint);font-family:var(--mono);text-transform:uppercase;letter-spacing:.05em}
.term{border:1px solid var(--border-2);border-radius:14px;overflow:hidden;background:var(--panel);margin-top:24px;max-width:560px}
.term .tb{display:flex;gap:7px;padding:11px 14px;border-bottom:1px solid var(--border);background:var(--panel-2)}
.term .tb i{width:11px;height:11px;border-radius:50%}
.term pre{margin:0;padding:16px 18px;font-family:var(--mono);font-size:13px;line-height:1.7;min-height:150px;overflow-x:auto}
.term .c{color:var(--accent)}.term .g{color:var(--good)}.term .m{color:var(--faint)}.term .r{color:var(--bad)}
.cursor{display:inline-block;width:8px;height:15px;background:var(--accent);vertical-align:-2px;animation:cur 1s step-end infinite}
@keyframes cur{50%{opacity:0}}
section{padding:70px 0;border-top:1px solid var(--border)}
.reveal{opacity:0;transform:translateY(24px);transition:opacity .7s cubic-bezier(.2,.7,.2,1),transform .7s cubic-bezier(.2,.7,.2,1)}
.reveal.in{opacity:1;transform:none}
.shead{max-width:660px;margin-bottom:34px}
section h2{font-size:38px;margin:12px 0 12px}section .lede{color:var(--muted);font-size:18px}
.row3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.row2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.card{border:1px solid var(--border);border-radius:18px;background:linear-gradient(180deg,var(--panel),var(--panel-2));padding:24px;transition:transform .18s,border-color .18s}
.card:hover{transform:translateY(-6px);border-color:var(--accent)}
.card .ic{width:46px;height:46px;border-radius:13px;background:var(--panel-2);border:1px solid var(--border-2);display:grid;place-items:center;color:var(--accent);margin-bottom:16px}
.card h3{font-size:19px;margin-bottom:7px}.card p{color:var(--muted);font-size:14.5px;margin:0}
.figure{border:1px solid var(--border-2);border-radius:20px;background:linear-gradient(180deg,var(--panel),var(--panel-2));padding:28px}
.figure .cap{font-weight:750;font-size:17px}.figure .sub{color:var(--muted);font-size:13.5px;margin:2px 0 18px}
.legend{display:flex;gap:20px;margin-bottom:8px;font-size:13.5px;flex-wrap:wrap}
.legend span{display:inline-flex;align-items:center;gap:8px;font-weight:600}.sw{width:12px;height:12px;border-radius:4px}
.bar-rect{transition:opacity .15s,filter .15s}.chartwrap:hover .bar-rect{opacity:.4}.chartwrap .bar-rect:hover{opacity:1;filter:brightness(1.15)}
.grow{transform:scaleY(0);transform-origin:bottom;transition:transform 1s cubic-bezier(.2,.7,.2,1)}
.growx{transform:scaleX(0);transform-origin:left;transition:transform 1.1s cubic-bezier(.2,.7,.2,1)}
.in .grow,.in .growx{transform:none}
.axis{stroke:var(--border-2);stroke-width:1}.gl{stroke:var(--border);stroke-width:1;stroke-dasharray:2 5}
.tick{fill:var(--faint);font-size:11px;font-family:var(--mono)}.xlab{fill:var(--ink);font-size:13px;font-weight:650}
.vlab{fill:var(--ink);font-size:12.5px;font-weight:800;font-family:var(--mono)}
.insight{margin-top:16px;padding:14px 16px;border-left:3px solid var(--accent);background:var(--panel-2);border-radius:0 10px 10px 0;font-size:14.5px;color:var(--muted)}
.insight b{color:var(--ink)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:center}
.statrow{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:6px}
.stat{border:1px solid var(--border);border-radius:16px;background:linear-gradient(180deg,var(--panel),var(--panel-2));padding:20px}
.stat .n{font-size:30px;font-weight:850;letter-spacing:-.02em}.stat .l{font-size:12.5px;color:var(--faint);font-family:var(--mono);text-transform:uppercase;letter-spacing:.04em;margin-top:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:16px}
.risk{border:1px solid var(--border);border-radius:16px;background:linear-gradient(180deg,var(--panel),var(--panel-2));padding:20px;transition:transform .18s,border-color .18s}
.risk:hover{transform:translateY(-6px);border-color:var(--accent)}
.risk .r1{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.risk .nm{font-weight:700;font-size:15px}.risk .cd{color:var(--faint);font-size:11.5px;font-family:var(--mono);margin-top:4px}
.gr{width:50px;height:50px;border-radius:14px;display:grid;place-items:center;font-weight:850;font-size:24px;flex:none;background:rgba(56,224,138,.14);color:var(--good);border:1px solid rgba(56,224,138,.3)}
.risk .meter{margin-top:16px;height:7px;border-radius:999px;background:var(--track);overflow:hidden}
.risk .meter i{display:block;height:100%;background:linear-gradient(90deg,var(--good),#9ff5c6);border-radius:999px;width:0;transition:width 1.1s ease}
.risk.in .meter i{width:var(--w)}
.risk .ms{display:flex;justify-content:space-between;font-size:11.5px;color:var(--faint);margin-top:7px;font-family:var(--mono)}
.copy{display:inline-flex;align-items:center;gap:10px;border:1px solid var(--border-2);background:var(--panel);border-radius:12px;padding:12px 16px;font-family:var(--mono);font-size:14px;cursor:pointer;color:var(--ink)}
.copy:hover{border-color:var(--accent)}.copy .k{color:var(--accent)}
footer{padding:76px 0;border-top:1px solid var(--border);text-align:center}
footer h2{font-size:34px;margin-bottom:22px}footer .fl{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin-bottom:22px}
footer p{color:var(--faint);font-size:13px;font-family:var(--mono)}
@media (max-width:860px){.hero{grid-template-columns:1fr;padding-top:52px}.hero h1{font-size:42px}.row3,.row2,.two{grid-template-columns:1fr}.statrow{grid-template-columns:1fr 1fr}nav .links{display:none}.scene{height:300px}}
"""


# ---------------------------------------------------------------------------
# fragments
# ---------------------------------------------------------------------------
def _nav() -> str:
    links = [("#what", "What it does"), ("#finding", "The finding"),
             ("#defence", "Defences"), ("#gate", "Regression gate"),
             ("#start", "Quickstart"), (REPO_URL, "GitHub")]
    items = "".join('<a href="' + esc(h) + '">' + esc(t) + "</a>" for h, t in links)
    return (
        '<nav><div class="shell"><span class="logo"><span class="mark">R</span>RAGProbe</span>'
        '<span class="links">' + items + "</span>"
        '<button class="tg" id="tg" aria-label="Toggle theme">'
        '<svg class="moon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>'
        '<svg class="sun" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2 2M17 17l2 2M4.9 19.1l2-2M17 7l2-2" stroke-linecap="round"/></svg>'
        "</button></div></nav>"
    )


def _threats() -> str:
    seeds = [("-190px", "-120px", "0s"), ("200px", "-90px", ".4s"), ("-210px", "60px", ".8s"),
             ("190px", "120px", "1.2s"), ("-120px", "160px", "1.6s"), ("150px", "-160px", "2s"),
             ("-200px", "-20px", "2.4s"), ("120px", "170px", "2.8s")]
    return "".join(
        '<div class="threat" style="--sx:' + sx + ';--sy:' + sy + ';animation-delay:' + d + '"></div>'
        for sx, sy, d in seeds)


def _hero_cta(security_href: Optional[str], dashboard_href: Optional[str],
              report_href: Optional[str]) -> str:
    """The hero's buttons lead *into* the product, not out to the repo.

    The primary action is the first live page that exists (the security
    scorecard, then the dashboard, then the report); if none has been published
    yet it scrolls to the on-page walkthrough. The repo lives in the top nav, so
    a first visit is an invitation to look, not a detour to GitHub.
    """
    entry = next((h for h in (security_href, dashboard_href, report_href) if h), None)
    if entry:
        primary = ('<a class="btn" href="' + esc(entry) + '">See a live security scan &rarr;</a>')
    else:
        primary = '<a class="btn" href="#what">See how it works &darr;</a>'
    return ('<div class="cta">' + primary
            + '<a class="btn ghost" href="#start">Quickstart &darr;</a></div>')


def _hero(numbers: Dict[str, str], repo_url: str,
          security_href: Optional[str] = None, dashboard_href: Optional[str] = None,
          report_href: Optional[str] = None) -> str:
    runs = numbers.get("runs", "0")
    scene = (
        '<div class="scene" aria-hidden="true"><div class="radar"></div><div class="radar r2"></div>'
        '<div class="radar r3"></div><div class="sweep"></div><div class="ring"></div>'
        '<div class="shield"><svg width="64" height="74" viewBox="0 0 64 74" fill="none" stroke="currentColor" stroke-width="3.2">'
        '<path d="M32 3 58 13v22c0 17-11 29-26 36C17 64 6 52 6 35V13z" fill="rgba(56,224,138,.08)"/>'
        '<path d="M22 36l7 8 14-16" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
        + _threats()
        + '<div class="hstats">'
        '<div><div class="n"><span data-count="92" data-suffix="%">0</span></div><div class="l">attacks stopped</div></div>'
        '<div><div class="n"><span data-count="8">0</span></div><div class="l">OWASP risks</div></div>'
        '<div><div class="n"><span data-count="' + esc(runs) + '">0</span></div><div class="l">CI runs</div></div>'
        "</div></div>"
    )
    return (
        '<header class="hero shell"><div>'
        '<span class="pill"><span class="d"></span>Open-source &middot; runs free &amp; offline</span>'
        '<h1>Ship AI features that <span class="hl">don’t get hacked</span>.</h1>'
        "<p>RAGProbe attacks your LLM app the way the OWASP Top 10 describes, proves every hit "
        "with planted secrets, and tells you which defences actually hold — then gates it in CI.</p>"
        + _hero_cta(security_href, dashboard_href, report_href)
        + '<div class="term"><div class="tb"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i>'
        '<i style="background:#28c840"></i></div><pre id="term"></pre></div>'
        "</div>" + scene + "</header>"
    )


def _icon(path: str) -> str:
    return ('<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2">' + path + "</svg>")


def _what() -> str:
    cards = [
        (_icon('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'),
         "Chat assistant", "A support bot with a secret in its system prompt. Can a user talk it out, or hijack it?"),
        (_icon('<path d="M4 4h16v4H4zM4 10h16v10H4zM8 14h8"/>'),
         "RAG assistant", "Answers from retrieved docs — one written by the attacker. Does the poison get retrieved, and obeyed?"),
        (_icon('<rect x="4" y="7" width="16" height="12" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'),
         "Email agent", "Reads and sends mail with tools. Can a planted email make it leak private data to an outsider?"),
    ]
    body = "".join('<div class="card"><div class="ic">' + ic + "</div><h3>" + t + "</h3><p>" + d + "</p></div>"
                   for ic, t, d in cards)
    return (
        '<section id="what" class="shell reveal" style="border-top:none">'
        '<div class="shead"><span class="eyebrow">What it tests</span><h2>Three apps, one attacker</h2>'
        '<p class="lede">The attacker controls some text each app reads. RAGProbe measures whether that '
        "text can take the app over — then whether a layered defence stops it.</p></div>"
        '<div class="row3">' + body + "</div></section>"
    )


def _finding() -> str:
    return (
        '<section id="finding" class="shell reveal">'
        '<div class="shead"><span class="eyebrow">The headline finding</span>'
        "<h2>AI safety filters are far weaker in German</h2>"
        '<p class="lede">Two injection detectors on 116 real labelled attacks, split by language. '
        "Both catch far fewer German attacks — Meta’s Prompt&nbsp;Guard&nbsp;2 nearly stops working.</p></div>"
        '<div class="figure"><div class="cap">Attacks caught (recall), by language</div>'
        '<div class="sub">Higher is better &middot; deepset/prompt-injections test split</div>'
        '<div class="legend"><span><i class="sw" style="background:var(--s1)"></i>Rule-based detector</span>'
        '<span><i class="sw" style="background:var(--s2)"></i>Meta Prompt Guard 2</span></div>'
        '<div class="chartwrap"><svg width="100%" viewBox="0 0 560 280" role="img" aria-label="Detector recall by language">'
        '<line class="gl" x1="54" y1="40" x2="540" y2="40"/><text class="tick" x="46" y="44" text-anchor="end">60%</text>'
        '<line class="gl" x1="54" y1="100" x2="540" y2="100"/><text class="tick" x="46" y="104" text-anchor="end">40%</text>'
        '<line class="gl" x1="54" y1="160" x2="540" y2="160"/><text class="tick" x="46" y="164" text-anchor="end">20%</text>'
        '<line class="axis" x1="54" y1="220" x2="540" y2="220"/><text class="tick" x="46" y="224" text-anchor="end">0%</text>'
        '<rect class="bar-rect grow" x="150" y="70" width="48" height="150" rx="4" fill="var(--s1)"><title>Rule-based &middot; English &middot; 50%</title></rect>'
        '<rect class="bar-rect grow" x="204" y="148" width="48" height="72" rx="4" fill="var(--s2)" style="transition-delay:.1s"><title>Prompt Guard 2 &middot; English &middot; 24%</title></rect>'
        '<text class="vlab" x="174" y="62" text-anchor="middle">50%</text><text class="vlab" x="228" y="140" text-anchor="middle">24%</text>'
        '<text class="xlab" x="201" y="245" text-anchor="middle">English</text>'
        '<rect class="bar-rect grow" x="348" y="142" width="48" height="78" rx="4" fill="var(--s1)" style="transition-delay:.2s"><title>Rule-based &middot; German &middot; 26%</title></rect>'
        '<rect class="bar-rect grow" x="402" y="205" width="48" height="15" rx="4" fill="var(--s2)" style="transition-delay:.3s"><title>Prompt Guard 2 &middot; German &middot; 5%</title></rect>'
        '<text class="vlab" x="372" y="134" text-anchor="middle">26%</text><text class="vlab" x="426" y="197" text-anchor="middle">5%</text>'
        '<text class="xlab" x="399" y="245" text-anchor="middle">German</text></svg></div>'
        '<div class="insight">Prompt Guard 2 catches <b>24%</b> of English attacks but only <b>5%</b> in German '
        "— a blind spot the moment real users don’t type in English.</div></div></section>"
    )


def _defence() -> str:
    return (
        '<section id="defence" class="shell reveal"><div class="two">'
        '<div><span class="eyebrow">Does defence work</span>'
        '<h2 style="font-size:34px;margin-top:10px">Layered defence takes attacks to zero</h2>'
        '<p class="lede" style="font-size:16.5px">A hardened prompt, data-marking, a detector, a tool policy '
        "and an output filter — stacked. Attack success collapses from 92% to 0, with no legitimate "
        "requests wrongly blocked.</p></div>"
        '<div class="figure"><div class="cap">Attack-success rate by defence</div><div class="sub">Lower is better</div>'
        '<div class="chartwrap"><svg width="100%" viewBox="0 0 520 170" role="img" aria-label="92 to 0 percent">'
        '<text class="xlab" x="8" y="52">None</text><rect x="92" y="34" width="410" height="30" rx="15" fill="var(--track)"/>'
        '<rect class="bar-rect growx" x="92" y="34" width="377" height="30" rx="15" fill="var(--bad)" style="filter:drop-shadow(0 0 8px var(--bad))"><title>No defence &middot; 92%</title></rect>'
        '<text class="vlab" x="479" y="54" text-anchor="end" fill="#0a0a0a">92%</text>'
        '<text class="xlab" x="8" y="120">Layered</text><rect x="92" y="102" width="410" height="30" rx="15" fill="var(--track)"/>'
        '<rect class="bar-rect growx" x="92" y="102" width="8" height="30" rx="4" fill="var(--good)" style="filter:drop-shadow(0 0 8px var(--good));transition-delay:.25s"><title>Layered &middot; 0%</title></rect>'
        '<text class="vlab" x="112" y="122">0%</text></svg></div>'
        '<div class="insight">Every OWASP category reaches grade <b>A</b> — what one layer misses, the next catches.</div>'
        "</div></div></section>"
    )


def _scorecard(security_href: Optional[str]) -> str:
    rows = [("Prompt Injection", "LLM01", "100% → 0%"), ("Sensitive Info Disclosure", "LLM02", "100% → 0%"),
            ("Excessive Agency", "LLM06", "100% → 0%"), ("System Prompt Leakage", "LLM07", "100% → 0%"),
            ("Vector &amp; Embedding", "LLM08", "50% → 0%")]
    cells = "".join(
        '<div class="risk"><div class="r1"><div><div class="nm">' + nm + '</div><div class="cd">' + cd +
        '</div></div><div class="gr">A</div></div><div class="meter" style="--w:100%"><i></i></div>'
        '<div class="ms"><span>' + ba + "</span><span>stopped</span></div></div>"
        for nm, cd, ba in rows)
    more = ('<p style="margin-top:22px"><a class="btn ghost" href="' + esc(security_href) +
            '">Open the full scorecard →</a></p>') if security_href else ""
    return (
        '<section id="scorecard" class="shell reveal">'
        '<div class="shead"><span class="eyebrow">The report card</span><h2>OWASP Top 10 scorecard</h2>'
        '<p class="lede">A grade per risk under the layered defence — the share of attacks that still get through.</p></div>'
        '<div class="grid">' + cells + "</div>" + more + "</section>"
    )


def _gate(numbers: Dict[str, str], dashboard_href: Optional[str], report_href: Optional[str]) -> str:
    if not numbers:
        inner = ('<div class="figure"><div class="cap">No runs recorded yet</div>'
                 '<div class="sub">The quality numbers appear here once the regression gate has run in CI.</div></div>')
    else:
        tiles = [(numbers.get("pass_rate", "-"), "pass rate"), (numbers.get("cases", "-"), "golden cases"),
                 (numbers.get("hit_rate", "-"), "hit rate@" + numbers.get("k", "k")),
                 (numbers.get("mrr", "-"), "MRR")]
        strip = "".join('<div class="stat"><div class="n">' + esc(v) + '</div><div class="l">' + l + "</div></div>"
                        for v, l in tiles)
        links = []
        if dashboard_href:
            links.append('<a class="btn ghost" href="' + esc(dashboard_href) + '">Live dashboard →</a>')
        if report_href:
            links.append('<a class="btn ghost" href="' + esc(report_href) + '">Latest report →</a>')
        linkrow = ('<p style="margin-top:20px;display:flex;gap:12px;flex-wrap:wrap">' + "".join(links) + "</p>") if links else ""
        inner = '<div class="statrow">' + strip + "</div>" + linkrow
    return (
        '<section id="gate" class="shell reveal">'
        '<div class="shead"><span class="eyebrow">The other half</span><h2>A regression gate for answer quality</h2>'
        '<p class="lede">RAGProbe started as a <code>pytest</code> for RAG: a golden set, a baseline, and a CI gate '
        "that fails when a prompt or retrieval change quietly breaks answers. Live numbers from the latest run:</p></div>"
        + inner + "</section>"
    )


def _start(repo_url: str) -> str:
    return (
        '<section id="start" class="shell reveal"><div class="shead"><span class="eyebrow">Quickstart</span>'
        "<h2>Running in one line</h2><p class=\"lede\">Installs tiny and runs offline against a deterministic "
        "stub — no API key needed to try it.</p></div>"
        '<button class="copy" id="copy" data-cmd="' + esc(INSTALL) + '"><span class="k">$</span>'
        "<span>" + esc(INSTALL) + '</span><span id="copylab" style="color:var(--faint)">copy</span></button>'
        '<p style="margin-top:16px"><a class="btn" href="' + esc(repo_url) + '">Read the docs on GitHub</a></p>'
        "</section>"
    )


def _footer(dashboard_href: Optional[str], security_href: Optional[str], repo_url: str) -> str:
    links = ['<a class="btn" href="' + esc(repo_url) + '">Get it on GitHub</a>']
    if dashboard_href:
        links.append('<a class="btn ghost" href="' + esc(dashboard_href) + '">Dashboard</a>')
    if security_href:
        links.append('<a class="btn ghost" href="' + esc(security_href) + '">Security scorecard</a>')
    return (
        '<footer class="reveal"><div class="shell"><h2>Test your AI before someone else does.</h2>'
        '<div class="fl">' + "".join(links) + "</div>"
        "<p>" + esc(TITLE) + " — " + esc(TAGLINE) + " &middot; free &amp; offline</p></div></footer>"
    )


SCRIPT = """
(function(){
  try{var t=localStorage.getItem('ragprobe-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}
  var tg=document.getElementById('tg');tg&&tg.addEventListener('click',function(){
    var n=document.documentElement.getAttribute('data-theme')!=='light'?'light':'dark';
    document.documentElement.setAttribute('data-theme',n);try{localStorage.setItem('ragprobe-theme',n);}catch(e){}});
  var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');
    e.target.querySelectorAll&&e.target.querySelectorAll('[data-count]').forEach(count);io.unobserve(e.target);}});},{threshold:.18});
  document.querySelectorAll('.reveal,.figure,.risk').forEach(function(el){io.observe(el);});
  function count(el){var to=+el.dataset.count,suf=el.dataset.suffix||'',t0=null,d=1100;
    function s(ts){t0=t0||ts;var p=Math.min((ts-t0)/d,1);el.textContent=Math.round(p*to)+suf;if(p<1)requestAnimationFrame(s);}requestAnimationFrame(s);}
  document.querySelectorAll('.scene [data-count]').forEach(count);
  var cp=document.getElementById('copy');cp&&cp.addEventListener('click',function(){
    try{navigator.clipboard.writeText(cp.dataset.cmd);var l=document.getElementById('copylab');if(l){l.textContent='copied';setTimeout(function(){l.textContent='copy';},1500);}}catch(e){}});
  var lines=[['m','$ '],['c','ragprobe'],['','  security run --defenses none,layered\\n'],
    ['m','  victim    : simulated   attacks : 12\\n'],['','  defence        ASR      95% CI\\n'],
    ['','  none           '],['r','92%'],['','    0.65-0.99\\n'],
    ['','  layered         '],['g','0%'],['','    0.00-0.28\\n'],
    ['g','  \\u2713 GATE PASSED '],['m','\\u2014 attack-success cut 92%']];
  var box=document.getElementById('term');if(box){box.innerHTML='<span class="cursor"></span>';var li=0,ci=0;
    function type(){if(li>=lines.length)return;var cls=lines[li][0],txt=lines[li][1];
      if(ci===0){var s=document.createElement('span');if(cls)s.className=cls;s.dataset.k=li;box.insertBefore(s,box.lastChild);}
      var sp=box.querySelector('span[data-k="'+li+'"]');sp.textContent=txt.slice(0,++ci);
      if(ci>=txt.length){li++;ci=0;setTimeout(type,40);}else setTimeout(type,txt.length>30?8:22);}
    setTimeout(type,500);}
})();
"""


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------
def render(numbers: Dict[str, str], dashboard_href: Optional[str], report_href: Optional[str],
           repo_url: str, changelog: Optional[List[str]] = None,
           security_href: Optional[str] = None) -> str:
    return (
        "<!doctype html><html lang=\"en\" data-theme=\"dark\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + esc(TITLE) + " — " + esc(TAGLINE) + "</title>"
        "<style>" + CSS + "</style></head><body><div class=\"bgfx\"></div>"
        + _nav()
        + _hero(numbers, repo_url, security_href, dashboard_href, report_href)
        + _what()
        + _finding()
        + _defence()
        + _scorecard(security_href)
        + _gate(numbers, dashboard_href, report_href)
        + _start(repo_url)
        + _footer(dashboard_href, security_href, repo_url)
        + "<script>" + SCRIPT + "</script></body></html>"
    )


def build(history_dir: Path, out: Path, dashboard: str, report: str, repo_url: str,
          changelog: Optional[List[str]] = None, security: str = "security.html") -> Path:
    runs = load_runs(history_dir)
    numbers = stats(runs)

    def usable(href: str) -> Optional[str]:
        if not href:
            return None
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return href if (out.parent / href).is_file() else None

    page = render(numbers, usable(dashboard), usable(report), repo_url,
                  changelog=changelog, security_href=usable(security))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render the RAGProbe landing page from the run history.")
    parser.add_argument("--history-dir", default="reports/history", help="directory of stored runs")
    parser.add_argument("--out", default="site/index.html", help="output HTML path")
    parser.add_argument("--dashboard", default="dashboard.html", help="href of the dashboard, relative to --out")
    parser.add_argument("--report", default="report.html", help="href of the latest report, relative to --out")
    parser.add_argument("--security", default="security.html", help="href of the security scorecard, relative to --out")
    parser.add_argument("--repo-url", default=REPO_URL, help="repository URL for the source links")
    parser.add_argument("--no-changelog", action="store_true", help="(kept for compatibility; unused)")
    args = parser.parse_args(argv)

    changelog = [] if args.no_changelog else recent_commits()
    out = build(Path(args.history_dir), Path(args.out), args.dashboard, args.report, args.repo_url,
                changelog=changelog, security=args.security)
    runs = len(load_runs(Path(args.history_dir)))
    print("site -> " + str(out) + " (" + str(runs) + " run(s) in history)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
