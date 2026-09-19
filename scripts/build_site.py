#!/usr/bin/env python
"""Render the RAGProbe landing page (site/index.html) from the run history.

This is the front door of the GitHub Pages site: a marketing-style page in the
visual language of a developer-tools homepage - a thick nav band, an oversized
headline with a marker highlight, a tilted product window with hard offset
shadows, sticker badges, a mascot, a product grid, a numbered stepper, a dark
"by the numbers" band, a comparison table, sticky-note callouts and a dense
columnar footer. It shows live numbers from the latest recorded run and links
to the dashboard, the latest report and the repository.

It is deliberately outside the ``ragprobe`` package. The library stays a
testing tool; this script is presentation. It depends on the standard library
only, reads the history files directly (the same JSON ``ragprobe run`` writes)
and never makes a network request: the page it produces embeds its own CSS,
JS and SVG and links only to sibling pages and the repository. No web fonts,
no scripts, no images are fetched, so it renders offline and from disk.

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
INSTALL = "pip install git+https://github.com/khushi-git-7/ragprobe"


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
    """The numbers on the stats band, all from the latest run; '-' when unknown."""
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
# tokens, styles, scripts
# ---------------------------------------------------------------------------
CSS = """
:root{
--bg:#EEEFE9;--surface:#FDFDF8;--accent:#E5E7E0;--text:#151515;--muted:#4B4B4B;--muted-2:#7A7A7A;
--border:#D0D1C9;--ink:#151515;--hard:#151515;--band:#151515;--band-text:#EEEFE9;--terminal:#1D1F27;
--red:#F54E00;--yellow:#F9BD2B;--blue:#1D4AFF;--green:#36C46F;--purple:#B62AD9;--paper:#FFE58A;
--btn-border:#B17816;--btn-shadow:#CD8407;
--head:"Matter","Inter","Segoe UI",system-ui,sans-serif;--body:"Matter","Inter","Segoe UI",system-ui,sans-serif;
--mono:"JetBrains Mono","Consolas",monospace;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
--bg:#151515;--surface:#1D1F27;--accent:#232429;--text:#EEEFE9;--muted:#8F8F8F;--muted-2:#8F8F8F;--border:#3A3A3A;
--ink:#EEEFE9;--hard:#F54E00;--band:#0D0D0D;--terminal:#111216;color-scheme:dark}}
:root[data-theme="dark"]{
--bg:#151515;--surface:#1D1F27;--accent:#232429;--text:#EEEFE9;--muted:#8F8F8F;--muted-2:#8F8F8F;--border:#3A3A3A;
--ink:#EEEFE9;--hard:#F54E00;--band:#0D0D0D;--terminal:#111216;color-scheme:dark}
*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--body);font-size:17px;line-height:1.55;overflow-x:hidden}
a{color:inherit}
h1,h2,h3,h4{font-family:var(--head);margin:0}
code,pre,kbd{font-family:var(--mono)}
img,svg{max-width:100%}
.wrap{max-width:1200px;margin:0 auto;padding:0 24px}
.eyebrow{display:block;font-family:var(--mono);font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--red);margin-bottom:14px}
section{padding:96px 0}
section h2{font-size:clamp(32px,4.6vw,56px);font-weight:800;letter-spacing:-.03em;line-height:1.02;margin:0 0 16px;max-width:18em}
section p.sub{font-size:19px;color:var(--muted);margin:0 0 40px;max-width:40em}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
/* ---- buttons (two-layer pressed) ---- */
.cta{position:relative;display:inline-block;border-radius:8px;background:var(--btn-shadow);border:1.5px solid var(--btn-border);text-decoration:none;font-weight:700;font-size:15px;line-height:1;color:#151515;cursor:pointer;font-family:var(--body);padding:0;vertical-align:middle}
.cta>span{display:block;margin:-1.5px;padding:12px 20px;border-radius:8px;background:var(--yellow);border:1.5px solid var(--btn-border);transform:translateY(-3px);transition:transform .1s}
.cta:hover>span{transform:translateY(-4px)}
.cta:active>span{transform:translateY(-1px)}
.cta.lg{font-size:17px}.cta.lg>span{padding:15px 26px}
.cta.secondary{background:var(--ink);border-color:var(--ink);color:var(--text)}
.cta.secondary>span{background:var(--surface);border-color:var(--ink)}
.cta:focus-visible{outline:3px solid var(--blue);outline-offset:3px}
/* ---- nav ---- */
.topnav{background:var(--accent);border-bottom:1.5px solid var(--border)}
.topnav .wrap{display:flex;align-items:center;gap:18px;min-height:72px;flex-wrap:wrap;padding-top:10px;padding-bottom:10px}
.logo{display:flex;align-items:center;gap:10px;text-decoration:none;font-family:var(--head);font-weight:900;font-size:22px;letter-spacing:-.03em}
.logo .mark{width:34px;height:34px;border-radius:8px;background:var(--red);border:1.5px solid #151515;display:grid;place-items:center}
.logo .mark svg{width:20px;height:20px}
.navlinks{display:flex;gap:2px;margin:0 auto;padding:0;list-style:none;flex-wrap:wrap}
.navlinks a{display:block;padding:8px 14px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;color:var(--text)}
.navlinks a:hover{background:var(--bg)}
.navright{display:flex;align-items:center;gap:12px;margin-left:auto}
.theme{width:40px;height:40px;border-radius:8px;border:1.5px solid var(--ink);background:var(--surface);color:var(--text);cursor:pointer;display:grid;place-items:center;padding:0}
.theme svg{width:18px;height:18px}
.theme .moon{display:block}.theme .sun{display:none}
:root[data-theme="dark"] .theme .moon{display:none}:root[data-theme="dark"] .theme .sun{display:block}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .theme .moon{display:none}:root:not([data-theme="light"]) .theme .sun{display:block}}
.subnav{border-bottom:1.5px solid var(--border);background:var(--bg)}
.subnav .wrap{display:flex;gap:8px 18px;align-items:center;min-height:40px;font-size:13px;color:var(--muted);flex-wrap:wrap;padding-top:6px;padding-bottom:6px}
.subnav a{text-decoration:none;font-weight:600}
.subnav a:hover{color:var(--red)}
.badge{display:inline-block;padding:2px 9px;border:1.5px solid var(--border);border-radius:999px;font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.04em;background:var(--surface)}
.badge.live{border-color:var(--green);color:var(--green)}
/* ---- hero ---- */
.hero{padding:80px 0 72px;overflow:visible}
.hero .wrap{display:grid;grid-template-columns:1.05fr .95fr;gap:56px;align-items:center}
.hero h1{font-size:clamp(44px,7vw,88px);font-weight:900;letter-spacing:-.03em;line-height:1.0;margin:0 0 22px;position:relative;z-index:0}
.hl{position:relative;display:inline-block;z-index:0;padding:0 .1em}
.hl::before{content:"";position:absolute;left:-.04em;right:-.04em;top:.1em;bottom:.02em;background:var(--yellow);transform:rotate(-1deg);border-radius:.08em;z-index:-1}
:root[data-theme="dark"] .hl{color:#151515}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .hl{color:#151515}}
.hero .lead{font-size:21px;line-height:1.45;color:var(--muted);margin:0 0 30px;max-width:30em}
.ctas{display:flex;gap:14px;flex-wrap:wrap;align-items:center}
.fine{margin:18px 0 0;font-size:14px;color:var(--muted-2);font-weight:500}
.fine b{color:var(--text);font-weight:700}
.hero-art{position:relative;transform:rotate(-1.5deg);padding:24px 0 30px}
.window{position:relative;border:1.5px solid var(--ink);border-radius:12px;background:var(--surface);box-shadow:8px 8px 0 var(--hard);overflow:visible;animation:float 6s ease-in-out infinite}
.window .bar{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1.5px solid var(--ink);background:var(--accent);border-radius:11px 11px 0 0}
.window .dot{width:11px;height:11px;border-radius:50%;border:1.5px solid #151515}
.window .url{margin-left:10px;flex:1;background:var(--bg);border:1.5px solid var(--border);border-radius:999px;padding:3px 12px;font-family:var(--mono);font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.window .screen{padding:10px 12px 12px;border-radius:0 0 11px 11px;overflow:hidden}
.window .screen svg{display:block;width:100%;height:auto}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
.sticker{position:absolute;z-index:3;padding:7px 13px;border:2px solid #151515;border-radius:999px;background:var(--surface);color:var(--text);font-weight:800;font-size:13px;letter-spacing:-.01em;white-space:nowrap;box-shadow:3px 3px 0 var(--hard)}
.sticker.s1{top:-4px;left:-26px;transform:rotate(-6deg);background:var(--yellow);color:#151515}
.sticker.s2{right:-22px;top:38%;transform:rotate(4deg);background:var(--blue);color:#fff}
.sticker.s3{bottom:6px;right:12%;transform:rotate(-3deg)}
.mascot{position:absolute;left:-44px;bottom:-8px;width:112px;z-index:4;transform:rotate(6deg);filter:drop-shadow(3px 3px 0 var(--hard))}
/* ---- product grid ---- */
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
.product{display:flex;flex-direction:column;gap:12px;padding:24px;border:1.5px solid var(--border);border-radius:12px;background:var(--surface);text-decoration:none;transition:transform .12s,box-shadow .12s,border-color .12s}
.product:hover{transform:translate(-2px,-2px);box-shadow:4px 4px 0 var(--hard);border-color:var(--ink)}
.icon{width:32px;height:32px;border-radius:7px;display:grid;place-items:center;border:1.5px solid #151515}
.icon svg{width:18px;height:18px}
.product h3{font-size:20px;font-weight:800;letter-spacing:-.02em}
.product p{margin:0;color:var(--muted);font-size:15.5px;line-height:1.5;flex:1}
.product .more{font-weight:700;font-size:14px;color:var(--red)}
.product code{font-size:.9em;background:var(--accent);padding:1px 5px;border-radius:4px}
/* ---- stepper ---- */
.steps{list-style:none;margin:0 0 40px;padding:0;display:grid;grid-template-columns:repeat(4,1fr);gap:24px;position:relative;counter-reset:step}
.steps::before{content:"";position:absolute;top:28px;left:8%;right:8%;border-top:2.5px dashed var(--border);z-index:0}
.step{position:relative;z-index:1}
.step .num{width:56px;height:56px;border-radius:50%;background:var(--yellow);border:2px solid #151515;display:grid;place-items:center;font-family:var(--head);font-weight:900;font-size:22px;color:#151515;box-shadow:3px 3px 0 var(--hard);margin-bottom:18px}
.step h3{font-size:19px;font-weight:800;letter-spacing:-.02em;margin-bottom:6px}
.step p{margin:0;color:var(--muted);font-size:15px}
.step code{background:var(--accent);padding:1px 6px;border-radius:4px;font-size:.9em}
.terminal{background:var(--terminal);color:#EEEFE9;border:1.5px solid #151515;border-radius:12px;box-shadow:8px 8px 0 var(--hard);overflow:hidden;max-width:820px}
.terminal .tbar{display:flex;gap:8px;align-items:center;padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.12);font-family:var(--mono);font-size:12px;color:#8F8F8F}
.terminal .tbar .dot{width:11px;height:11px;border-radius:50%}
.terminal pre{margin:0;padding:18px 20px 22px;font-size:14px;line-height:1.6;overflow-x:auto;white-space:pre}
.terminal .p{color:var(--yellow)}.terminal .ok{color:var(--green)}.terminal .bad{color:var(--red);font-weight:700}.terminal .dim{color:#8F8F8F}.terminal .b{color:#fff;font-weight:700}
/* ---- numbers band ---- */
.band{background:var(--band);color:var(--band-text);padding:96px 0}
.band .eyebrow{color:var(--yellow)}
.band h2{color:#fff}
.band p.sub{color:#B5B5B0}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:24px;margin-top:8px}
.stat .v{font-family:var(--head);font-size:clamp(48px,7vw,84px);font-weight:900;letter-spacing:-.04em;line-height:1}
.stat .l{margin-top:8px;font-family:var(--mono);font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#B5B5B0}
.stat.y .v{color:var(--yellow)}.stat.r .v{color:var(--red)}.stat.b .v{color:#5B7BFF}.stat.g .v{color:var(--green)}
.substats{display:flex;flex-wrap:wrap;gap:10px 28px;margin-top:40px;padding-top:24px;border-top:1px solid #333;font-family:var(--mono);font-size:13px;color:#B5B5B0}
.substats b{color:#fff;font-weight:700}
.band .note{margin:18px 0 0;font-size:14px;color:#B5B5B0}
.band a{color:var(--yellow)}
/* ---- comparison ---- */
.compare{width:100%;border-collapse:separate;border-spacing:0;border:2px solid var(--ink);border-radius:12px;overflow:hidden;background:var(--surface);font-size:15.5px}
.compare th,.compare td{padding:16px 18px;text-align:left;border-bottom:1.5px solid var(--border);vertical-align:middle}
.compare thead th{font-family:var(--head);font-weight:800;font-size:16px;background:var(--accent);border-bottom:2px solid var(--ink)}
.compare thead th.us{color:var(--red)}
.compare tbody tr:nth-child(even) td{background:var(--accent)}
.compare tbody tr:last-child td{border-bottom:0}
.compare td.c{text-align:center;width:22%}
.compare td.c svg{width:26px;height:26px;vertical-align:middle}
.compare td.c .txt{font-weight:700;font-size:14px}
.compare td.first{font-weight:600}
.compare-scroll{overflow-x:auto}
/* ---- sticky notes ---- */
.notes{display:grid;grid-template-columns:repeat(2,1fr);gap:40px;max-width:980px}
.note{position:relative;background:var(--paper);color:#151515;border:1.5px solid #151515;padding:34px 26px 26px;box-shadow:6px 6px 0 var(--hard);transform:rotate(-1.5deg)}
.note:nth-child(2){transform:rotate(1.2deg);background:#FFD699}
.note::before{content:"";position:absolute;top:-13px;left:50%;width:96px;height:26px;background:rgba(255,255,255,.55);border:1px solid rgba(0,0,0,.1);transform:translateX(-50%) rotate(-2deg)}
.note h3{font-size:20px;font-weight:800;letter-spacing:-.02em;margin-bottom:10px}
.note p{margin:0 0 12px;font-size:15px;line-height:1.5}
.note pre{margin:0;padding:12px 14px;background:rgba(21,21,21,.08);border:1px dashed rgba(21,21,21,.35);border-radius:6px;font-size:13px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
/* ---- closing ---- */
.closing{padding:96px 0}
.closing .inner{border:2px solid var(--ink);border-radius:16px;background:var(--surface);box-shadow:10px 10px 0 var(--hard);padding:64px 40px;text-align:center}
.closing h2{margin:0 auto 16px;max-width:14em}
.closing p.sub{margin:0 auto 32px}
.install{display:inline-flex;align-items:stretch;max-width:100%;border:2px solid var(--ink);border-radius:10px;background:var(--terminal);color:#EEEFE9;margin:0 0 28px;overflow:hidden}
.install code{padding:14px 18px;font-size:15px;white-space:nowrap;overflow-x:auto}
.install code .p{color:var(--yellow)}
.install button{font:inherit;font-weight:700;font-size:13px;font-family:var(--body);border:0;border-left:2px solid var(--ink);background:var(--yellow);color:#151515;padding:0 16px;cursor:pointer}
.install button:hover{background:#FFD24F}
.install button.done{background:var(--green);color:#151515}
/* ---- footer ---- */
footer{background:var(--accent);border-top:2px solid var(--ink);padding:64px 0 32px;font-size:15px}
.fcols{display:grid;grid-template-columns:1.4fr repeat(4,1fr);gap:32px}
.fcols h4{font-family:var(--head);font-size:14px;font-weight:800;letter-spacing:.02em;text-transform:uppercase;margin-bottom:14px}
.fcols ul{list-style:none;margin:0;padding:0;display:grid;gap:9px}
.fcols a{text-decoration:none;color:var(--muted)}
.fcols a:hover{color:var(--red);text-decoration:underline}
.fcols .blurb{color:var(--muted);font-size:14.5px;line-height:1.55;max-width:26em;margin:12px 0 0}
.fbottom{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:48px;padding-top:24px;border-top:1.5px solid var(--border);color:var(--muted);font-size:14px}
.fbottom .tiny{width:38px;height:auto;flex:none}
.fbottom .right{margin-left:auto;display:flex;gap:16px;flex-wrap:wrap}
.fbottom a{text-decoration:none;font-weight:600}
/* ---- responsive ---- */
@media (max-width:1024px){.grid{grid-template-columns:repeat(2,1fr)}.steps{grid-template-columns:repeat(2,1fr)}.steps::before{display:none}.stats{grid-template-columns:repeat(2,1fr)}.fcols{grid-template-columns:1fr 1fr 1fr}.fcols .about{grid-column:1/-1}}
@media (max-width:900px){.hero .wrap{grid-template-columns:1fr;gap:40px}.hero-art{transform:none;padding:16px 0 0}.sticker.s1{left:0;top:-14px}.sticker.s2{right:0}.sticker.s3{right:8%}.mascot{left:-14px;width:90px}.hero{padding:56px 0 48px}}
@media (max-width:760px){section,.band,.closing{padding:56px 0}.topnav .wrap{gap:10px}.navlinks{order:3;width:100%;margin:0;justify-content:flex-start;overflow-x:auto;flex-wrap:nowrap}.navlinks a{padding:6px 10px;font-size:14px}.navright .cta{font-size:14px}.navright .cta>span{padding:10px 14px}.notes{grid-template-columns:1fr;gap:34px}.closing .inner{padding:44px 20px}.fcols{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.steps{grid-template-columns:1fr}}
@media (max-width:480px){body{font-size:16px}.wrap{padding:0 16px}.ctas .cta{width:100%;text-align:center}.stats{grid-template-columns:1fr 1fr;gap:18px}.stat .v{font-size:44px}.sticker{font-size:11.5px;padding:5px 10px}.sticker.s1{left:-6px}.sticker.s2{top:auto;bottom:34px;right:-6px}.sticker.s3{display:none}.mascot{width:72px;left:-10px;bottom:-4px}.fcols{grid-template-columns:1fr}.install{width:100%}.install code{font-size:13px}.compare{font-size:14px}.compare th,.compare td{padding:12px 10px}}
@media (prefers-reduced-motion:reduce){.window{animation:none}.product,.cta>span{transition:none}}
"""

JS = """
(function(){
  var KEY='ragprobe-site-theme';var root=document.documentElement;
  function stored(){try{return localStorage.getItem(KEY)}catch(e){return null}}
  function system(){return (window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light'}
  function current(){return root.getAttribute('data-theme')||stored()||system()}
  function apply(v){root.setAttribute('data-theme',v);var b=document.getElementById('theme');
    if(b){b.setAttribute('aria-label','Switch to '+(v==='dark'?'light':'dark')+' mode')}}
  var saved=stored();if(saved==='dark'||saved==='light'){apply(saved)}
  var btn=document.getElementById('theme');
  if(btn){btn.addEventListener('click',function(){var next=current()==='dark'?'light':'dark';
    try{localStorage.setItem(KEY,next)}catch(e){}apply(next)})}
  var copy=document.getElementById('copy');var cmd=document.getElementById('install-cmd');
  if(copy&&cmd){copy.addEventListener('click',function(){var text=cmd.textContent;
    function done(){copy.textContent='Copied';copy.classList.add('done');setTimeout(function(){copy.textContent='Copy';copy.classList.remove('done')},1600)}
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done,function(){fallback()})}else{fallback()}
    function fallback(){var ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.left='-9999px';
      document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done()}catch(e){}document.body.removeChild(ta)}})}
})();
"""

# The mock dashboard shown inside the tilted browser window in the hero.
# Values are illustrative and static; the real numbers live in the numbers band.
ART = """
<svg viewBox="0 0 560 330" role="img" aria-labelledby="art-title"><title id="art-title">A mock of the RAGProbe dashboard: KPI tiles, a pass-rate trend and per-category bars</title>
<rect x="0" y="0" width="560" height="330" rx="6" fill="var(--bg)"/>
<rect x="0" y="0" width="112" height="330" fill="var(--accent)"/>
<rect x="12" y="14" width="88" height="10" rx="3" fill="var(--text)" opacity=".85"/>
<rect x="12" y="40" width="88" height="18" rx="5" fill="var(--yellow)" stroke="#151515" stroke-width="1.5"/>
<g fill="var(--muted-2)" opacity=".55"><rect x="12" y="68" width="64" height="8" rx="3"/><rect x="12" y="86" width="72" height="8" rx="3"/><rect x="12" y="104" width="56" height="8" rx="3"/><rect x="12" y="122" width="68" height="8" rx="3"/></g>
<g font-family="var(--mono)" font-size="9" font-weight="700" letter-spacing=".08" fill="var(--muted)">
<text x="126" y="24">PASS RATE</text><text x="234" y="24">HIT RATE@3</text><text x="342" y="24">MRR</text><text x="450" y="24">REGRESSED</text></g>
<g stroke="var(--border)" stroke-width="1.5" fill="var(--surface)"><rect x="124" y="30" width="100" height="56" rx="6"/><rect x="232" y="30" width="100" height="56" rx="6"/><rect x="340" y="30" width="100" height="56" rx="6"/><rect x="448" y="30" width="100" height="56" rx="6"/></g>
<g font-family="var(--head)" font-weight="900" font-size="22" fill="var(--text)" letter-spacing="-.5"><text x="134" y="62">87.5%</text><text x="242" y="62">100%</text><text x="350" y="62">0.929</text><text x="458" y="62" fill="#F54E00">1</text></g>
<g font-family="var(--mono)" font-size="9" font-weight="700"><text x="134" y="78" fill="#36C46F">&#9650; +6.3 pts</text><text x="242" y="78" fill="#7A7A7A">&#9644; flat</text><text x="350" y="78" fill="#36C46F">&#9650; +0.02</text><text x="458" y="78" fill="#F54E00">&#9660; gate failed</text></g>
<rect x="124" y="98" width="424" height="122" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1.5"/>
<text x="134" y="114" font-family="var(--head)" font-weight="800" font-size="11" fill="var(--text)">Pass rate over runs</text>
<g stroke="var(--border)" stroke-width="1"><line x1="134" y1="140" x2="538" y2="140"/><line x1="134" y1="170" x2="538" y2="170"/><line x1="134" y1="200" x2="538" y2="200"/></g>
<path d="M140,196 L190,180 L240,184 L290,160 L340,166 L390,138 L440,142 L490,128 L532,126 L532,208 L140,208 Z" fill="#1D4AFF" opacity=".12"/>
<path d="M140,196 L190,180 L240,184 L290,160 L340,166 L390,138 L440,142 L490,128 L532,126" fill="none" stroke="#1D4AFF" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
<line x1="390" y1="124" x2="390" y2="208" stroke="#F9BD2B" stroke-width="1.5" stroke-dasharray="3 3"/>
<path d="M390,118 l5,5 l-5,5 l-5,-5 z" fill="#F9BD2B" stroke="#151515" stroke-width="1"/>
<g fill="#1D4AFF" stroke="var(--surface)" stroke-width="1.5"><circle cx="140" cy="196" r="3"/><circle cx="190" cy="180" r="3"/><circle cx="240" cy="184" r="3"/><circle cx="290" cy="160" r="3"/><circle cx="340" cy="166" r="3"/><circle cx="390" cy="138" r="3"/><circle cx="440" cy="142" r="3"/><circle cx="490" cy="128" r="3"/></g>
<circle cx="532" cy="126" r="4.5" fill="#F54E00" stroke="#151515" stroke-width="1.5"/>
<rect x="124" y="232" width="424" height="86" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1.5"/>
<text x="134" y="248" font-family="var(--head)" font-weight="800" font-size="11" fill="var(--text)">Pass rate by category</text>
<g font-family="var(--mono)" font-size="9" fill="var(--muted)"><text x="134" y="264">refunds</text><text x="134" y="282">security</text><text x="134" y="300">pricing</text></g>
<g fill="var(--accent)"><rect x="200" y="256" width="330" height="10" rx="3"/><rect x="200" y="274" width="330" height="10" rx="3"/><rect x="200" y="292" width="330" height="10" rx="3"/></g>
<rect x="200" y="256" width="330" height="10" rx="3" fill="#1D4AFF"/><rect x="200" y="274" width="248" height="10" rx="3" fill="#F9BD2B"/><rect x="200" y="292" width="132" height="10" rx="3" fill="#F54E00"/>
<g font-family="var(--mono)" font-size="9" font-weight="700" fill="var(--text)"><text x="536" y="264" text-anchor="end">100%</text><text x="454" y="282">75%</text><text x="338" y="300">40%</text></g>
</svg>
"""

# The mascot: a hedgehog holding a magnifying glass, drawn flat with thick
# outlines. Original artwork; sized for the corner of the hero window.
MASCOT = """
<svg viewBox="0 0 120 112" role="img" aria-labelledby="{id}"><title id="{id}">Probe the hedgehog, peering through a magnifying glass</title>
<g stroke="#151515" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round">
<path d="M28 70 L20 50 L33 56 L34 36 L45 48 L52 28 L59 46 L72 30 L74 50 L90 40 L84 58 L100 58 L88 70 Z" fill="#F54E00"/>
<ellipse cx="60" cy="76" rx="40" ry="26" fill="#F2C98F"/>
<path d="M22 78 C24 60 40 54 58 56 L62 60 C70 62 80 62 90 66 C96 70 98 84 92 92 C80 100 40 100 26 92 C20 88 21 82 22 78 Z" fill="#F7E2C0"/>
<path d="M20 78 C10 76 4 80 6 86 C8 90 14 90 20 86 Z" fill="#F7E2C0"/>
<circle cx="8" cy="86" r="3.5" fill="#151515" stroke="none"/>
<circle cx="34" cy="74" r="6.5" fill="#fff"/><circle cx="35.5" cy="75" r="2.6" fill="#151515" stroke="none"/>
<path d="M25 63 Q32 58 40 64" fill="none"/>
<circle cx="56" cy="72" r="6.5" fill="#fff"/><circle cx="57.5" cy="73" r="2.6" fill="#151515" stroke="none"/>
<path d="M50 66 L63 67" fill="none"/>
<path d="M38 88 Q44 93 50 88" fill="none"/>
<ellipse cx="42" cy="101" rx="9" ry="4.5" fill="#F2C98F"/><ellipse cx="74" cy="101" rx="9" ry="4.5" fill="#F2C98F"/>
<path d="M70 84 C78 78 90 76 96 80" fill="none" stroke-width="5"/>
<path d="M70 84 C78 78 90 76 96 80" fill="none" stroke="#F2C98F" stroke-width="2"/>
<path d="M97 79 L110 95" stroke="#F9BD2B" stroke-width="7"/><path d="M97 79 L110 95" stroke="#151515" stroke-width="2" fill="none"/>
<circle cx="92" cy="72" r="13" fill="#9FC4FF" fill-opacity=".85"/>
<path d="M84 66 Q88 62 94 63" fill="none" stroke="#fff" stroke-width="2"/>
</g></svg>
"""


# ---------------------------------------------------------------------------
# small pieces
# ---------------------------------------------------------------------------
def _svg_icon(kind: str) -> str:
    """A white 18px glyph for a product card icon square."""
    stroke = 'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"'
    paths = {
        "dataset": '<path d="M4 6h10M4 12h16M4 18h12"/><path d="M17 4l2 2 3-3"/>',
        "metrics": '<path d="M4 20h16"/><rect x="6" y="10" width="3" height="7" rx="1"/><rect x="11" y="5" width="3" height="12" rx="1"/><rect x="16" y="12" width="3" height="5" rx="1"/>',
        "evaluators": '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 11l3 3 5-6"/>',
        "gate": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8 12h8"/>',
        "history": '<path d="M3 17l5-6 4 3 4-6 5 4"/><circle cx="20" cy="12" r="1.6"/>',
        "offline": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    }
    return '<svg viewBox="0 0 24 24" aria-hidden="true" ' + stroke + ">" + paths[kind] + "</svg>"


def _tick() -> str:
    return (
        '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="#36C46F" stroke="#151515" stroke-width="1.5"/>'
        '<path d="M7 12.5l3.2 3.2L17 9" fill="none" stroke="#151515" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        '<span class="sr">yes</span>'
    )


def _cross() -> str:
    return (
        '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="#F54E00" stroke="#151515" stroke-width="1.5"/>'
        '<path d="M8 8l8 8M16 8l-8 8" fill="none" stroke="#151515" stroke-width="2.6" stroke-linecap="round"/></svg>'
        '<span class="sr">no</span>'
    )


def _cta(href: str, label: str, secondary: bool = False, large: bool = False) -> str:
    cls = "cta" + (" secondary" if secondary else "") + (" lg" if large else "")
    return '<a class="' + cls + '" href="' + esc(href) + '"><span>' + label + "</span></a>"


def stat_cell(value: str, label: str, tone: str = "y") -> str:
    return '<div class="stat ' + tone + '"><div class="v">' + esc(value) + '</div><div class="l">' + esc(label) + "</div></div>"


def render_stats(numbers: Dict[str, str], dashboard_href: Optional[str]) -> str:
    """The stats inside the dark "by the numbers" band."""
    if not numbers:
        return (
            '<div class="stats">' + stat_cell("0", "runs recorded", "y") + "</div>"
            '<p class="note">No runs recorded yet. The first push to main fills this in.</p>'
        )
    cells = [
        stat_cell(numbers["runs"], "runs recorded", "y"),
        stat_cell(numbers["cases"], "golden cases", "r"),
        stat_cell(numbers["pass_rate"], "latest pass rate", "b"),
        stat_cell(numbers["hit_rate"], "hit rate@" + numbers["k"], "g"),
    ]
    sub = (
        "<span>MRR <b>" + esc(numbers["mrr"]) + "</b></span>"
        "<span>docs / chunks <b>" + esc(numbers["documents"]) + " / " + esc(numbers["chunks"]) + "</b></span>"
        "<span>categories <b>" + esc(numbers["categories"]) + "</b></span>"
        "<span>provider <b>" + esc(numbers["provider"]) + "</b></span>"
        "<span>latest run <b>" + esc(numbers["started_at"]) + "</b></span>"
    )
    note = "Every number comes from the latest recorded run on main."
    if dashboard_href:
        note += ' The <a href="' + esc(dashboard_href) + '">dashboard</a> reads the same history.'
    return '<div class="stats">' + "".join(cells) + '</div><div class="substats">' + sub + '</div><p class="note">' + note + "</p>"


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------
def _nav(dash_link: str, readme: str, repo_url: str, report_href: Optional[str]) -> str:
    logo_glyph = (
        '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="#fff" stroke-width="2.4"/>'
        '<path d="M12.8 12.8L17 17" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/></svg>'
    )
    links = [
        ("#overview", "Overview"),
        ("#how", "How it works"),
        (dash_link, "Dashboard"),
        (readme, "Docs"),
        (repo_url, "GitHub"),
    ]
    items = "".join('<li><a href="' + esc(href) + '">' + label + "</a></li>" for href, label in links)
    theme_btn = (
        '<button class="theme" id="theme" type="button" aria-label="Toggle dark mode">'
        '<svg class="moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>'
        '<svg class="sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" stroke-width="2"/>'
        '<path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'
        "</button>"
    )
    sub = [
        '<span class="badge">v0.1 &middot; MIT</span>',
        '<span class="badge">Python 3.9+</span>',
        '<span class="badge live">runs offline <span class="badge live">CI green &middot; runs offline</span>middot; no API key</span>',
        '<a href="' + esc(repo_url + "/actions") + '">Latest CI run &rarr;</a>',
    ]
    if report_href:
        sub.append('<a href="' + esc(report_href) + '">Latest HTML report &rarr;</a>')
    sub.append('<a href="' + esc(repo_url + "/blob/main/datasets/golden_set.yaml") + '">Golden set &rarr;</a>')
    return (
        '<header class="topnav"><div class="wrap">'
        '<a class="logo" href="./"><span class="mark">' + logo_glyph + "</span>RAGProbe</a>"
        '<ul class="navlinks">' + items + "</ul>"
        '<div class="navright">' + _cta(readme, "Get started &ndash; free") + theme_btn + "</div>"
        "</div></header>"
        '<div class="subnav"><div class="wrap">' + "".join(sub) + "</div></div>"
    )


def _hero(dash_link: str, readme: str) -> str:
    stickers = (
        '<span class="sticker s1">exit code 1 on regression</span>'
        '<span class="sticker s2">no API key needed</span>'
        '<span class="sticker s3">PyYAML only</span>'
    )
    window = (
        '<div class="window"><div class="bar">'
        '<span class="dot" style="background:#F54E00"></span><span class="dot" style="background:#F9BD2B"></span><span class="dot" style="background:#36C46F"></span>'
        '<span class="url">ragprobe &middot; dashboard.html &middot; overview</span></div>'
        '<div class="screen">' + ART + "</div></div>"
    )
    return (
        '<section class="hero" id="overview"><div class="wrap"><div>'
        '<span class="eyebrow">Regression testing for RAG</span>'
        '<h1>Catch RAG regressions <span class="hl">before</span> they ship.</h1>'
        '<p class="lead">RAGProbe runs a golden dataset through your pipeline, scores retrieval and answers, '
        "records a baseline, and fails CI the moment a prompt or chunking change makes a case worse.</p>"
        '<div class="ctas">' + _cta(readme, "Get started &ndash; free", large=True)
        + _cta(dash_link, "Open the live dashboard", secondary=True, large=True) + "</div>"
        '<p class="fine"><b>Open source</b> &middot; MIT &middot; 370+ tests &middot; runs offline &middot; one dependency</p>'
        '</div><div class="hero-art">' + stickers + window
        + '<div class="mascot">' + MASCOT.format(id="mascot-hero") + "</div>"
        "</div></div></section>"
    )


def _products(readme: str, dash_link: str) -> str:
    cards = [
        ("dataset", "#1D4AFF", "#fff", "Golden dataset", "Questions with expected chunks, required and forbidden keywords and refusal rules, in one YAML file you commit next to the code.", readme),
        ("metrics", "#F54E00", "#fff", "Retrieval metrics", "<code>precision@k</code>, <code>recall@k</code>, hit rate and MRR computed the strict way: precision divides by k and an undefined metric is <code>null</code>, never zero.", readme),
        ("evaluators", "#36C46F", "#151515", "Answer evaluators", "Keyword presence, forbidden terms, refusal in both directions, citation validity and an offline grounding check. The LLM judge is advisory only.", readme),
        ("gate", "#F9BD2B", "#151515", "Regression gate", "<code>ragprobe diff</code> classifies every case as regressed, degraded, improved, flat, new or removed and exits 1 when the gate fails.", readme),
        ("history", "#B62AD9", "#fff", "History &amp; dashboard", "Every run is appended to a history store. The dashboard plots trends, marks config changes and attributes failures to retrieval or generation.", dash_link),
        ("offline", "#151515", "#fff", "Runs offline in CI", "A deterministic stub provider means the same input gives the same output on any machine. No key, no network, no flaky baseline.", readme),
    ]
    out = []
    for kind, bg, fg, title, body, href in cards:
        out.append(
            '<a class="product" href="' + esc(href) + '">'
            '<span class="icon" style="background:' + bg + ";color:" + fg + '">' + _svg_icon(kind) + "</span>"
            "<h3>" + title + "</h3><p>" + body + "</p>"
            '<span class="more">Learn more &rarr;</span></a>'
        )
    return (
        '<section id="product"><div class="wrap">'
        '<span class="eyebrow">What you get</span>'
        "<h2>Everything a RAG pipeline needs to be tested like code</h2>"
        '<p class="sub">One package, one dependency. Each piece works on its own and they all write to the same history.</p>'
        '<div class="grid">' + "".join(out) + "</div></div></section>"
    )


def _how() -> str:
    steps = [
        ("Write cases", "Describe what a good answer looks like in <code>golden_set.yaml</code>: expected chunks, keywords, refusals."),
        ("<code>ragprobe run</code>", "Ingest the corpus, answer every case, score retrieval and answers, append the run to history."),
        ("<code>ragprobe baseline</code>", "Promote the current behaviour to the regression contract and commit the file."),
        ("<code>ragprobe diff</code>", "Re-run after every change. A regressed case fails CI with exit code 1; drift is reported."),
    ]
    items = "".join(
        '<li class="step"><span class="num">' + str(i + 1) + "</span><h3>" + title + "</h3><p>" + body + "</p></li>"
        for i, (title, body) in enumerate(steps)
    )
    terminal = (
        '<div class="terminal"><div class="tbar">'
        '<span class="dot" style="background:#F54E00"></span><span class="dot" style="background:#F9BD2B"></span><span class="dot" style="background:#36C46F"></span>'
        "<span>ci &middot; ragprobe diff</span></div><pre>"
        '<span class="p">$</span> ragprobe diff --baseline baselines/baseline.json --max-regressions 0\n'
        '<span class="dim">comparing 16 cases against baseline 2026-09-18T17:30:23Z (config a91f3c)</span>\n'
        '<span class="ok">  improved </span> refund_window_annual      <span class="dim">0.71 -&gt; 0.93</span>\n'
        '<span class="ok">  improved </span> support_sla_sev1          <span class="dim">0.80 -&gt; 0.88</span>\n'
        '<span class="bad">  REGRESSED</span> pricing_growth_tier       <span class="dim">0.92 -&gt; 0.43  forbidden term present</span>\n'
        '<span class="dim">  flat      13 cases</span>\n\n'
        '<span class="b">GATE FAILED</span>  regressed 1  degraded 0  improved 2  flat 13\n'
        '<span class="dim">exit 1</span></pre></div>'
    )
    return (
        '<section id="how"><div class="wrap">'
        '<span class="eyebrow">How it works</span>'
        "<h2>Four commands, one gate</h2>"
        '<p class="sub">The workflow is the same one you already use for unit tests: write the expectation, record the baseline, fail the build on regression.</p>'
        '<ol class="steps">' + items + "</ol>" + terminal + "</div></section>"
    )


def _numbers(numbers: Dict[str, str], dashboard_href: Optional[str]) -> str:
    return (
        '<section class="band" id="numbers"><div class="wrap">'
        '<span class="eyebrow">By the numbers</span>'
        "<h2>Live from the latest run on main</h2>"
        + render_stats(numbers, dashboard_href)
        + "</div></section>"
    )


def _compare() -> str:
    rows = [
        ("Runs in CI without an API key", True, True, False),
        ("Fails the build on regression", True, False, "Sometimes"),
        ("Attributes failure to retrieval vs generation", True, False, "Sometimes"),
        ("Deterministic re-runs", True, False, False),
    ]

    def cell(value: Any) -> str:
        if value is True:
            return '<td class="c">' + _tick() + "</td>"
        if value is False:
            return '<td class="c">' + _cross() + "</td>"
        return '<td class="c"><span class="txt">' + esc(value) + "</span></td>"

    body = "".join(
        '<tr><td class="first">' + label + "</td>" + cell(a) + cell(b) + cell(c) + "</tr>" for label, a, b, c in rows
    )
    body += (
        '<tr><td class="first">Cost</td><td class="c"><span class="txt">Free, MIT</span></td>'
        '<td class="c"><span class="txt">Your afternoon, every time</span></td>'
        '<td class="c"><span class="txt">Per seat, per month</span></td></tr>'
    )
    return (
        '<section id="why"><div class="wrap">'
        '<span class="eyebrow">Why RAGProbe</span>'
        "<h2>Versus the two things teams do instead</h2>"
        '<p class="sub">Most RAG systems are tested by re-reading answers in a notebook, or by paying for an eval product that needs a key, a network and a budget.</p>'
        '<div class="compare-scroll"><table class="compare"><thead><tr><th></th><th class="us">RAGProbe</th><th>Eyeballing in a notebook</th><th>Paid eval SaaS</th></tr></thead>'
        "<tbody>" + body + "</tbody></table></div></div></section>"
    )


def _catches() -> str:
    return (
        '<section id="catches"><div class="wrap">'
        '<span class="eyebrow">What the gate catches</span>'
        "<h2>Two real failures, kept on purpose</h2>"
        '<p class="sub">The shipped golden set contains defects the harness found in its own pipeline. They stay in as documented failures instead of being deleted.</p>'
        '<div class="notes">'
        '<div class="note"><h3>Perfect retrieval, wrong answer</h3>'
        "<p>Every expected chunk came back at rank one. The answer still named the wrong plan tier, because the prompt let the model paraphrase a number.</p>"
        "<pre>hit_rate@3 1.000  mrr 1.000\nforbidden_absent  FAIL  found: &quot;Growth&quot;\nattribution: generation</pre></div>"
        '<div class="note"><h3>Deleting the failing case</h3>'
        "<p>Removing a case that used to fail is the oldest trick there is. The diff counts it as removed and the gate fails anyway.</p>"
        "<pre>removed  refund_window_annual  (was failing)\nGATE FAILED  removed 1\nexit 1</pre></div>"
        "</div></div></section>"
    )


def _closing(readme: str, repo_url: str) -> str:
    return (
        '<section class="closing" id="start"><div class="wrap"><div class="inner">'
        '<span class="eyebrow">Get started</span>'
        "<h2>Stop shipping prompt changes blind.</h2>"
        '<p class="sub">Install, run the sample corpus, record a baseline. Three commands and no API key.</p>'
        '<div class="install"><code id="install-cmd">' + esc(INSTALL) + '</code><button id="copy" type="button" aria-label="Copy install command">Copy</button></div>'
        '<div class="ctas" style="justify-content:center">' + _cta(readme, "Read the docs", large=True)
        + _cta(repo_url, "View on GitHub", secondary=True, large=True) + "</div>"
        "</div></div></section>"
    )


def _footer(dash_link: str, readme: str, repo_url: str, report_href: Optional[str]) -> str:
    docs = [
        (readme + "#quickstart", "Quickstart"),
        (readme + "#the-regression-workflow", "Regression workflow"),
        (readme + "#retrieval-metrics", "Retrieval metrics"),
        (readme + "#answer-quality-evaluators", "Evaluators"),
        (readme + "#known-weaknesses-of-llm-as-judge", "LLM-as-judge caveats"),
        (readme + "#cli-reference", "CLI reference"),
    ]
    project = [(dash_link, "Dashboard")]
    if report_href:
        project.append((report_href, "Latest report"))
    project += [
        (repo_url + "/blob/main/datasets/golden_set.yaml", "Golden set"),
        (repo_url + "/blob/main/baselines/baseline.json", "Baseline"),
        (repo_url + "/actions", "CI runs"),
    ]
    source = [
        (repo_url, "Repository"),
        (repo_url + "/issues", "Issues"),
        (repo_url + "/blob/main/LICENSE", "MIT license"),
        (repo_url + "/blob/main/tests", "Test suite"),
    ]
    author = [
        (repo_url + "/graphs/contributors", "Khushi Jain, author"),
        (repo_url + "/blob/main/README.md#design-decisions", "Design decisions"),
        (repo_url + "/blob/main/README.md#roadmap", "Roadmap"),
    ]

    def col(title: str, links: List[Any]) -> str:
        return (
            "<div><h4>" + title + "</h4><ul>"
            + "".join('<li><a href="' + esc(h) + '">' + esc(t) + "</a></li>" for h, t in links)
            + "</ul></div>"
        )

    return (
        "<footer><div class=\"wrap\"><div class=\"fcols\">"
        '<div class="about"><a class="logo" href="./"><span class="mark">'
        '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="#fff" stroke-width="2.4"/><path d="M12.8 12.8L17 17" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/></svg>'
        "</span>RAGProbe</a>"
        '<p class="blurb">' + esc(TAGLINE) + " PyYAML is the only runtime dependency. Every chart and page is generated in Python with no external assets, so it all works offline.</p></div>"
        + col("Project", project) + col("Docs", docs) + col("Source", source) + col("Author", author)
        + '</div><div class="fbottom"><span class="tiny">' + MASCOT.format(id="mascot-foot") + "</span>"
        "<span>MIT licensed &middot; Built by Khushi Jain</span>"
        '<span class="right"><a href="' + esc(repo_url) + '">GitHub</a><a href="' + esc(readme) + '">README</a><a href="#overview">Back to top &uarr;</a></span>'
        "</div></div></footer>"
    )


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

    parts: List[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en"><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append("<title>" + esc(title) + " - " + esc(TAGLINE) + "</title>")
    parts.append('<meta name="description" content="' + esc(title + ": an evaluation and regression-testing harness for RAG pipelines and LLM features. Golden dataset, retrieval metrics, answer evaluators and a CI gate that fails on regression.") + '">')
    parts.append("<style>" + CSS + "</style></head><body>")
    parts.append(_nav(dash_link, readme, repo_url, report_href))
    parts.append("<main>")
    parts.append(_hero(dash_link, readme))
    parts.append(_products(readme, dash_link))
    parts.append(_how())
    parts.append(_numbers(numbers, dashboard_href))
    parts.append(_compare())
    parts.append(_catches())
    parts.append(_closing(readme, repo_url))
    parts.append("</main>")
    parts.append(_footer(dash_link, readme, repo_url, report_href))
    parts.append("<script>" + JS + "</script></body></html>")
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
