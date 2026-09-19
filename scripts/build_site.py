#!/usr/bin/env python
"""Render the RAGProbe landing page (site/index.html) from the run history.

This is the front door of the GitHub Pages site, built as a desktop: a thin
menu bar, a grass wallpaper, two columns of desktop icons and floating app
windows. The main window carries the headline, the "set up for free" card and
a tabbed panel; every icon opens a smaller window with the section it names.
All windows exist in the HTML at build time - without JavaScript they render
stacked below the main window, so nothing is unreachable.

It is deliberately outside the ``ragprobe`` package. The library stays a
testing tool; this script is presentation. It depends on the standard library
only, reads the history files directly (the same JSON ``ragprobe run`` writes)
and never makes a network request: the page embeds its own CSS, JS and SVG
(the wallpaper is a generated SVG tile in a data URI) and links only to
sibling pages and the repository. No web fonts, scripts or images are fetched.

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
from typing import Any, Dict, List, Optional, Tuple

REPO_URL = "https://github.com/khushi-git-7/ragprobe"
TITLE = "RAGProbe"
TAGLINE = "A regression gate for RAG pipelines."
INSTALL = "pip install git+https://github.com/khushi-git-7/ragprobe"

# Desktop icons, top to bottom, per column. The key is the window id suffix.
LEFT_ICONS: List[Tuple[str, str]] = [
    ("home", "Home"),
    ("gate", "The regression gate"),
    ("golden", "Golden sets"),
    ("metrics", "Metrics"),
    ("docs", "Docs"),
    ("demo", "Demo"),
    ("author", "Talk to the author"),
]
RIGHT_ICONS: List[Tuple[str, str]] = [
    ("about", "About"),
    ("changelog", "Changelog"),
    ("casestudy", "Case study"),
    ("examples", "Examples"),
    ("hire", "Hire me"),
    ("trash", "Trash"),
]
WINDOW_KEYS = [key for key, _ in LEFT_ICONS] + [key for key, _ in RIGHT_ICONS]


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
# wallpaper
# ---------------------------------------------------------------------------
def grass_tile(colors: List[str], opacity: str) -> str:
    """A 120x120 SVG tile of curved grass blades as a CSS ``url()`` data URI.

    Deterministic (a small LCG, not ``random``) so the page is byte-stable
    between builds. Blades are kept inside the tile so it repeats seamlessly.
    """
    seed = 20260919
    paths = []
    for i in range(38):
        seed = (seed * 1103515245 + 12345) % 2147483648
        x = 8 + seed % 104
        seed = (seed * 1103515245 + 12345) % 2147483648
        height = 18 + seed % 26
        seed = (seed * 1103515245 + 12345) % 2147483648
        bend = -8 + seed % 17
        seed = (seed * 1103515245 + 12345) % 2147483648
        y = height + 2 + seed % max(1, 118 - height)
        colour = colors[i % len(colors)]
        paths.append(
            "<path d='M" + str(x) + "," + str(y) + " q" + str(bend // 2) + "," + str(-height // 2)
            + " " + str(bend) + "," + str(-height) + "' stroke='" + colour + "'/>"
        )
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'>"
        "<g fill='none' stroke-width='1.6' stroke-linecap='round' opacity='" + opacity + "'>"
        + "".join(paths) + "</g></svg>"
    )
    encoded = svg.replace("#", "%23").replace("<", "%3C").replace(">", "%3E").replace(" ", "%20")
    return 'url("data:image/svg+xml,' + encoded + '")'


LIGHT_TILE = grass_tile(["#6E8F4F", "#7FA35B", "#5C7A40", "#8DB06A"], ".8")
DARK_TILE = grass_tile(["#2C3B22", "#37492B", "#22301A", "#3F5432"], ".8")


# ---------------------------------------------------------------------------
# styles and script
# ---------------------------------------------------------------------------
CSS = """
:root{--top:rgba(221,229,214,.88);--win:rgba(228,234,220,.94);--card:#FFFFFF;--panel:#F3F4EF;--text:#151515;--muted:#4B4B4B;
--border:rgba(0,0,0,.15);--line:#D0D1C9;--ctl:rgba(255,255,255,.55);--ctl-ink:#5A5A5A;--icon:#3D3D3D;--icon-2:#FFFFFF;
--orange:#F1A82C;--orange-2:#E5A32E;--btn-border:#B17816;--purple:#B62AD9;--red:#F54E00;--green:#36C46F;--blue:#1D4AFF;--yellow:#F9BD2B;
--terminal:#1D1F27;--code:#EEEFE9;--lawn-a:#7A9A5A;--lawn-b:#5F7F45;--tile:TILE_LIGHT;
--font:"Matter","Inter","Segoe UI",system-ui,sans-serif;--mono:"JetBrains Mono","Consolas",monospace;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--top:rgba(28,36,24,.9);--win:rgba(30,36,28,.94);--card:#1D1F27;--panel:#232429;--text:#EEEFE9;--muted:#B5B5B0;
--border:rgba(255,255,255,.14);--line:#3A3A3A;--ctl:rgba(255,255,255,.08);--ctl-ink:#B5B5B0;--icon:#2B2B2B;--icon-2:#EEEFE9;--code:#151515;--lawn-a:#2F3F26;--lawn-b:#1F2B18;--tile:TILE_DARK;color-scheme:dark}}
:root[data-theme="dark"]{--top:rgba(28,36,24,.9);--win:rgba(30,36,28,.94);--card:#1D1F27;--panel:#232429;--text:#EEEFE9;--muted:#B5B5B0;
--border:rgba(255,255,255,.14);--line:#3A3A3A;--ctl:rgba(255,255,255,.08);--ctl-ink:#B5B5B0;--icon:#2B2B2B;--icon-2:#EEEFE9;--code:#151515;--lawn-a:#2F3F26;--lawn-b:#1F2B18;--tile:TILE_DARK;color-scheme:dark}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;color:var(--text);font-family:var(--font);font-size:15px;line-height:1.5;
background-color:var(--lawn-b);
background-image:repeating-radial-gradient(circle at 30% 40%,rgba(255,255,255,.035) 0 2px,transparent 2px 6px),var(--tile),linear-gradient(var(--lawn-a),var(--lawn-b));
background-size:auto,240px 240px,100% 100%;background-attachment:fixed}
a{color:inherit}
h1,h2,h3,h4{margin:0;letter-spacing:-.02em}
code,pre,kbd{font-family:var(--mono)}
svg{max-width:100%}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
/* ---- menu bar ---- */
.menubar{position:sticky;top:0;z-index:300;height:48px;display:flex;align-items:center;gap:4px;padding:0 14px;background:var(--top);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid var(--border)}
.logo{display:inline-flex;align-items:center;gap:8px;text-decoration:none;font-weight:800;font-size:16px;letter-spacing:-.02em;margin-right:14px}
.mark{width:26px;height:26px;border-radius:7px;background:var(--red);border:1.5px solid #151515;display:inline-grid;place-items:center;flex:none}
.mark svg{width:15px;height:15px}
.menu{display:flex;gap:2px;margin:0;padding:0;list-style:none}
.menu a{display:block;padding:6px 10px;border-radius:6px;text-decoration:none;font-size:15px;font-weight:500}
.menu a:hover{background:rgba(255,255,255,.35)}
.mright{margin-left:auto;display:flex;align-items:center;gap:6px}
.ibtn{width:32px;height:32px;border-radius:8px;border:1px solid var(--border);background:var(--ctl);color:var(--text);display:grid;place-items:center;cursor:pointer;padding:0;text-decoration:none}
.ibtn svg{width:16px;height:16px}
.ibtn .moon{display:block}.ibtn .sun{display:none}
:root[data-theme="dark"] .ibtn .moon{display:none}:root[data-theme="dark"] .ibtn .sun{display:block}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .ibtn .moon{display:none}:root:not([data-theme="light"]) .ibtn .sun{display:block}}
/* ---- 3D buttons ---- */
.b3{display:inline-flex;justify-content:center;align-items:center;gap:8px;padding:10px 18px;border:1.5px solid var(--btn-border);border-bottom-width:4px;border-radius:8px;background:var(--orange);color:#151515;font-weight:700;font-size:15px;line-height:1.2;text-decoration:none;cursor:pointer;font-family:var(--font);transition:transform .08s,border-bottom-width .08s}
.b3:hover{background:#F7B23A}
.b3:active{transform:translateY(2px);border-bottom-width:2px}
.b3.white{background:#fff;border-color:var(--orange-2);border-bottom-color:var(--btn-border)}
.b3.white:hover{background:#FFF8EA}
.b3.full{display:flex;width:100%}
.b3.sm{padding:7px 12px;font-size:14px;border-bottom-width:3px}
/* ---- desktop ---- */
.stage{position:relative;min-height:calc(100vh - 48px);padding:36px 128px 72px}
.icons{position:absolute;top:22px;display:grid;gap:22px;z-index:5}
.icons.left{left:16px}.icons.right{right:16px}
.dicon{display:flex;flex-direction:column;align-items:center;gap:6px;width:92px;text-decoration:none;color:#fff;font-size:13px;font-weight:600;line-height:1.2;text-align:center;text-shadow:0 1px 3px rgba(0,0,0,.65),0 0 12px rgba(0,0,0,.35)}
.dicon svg{width:48px;height:48px;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35));transition:transform .1s}
.dicon:hover svg{transform:scale(1.07)}
.dicon:focus-visible{outline:2px solid #fff;outline-offset:4px;border-radius:8px}
/* ---- windows ---- */
.win{position:relative;background:var(--win);border:1px solid var(--border);border-radius:14px;box-shadow:0 24px 60px rgba(0,0,0,.28);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);overflow:hidden;margin:0 auto 26px;width:100%;max-width:1180px}
.win.sub{max-width:860px}
.win:focus{outline:none}
.js .win:not(.open){display:none}
@media (min-width:900px){.js .win.sub.open,.js .win.floating{position:absolute;margin:0;width:min(860px,80%)}.js .win.floating{max-width:none}}
.win.max{position:fixed !important;top:56px !important;left:8px !important;right:8px !important;bottom:8px !important;width:auto !important;max-width:none;margin:0;z-index:250 !important;overflow:auto}
.titlebar{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid var(--border);cursor:grab;user-select:none;background:rgba(255,255,255,.18)}
.titlebar:active{cursor:grabbing}
.titlebar .wtitle{font-weight:700;font-size:14px}
.wctl{margin-left:auto;display:flex;gap:6px}
.wctl button{width:26px;height:26px;border:1px solid var(--border);border-radius:6px;background:var(--ctl);color:var(--ctl-ink);cursor:pointer;display:grid;place-items:center;padding:0}
.wctl button:hover{background:rgba(255,255,255,.8);color:#151515}
.wctl svg{width:12px;height:12px}
.wbody{padding:24px 26px 28px}
.wbody p{margin:0 0 12px}
.wbody p.muted{color:var(--muted)}
.wbody h2{font-size:22px;font-weight:800;margin-bottom:10px}
.wbody h3{font-size:16px;font-weight:700;margin:18px 0 8px}
.wbody ul{margin:0 0 12px;padding-left:20px}
.wbody li{margin:4px 0}
.wbody code{font-size:.92em;background:var(--code);padding:1px 6px;border-radius:4px}
.wbody pre{margin:0 0 14px;padding:14px 16px;background:var(--code);border:1px solid var(--line);border-radius:10px;font-size:13px;line-height:1.55;overflow-x:auto}
.wbody pre code{background:none;padding:0}
/* ---- home window ---- */
.homegrid{display:grid;grid-template-columns:1.25fr .85fr;gap:32px;align-items:start}
.hero{padding:22px 0 0}
.hero h1{font-size:clamp(36px,4.6vw,56px);font-weight:800;letter-spacing:-.03em;line-height:1.02;margin:0 0 16px}
.hero .lead{font-size:18px;color:var(--muted);margin:0 0 20px;max-width:30em}
.hero .fine{font-size:13px;color:var(--muted)}
.setup{background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:0 10px 28px rgba(0,0,0,.14);padding:22px}
.setup h2{display:flex;align-items:center;gap:8px;font-size:19px;font-weight:800;margin-bottom:12px}
.setup .mark{width:22px;height:22px}
.setup ul{list-style:none;margin:0 0 16px;padding:0;display:grid;gap:8px}
.setup li{display:flex;gap:8px;align-items:center;font-size:14.5px}
.setup li svg{width:18px;height:18px;flex:none}
.setup .b3+.b3{margin-top:10px}
.install{display:flex;align-items:stretch;margin-top:14px;border:1px solid var(--line);border-radius:8px;background:var(--terminal);color:#EEEFE9;overflow:hidden}
.install code{flex:1;padding:9px 12px;font-size:12px;white-space:nowrap;overflow-x:auto;background:none;color:inherit;border-radius:0}
.install button{font:inherit;font-family:var(--font);font-weight:700;font-size:12px;border:0;border-left:1px solid rgba(255,255,255,.15);background:var(--yellow);color:#151515;padding:0 12px;cursor:pointer}
.install button.done{background:var(--green)}
/* ---- tabbed panel ---- */
.tabs{display:flex;gap:4px;margin-top:34px;flex-wrap:wrap}
.tab{padding:10px 16px;border:0;background:transparent;font:inherit;font-weight:600;font-size:14px;border-radius:8px 8px 0 0;cursor:pointer;color:var(--text)}
.tab:hover{background:rgba(182,42,217,.12)}
.tab[aria-selected="true"]{background:var(--purple);color:#fff}
.tabframe{border:3px solid var(--purple);border-radius:0 12px 12px 12px;background:var(--panel);padding:30px 28px}
.js .tabpanel:not(.active){display:none}
.no-js .tabpanel+.tabpanel{margin-top:28px;padding-top:24px;border-top:1px dashed var(--line)}
.centered{max-width:760px;margin:0 auto;text-align:center}
.centered .mark{width:40px;height:40px;border-radius:10px;margin:0 auto 12px}
.centered .mark svg{width:22px;height:22px}
.centered h2{font-size:26px;font-weight:800;margin-bottom:18px}
.askbox{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;text-align:left;box-shadow:0 6px 18px rgba(0,0,0,.08)}
.askbox .ctx{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border:1px solid var(--line);border-radius:999px;font-size:12px;font-weight:600;color:var(--muted);margin-bottom:10px}
.askbox .placeholder{color:var(--muted);font-size:14px;margin:0 0 10px}
.askfoot{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border:1px solid var(--line);border-radius:8px;font-size:12.5px;font-weight:600;background:var(--panel);color:var(--text)}
.chip svg{width:11px;height:11px;opacity:.6}
.arrow{margin-left:auto;width:36px;height:36px;border-radius:8px;background:#151515;color:#fff;display:grid;place-items:center;text-decoration:none;border:1.5px solid var(--btn-border);border-bottom-width:4px}
.arrow:active{transform:translateY(2px);border-bottom-width:2px}
.arrow svg{width:16px;height:16px}
.terminal{background:var(--terminal);color:#EEEFE9;border:1px solid rgba(0,0,0,.4);border-radius:10px;overflow:hidden;text-align:left}
.terminal .tbar{display:flex;gap:7px;align-items:center;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,.12);font-family:var(--mono);font-size:11.5px;color:#8F8F8F}
.terminal .dot{width:10px;height:10px;border-radius:50%}
.terminal pre{margin:0;padding:14px 16px 16px;font-size:13px;line-height:1.6;overflow-x:auto;background:none;border:0;color:inherit;border-radius:0}
.terminal .p{color:var(--yellow)}.terminal .ok{color:var(--green)}.terminal .bad{color:#FF7A45;font-weight:700}.terminal .dim{color:#8F8F8F}.terminal .b{color:#fff;font-weight:700}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;text-align:left}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.stat .v{font-size:30px;font-weight:800;letter-spacing:-.03em;line-height:1.05}
.stat .l{margin-top:6px;font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.stat.y .v{color:#B17816}.stat.r .v{color:var(--red)}.stat.b .v{color:var(--blue)}.stat.g .v{color:#1E8A4C}.stat.p .v{color:var(--purple)}
.substats{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:14px;font-family:var(--mono);font-size:12.5px;color:var(--muted);text-align:left}
.substats b{color:var(--text)}
.bandnote{margin:12px 0 0;font-size:13px;color:var(--muted);text-align:left}
/* ---- section windows ---- */
.steps{list-style:none;margin:0 0 18px;padding:0;display:grid;grid-template-columns:repeat(4,1fr);gap:18px;position:relative}
.steps::before{content:"";position:absolute;top:22px;left:10%;right:10%;border-top:2px dashed var(--line)}
.step{position:relative}
.step .num{width:44px;height:44px;border-radius:50%;background:var(--yellow);border:2px solid #151515;display:grid;place-items:center;font-weight:900;font-size:18px;color:#151515;margin-bottom:10px}
.step h3{margin:0 0 4px;font-size:15px}
.step p{margin:0;color:var(--muted);font-size:13.5px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.product{display:flex;flex-direction:column;gap:8px;padding:16px;border:1px solid var(--line);border-radius:10px;background:var(--card);text-decoration:none;transition:transform .12s,box-shadow .12s}
.product:hover{transform:translateY(-2px);box-shadow:0 8px 20px rgba(0,0,0,.14)}
.icon{width:30px;height:30px;border-radius:7px;display:grid;place-items:center;border:1.5px solid #151515}
.icon svg{width:17px;height:17px}
.product h3{margin:0;font-size:15px;font-weight:800}
.product p{margin:0;color:var(--muted);font-size:13.5px;line-height:1.45}
.compare{width:100%;border-collapse:separate;border-spacing:0;border:2px solid var(--line);border-radius:10px;overflow:hidden;background:var(--card);font-size:14px}
.compare th,.compare td{padding:11px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
.compare thead th{font-weight:800;background:var(--panel)}
.compare thead th.us{color:var(--red)}
.compare tbody tr:nth-child(even) td{background:var(--panel)}
.compare tbody tr:last-child td{border-bottom:0}
.compare td.c{text-align:center;width:22%}
.compare td.c svg{width:22px;height:22px;vertical-align:middle}
.compare td.c .txt{font-weight:600;font-size:13px}
.tscroll{overflow-x:auto}
.plain{width:100%;border-collapse:collapse;font-size:14px;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.plain th,.plain td{padding:9px 12px;border-bottom:1px solid var(--line);text-align:left}
.plain th{background:var(--panel);font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.plain td.n{font-family:var(--mono);text-align:right}
.plain tr:last-child td{border-bottom:0}
.up{color:#1E8A4C;font-weight:700}
.links{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(2,1fr);gap:8px 20px}
.links a{display:block;padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);text-decoration:none;font-weight:600}
.links a:hover{border-color:var(--red);color:var(--red)}
.links small{display:block;font-weight:400;color:var(--muted);font-size:12.5px}
.log{list-style:none;padding:0;margin:0;display:grid;gap:6px}
.log li{display:flex;gap:10px;align-items:baseline;padding:8px 12px;background:var(--card);border:1px solid var(--line);border-radius:8px;font-size:14px}
.log li::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--green);flex:none;position:relative;top:-1px}
.trash-item{display:grid;grid-template-columns:auto 1fr;gap:12px;padding:12px 14px;border:1px dashed var(--line);border-radius:10px;background:var(--card);margin-bottom:10px}
.trash-item .tag{font-family:var(--mono);font-size:11px;padding:2px 7px;border-radius:999px;background:#FDE7DC;color:#D93F00;font-weight:700;align-self:start}
.trash-item p{margin:4px 0 0;font-size:13.5px;color:var(--muted)}
.credit{position:fixed;bottom:12px;left:50%;transform:translateX(-50%);z-index:40;background:rgba(0,0,0,.45);color:#fff;padding:6px 14px;border-radius:999px;font-size:12.5px;font-weight:500;backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);white-space:nowrap}
.credit a{text-decoration:none;font-weight:700}
/* ---- responsive ---- */
@media (max-width:1100px){.stage{padding:28px 112px 72px}.stats{grid-template-columns:repeat(3,1fr)}.grid{grid-template-columns:repeat(2,1fr)}}
@media (max-width:900px){.stage{padding:16px 16px 72px}.icons{position:static;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:12px;margin:0 0 16px}.icons.right{margin-bottom:22px}.dicon{width:auto}.dicon svg{width:42px;height:42px}
.homegrid{grid-template-columns:1fr}.steps{grid-template-columns:repeat(2,1fr)}.steps::before{display:none}.menu{display:none}.wbody{padding:18px 16px 22px}.tabframe{padding:20px 16px}}
@media (max-width:600px){.stats{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.steps{grid-template-columns:1fr}.links{grid-template-columns:1fr}.mright .b3{padding:7px 10px;font-size:13px}.hero h1{font-size:34px}.credit{font-size:11.5px;white-space:normal;text-align:center;max-width:90vw}}
@media (prefers-reduced-motion:reduce){*{transition:none !important}}
"""

JS = """
(function(){
  var root=document.documentElement;root.className=root.className.replace('no-js','js');
  var KEY='ragprobe-site-theme';
  function stored(){try{return localStorage.getItem(KEY)}catch(e){return null}}
  function system(){return (window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light'}
  function current(){return root.getAttribute('data-theme')||stored()||system()}
  function apply(v){root.setAttribute('data-theme',v)}
  var saved=stored();if(saved==='dark'||saved==='light'){apply(saved)}
  var tb=document.getElementById('theme');
  if(tb){tb.addEventListener('click',function(){var next=current()==='dark'?'light':'dark';try{localStorage.setItem(KEY,next)}catch(e){}apply(next)})}

  var copy=document.getElementById('copy'),cmd=document.getElementById('install-cmd');
  if(copy&&cmd){copy.addEventListener('click',function(){var text=cmd.textContent;
    function done(){copy.textContent='Copied';copy.classList.add('done');setTimeout(function(){copy.textContent='Copy';copy.classList.remove('done')},1600)}
    function fallback(){var ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.left='-9999px';
      document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done()}catch(e){}document.body.removeChild(ta)}
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done,fallback)}else{fallback()}})}

  var tabs=[].slice.call(document.querySelectorAll('.tab'));
  tabs.forEach(function(t){t.addEventListener('click',function(){tabs.forEach(function(o){var on=o===t;o.setAttribute('aria-selected',String(on));
    var p=document.getElementById(o.getAttribute('aria-controls'));if(p){p.classList.toggle('active',on)}})})});

  var stage=document.getElementById('stage');var z=10,opened=0;
  function desktop(){return window.matchMedia('(min-width: 900px)').matches&&window.matchMedia('(pointer: fine)').matches}
  function raise(w){z+=1;w.style.zIndex=String(z)}
  function open(key){var w=document.getElementById('win-'+key);if(!w){return}
    if(!w.classList.contains('open')){w.classList.add('open');
      if(desktop()&&w.classList.contains('sub')&&!w.style.left){opened+=1;var k=opened%6;w.style.left=(90+k*28)+'px';w.style.top=(24+k*28)+'px'}}
    raise(w);if(!desktop()){w.scrollIntoView({behavior:'smooth',block:'start'})}
    var first=w.querySelector('.wtitle');if(first){w.setAttribute('tabindex','-1');w.focus({preventScroll:desktop()})}}
  document.addEventListener('click',function(e){
    var o=e.target.closest('[data-open]');if(o){e.preventDefault();open(o.getAttribute('data-open'));return}
    var c=e.target.closest('.wclose');if(c){var w=c.closest('.win');w.classList.remove('open','max');return}
    var m=e.target.closest('.wmax');if(m){var w2=m.closest('.win');w2.classList.toggle('max');raise(w2);return}
    var w3=e.target.closest('.win');if(w3){raise(w3)}});

  var drag=null;
  document.addEventListener('pointerdown',function(e){var bar=e.target.closest('.titlebar');if(!bar||e.target.closest('button')||!desktop()){return}
    var w=bar.closest('.win');if(w.classList.contains('max')){return}
    var r=w.getBoundingClientRect(),s=stage.getBoundingClientRect();
    if(!w.classList.contains('sub')&&!w.classList.contains('floating')){w.style.width=r.width+'px';w.classList.add('floating')}
    w.style.left=(r.left-s.left)+'px';w.style.top=(r.top-s.top)+'px';raise(w);
    drag={w:w,x:e.clientX,y:e.clientY,l:r.left-s.left,t:r.top-s.top};bar.setPointerCapture(e.pointerId);e.preventDefault()});
  document.addEventListener('pointermove',function(e){if(!drag){return}var l=drag.l+e.clientX-drag.x,t=drag.t+e.clientY-drag.y;
    drag.w.style.left=Math.max(-drag.w.offsetWidth+120,l)+'px';drag.w.style.top=Math.max(0,t)+'px'});
  document.addEventListener('pointerup',function(){drag=null});document.addEventListener('pointercancel',function(){drag=null});
  if(location.hash&&location.hash.indexOf('#win-')===0){open(location.hash.slice(5))}
})();
"""


# ---------------------------------------------------------------------------
# small pieces
# ---------------------------------------------------------------------------
def _mark(cls: str = "mark") -> str:
    return (
        '<span class="' + cls + '"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="#fff" stroke-width="2.4"/>'
        '<path d="M12.8 12.8L17 17" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/></svg></span>'
    )


def _check() -> str:
    return (
        '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="#36C46F"/>'
        '<path d="M7 12.5l3.2 3.2L17 9" fill="none" stroke="#151515" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


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


def _caret() -> str:
    return '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>'


# Desktop icon glyphs: a dark rounded square with a white line-art symbol.
_GLYPHS: Dict[str, str] = {
    "home": '<path d="M12 24L24 13l12 11"/><path d="M15 22v12h18V22"/><path d="M21 34v-7h6v7"/>',
    "gate": '<path d="M24 11l10 4v8c0 6-4.5 10-10 12-5.5-2-10-6-10-12v-8z"/><path d="M19 24l3.5 3.5L30 20"/>',
    "golden": '<path d="M13 15h22M13 24h22M13 33h14"/><circle cx="34" cy="33" r="3.5"/>',
    "metrics": '<path d="M13 35h22"/><path d="M17 30v-8M24 30V16M31 30v-5"/>',
    "docs": '<path d="M16 12h11l7 7v17H16z"/><path d="M27 12v7h7"/><path d="M20 26h8M20 31h8"/>',
    "author": '<circle cx="24" cy="19" r="6"/><path d="M13 36c1.5-7 6-10 11-10s9.5 3 11 10"/>',
    "about": '<circle cx="24" cy="24" r="12"/><path d="M24 22v9"/><circle cx="24" cy="17" r="1.4" fill="#fff" stroke="none"/>',
    "changelog": '<path d="M15 14h18v20H15z"/><path d="M19 20h10M19 25h10M19 30h6"/>',
    "casestudy": '<path d="M14 16h20v18H14z"/><path d="M14 22h20"/><path d="M19 27h10"/>',
    "examples": '<path d="M14 18l10-5 10 5-10 5z"/><path d="M14 18v12l10 5 10-5V18"/><path d="M24 23v12"/>',
    "hire": '<path d="M14 18h20v16H14z"/><path d="M20 18v-4h8v4"/><path d="M14 25h20"/>',
    "trash": '<path d="M15 17h18"/><path d="M20 17v-3h8v3"/><path d="M17 17l1.5 18h11L31 17"/><path d="M22 22v9M26 22v9"/>',
}


def _desktop_icon(key: str, label: str) -> str:
    if key == "demo":
        art = (
            '<svg viewBox="0 0 48 48" aria-hidden="true"><rect x="4" y="4" width="40" height="40" rx="10" fill="var(--icon)"/>'
            '<rect x="8" y="17" width="32" height="14" rx="4" fill="#F1A82C" stroke="#151515" stroke-width="1.5"/>'
            '<text x="24" y="27.5" text-anchor="middle" font-family="var(--font)" font-size="9.5" font-weight="900" fill="#151515" letter-spacing=".5">DEMO</text></svg>'
        )
    else:
        art = (
            '<svg viewBox="0 0 48 48" aria-hidden="true"><rect x="4" y="4" width="40" height="40" rx="10" fill="var(--icon)"/>'
            '<g fill="none" stroke="var(--icon-2)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' + _GLYPHS[key] + "</g></svg>"
        )
    return '<a class="dicon" href="#win-' + key + '" data-open="' + key + '">' + art + "<span>" + esc(label) + "</span></a>"


def _window(key: str, title: str, body: str, main: bool = False) -> str:
    cls = "win main-win open" if main else "win sub"
    return (
        '<section class="' + cls + '" id="win-' + key + '" aria-label="' + esc(title) + '">'
        '<div class="titlebar">' + _mark() + '<span class="wtitle">' + esc(title) + "</span>"
        '<span class="wctl"><button class="wmax" type="button" aria-label="Maximize window">'
        '<svg viewBox="0 0 12 12" aria-hidden="true"><rect x="1.5" y="1.5" width="9" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg></button>'
        '<button class="wclose" type="button" aria-label="Close window">'
        '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 2.5l7 7M9.5 2.5l-7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button></span>'
        '</div><div class="wbody">' + body + "</div></section>"
    )


def _terminal(title: str, lines: str) -> str:
    return (
        '<div class="terminal"><div class="tbar">'
        '<span class="dot" style="background:#F54E00"></span><span class="dot" style="background:#F9BD2B"></span><span class="dot" style="background:#36C46F"></span>'
        "<span>" + esc(title) + "</span></div><pre>" + lines + "</pre></div>"
    )


GATE_LINES = (
    '<span class="p">$</span> ragprobe run --html\n'
    '<span class="dim">16 cases, stub provider, 5 docs / 29 chunks -&gt; reports/results.json</span>\n'
    '<span class="p">$</span> ragprobe baseline\n'
    '<span class="dim">baseline -&gt; baselines/baseline.json (config a91f3c)</span>\n'
    '<span class="p">$</span> ragprobe diff --max-regressions 0\n'
    '<span class="ok">  improved </span> refund_window_annual      <span class="dim">0.71 -&gt; 0.93</span>\n'
    '<span class="bad">  REGRESSED</span> pricing_growth_tier       <span class="dim">0.92 -&gt; 0.43  forbidden term present</span>\n'
    '<span class="dim">  flat      14 cases</span>\n'
    '<span class="b">GATE FAILED</span>  regressed 1  improved 1  flat 14\n'
    '<span class="dim">exit 1</span>'
)


def stat_cell(value: str, label: str, tone: str = "y") -> str:
    return '<div class="stat ' + tone + '"><div class="v">' + esc(value) + '</div><div class="l">' + esc(label) + "</div></div>"


def render_stats(numbers: Dict[str, str], dashboard_href: Optional[str]) -> str:
    """The live numbers grid (the third tab of the main window)."""
    if not numbers:
        return (
            '<div class="stats">' + stat_cell("0", "runs recorded", "y") + "</div>"
            '<p class="bandnote">No runs recorded yet. The first push to main fills this in.</p>'
        )
    cells = [
        stat_cell(numbers["runs"], "runs recorded", "y"),
        stat_cell(numbers["cases"], "golden cases", "r"),
        stat_cell(numbers["pass_rate"], "latest pass rate", "b"),
        stat_cell(numbers["hit_rate"], "hit rate@" + numbers["k"], "g"),
        stat_cell(numbers["mrr"], "MRR", "p"),
    ]
    sub = (
        "<span>docs / chunks <b>" + esc(numbers["documents"]) + " / " + esc(numbers["chunks"]) + "</b></span>"
        "<span>categories <b>" + esc(numbers["categories"]) + "</b></span>"
        "<span>provider <b>" + esc(numbers["provider"]) + "</b></span>"
        "<span>latest run <b>" + esc(numbers["started_at"]) + "</b></span>"
    )
    note = "Every number comes from the latest recorded run on main."
    if dashboard_href:
        note += ' The <a href="' + esc(dashboard_href) + '">dashboard</a> reads the same history.'
    return '<div class="stats">' + "".join(cells) + '</div><div class="substats">' + sub + '</div><p class="bandnote">' + note + "</p>"


# ---------------------------------------------------------------------------
# page regions
# ---------------------------------------------------------------------------
def _menubar(dash_link: str, repo_url: str) -> str:
    links = [
        ("#win-home", "Product", "home"),
        ("#win-examples", "Examples", "examples"),
        ("#win-docs", "Docs", "docs"),
        (dash_link, "Dashboard", None),
        (repo_url, "GitHub", None),
        ("#win-about", "More", "about"),
    ]
    items = "".join(
        '<li><a href="' + esc(href) + '"' + (' data-open="' + key + '"' if key else "") + ">" + label + "</a></li>"
        for href, label, key in links
    )
    search = (
        '<span class="ibtn" role="img" aria-label="Search"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">'
        '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l5 5"/></svg></span>'
    )
    help_btn = (
        '<a class="ibtn" href="#win-docs" data-open="docs" aria-label="Help: open the docs"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">'
        '<circle cx="12" cy="12" r="9.5"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7"/><circle cx="12" cy="17" r=".6" fill="currentColor"/></svg></a>'
    )
    account = (
        '<a class="ibtn" href="' + esc(repo_url + "/graphs/contributors") + '" aria-label="Author"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">'
        '<circle cx="12" cy="9" r="4"/><path d="M4.5 20c1-4 4-6 7.5-6s6.5 2 7.5 6"/></svg></a>'
    )
    theme = (
        '<button class="ibtn" id="theme" type="button" aria-label="Toggle dark mode">'
        '<svg class="moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>'
        '<svg class="sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" stroke-width="2"/>'
        '<path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button>'
    )
    return (
        '<header class="menubar"><a class="logo" href="./">' + _mark() + "RAGProbe</a>"
        '<ul class="menu">' + items + "</ul>"
        '<div class="mright"><a class="b3 sm" href="' + esc(repo_url) + '">Get started &ndash; free</a>'
        + search + help_btn + account + theme + "</div></header>"
    )


def _home_body(numbers: Dict[str, str], dashboard_href: Optional[str], readme: str, repo_url: str) -> str:
    setup = (
        '<aside class="setup"><h2>' + _mark() + "Set up RAGProbe for free</h2><ul>"
        "<li>" + _check() + "No API key required</li>"
        "<li>" + _check() + "Runs offline in CI &mdash; 370+ tests</li>"
        "<li>" + _check() + "One dependency: PyYAML</li></ul>"
        '<a class="b3 full" href="' + esc(repo_url) + '">Get started</a>'
        '<a class="b3 white full" href="' + esc(readme) + '">Read the docs</a>'
        '<div class="install"><code id="install-cmd">' + esc(INSTALL) + '</code><button id="copy" type="button" aria-label="Copy install command">Copy</button></div>'
        "</aside>"
    )
    hero = (
        '<div class="hero"><h1>Catch RAG regressions before they ship.</h1>'
        '<p class="lead">A golden dataset, retrieval and answer scoring, a baseline, and a diff that fails CI when a prompt or chunking change makes a case worse.</p>'
        '<p class="fine">Open source &middot; MIT &middot; deterministic stub provider &middot; PyYAML is the only dependency</p></div>'
    )
    tab1 = (
        '<div class="centered">' + _mark() + "<h2>Three commands, one gate</h2>"
        '<div class="askbox">' + _terminal("ragprobe diff", GATE_LINES)
        + '<div class="askfoot"><span class="chip">stub &middot; deterministic' + _caret() + '</span><span class="chip">Python 3.9+' + _caret() + "</span>"
        '<a class="arrow" href="' + esc(readme) + '" aria-label="Open the README"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M6 11l6-6 6 6"/></svg></a>'
        "</div></div></div>"
    )
    tab2 = (
        '<div class="centered">' + _mark() + "<h2>Point it at your RAG</h2>"
        '<div class="askbox"><span class="ctx">@ Add a target</span>'
        "<pre><code>ragprobe run --target http://localhost:8000/ask\nragprobe run --target myapp.rag:answer</code></pre>"
        '<p class="placeholder">RAGProbe POSTs <code>{&quot;question&quot;: &quot;...&quot;}</code> and reads this back. Only <code>answer</code> is required; return <code>contexts</code> with stable chunk ids to get retrieval metrics.</p>'
        "<pre><code>{&quot;answer&quot;:   &quot;Full-time employees get 20 days.&quot;,\n"
        " &quot;contexts&quot;: [{&quot;id&quot;: &quot;handbook#paid-time-off&quot;, &quot;text&quot;: &quot;...&quot;, &quot;score&quot;: 0.81}],\n"
        " &quot;refused&quot;:  false}</code></pre>"
        '<div class="askfoot"><span class="chip">HTTP or Python entry point' + _caret() + '</span><span class="chip">same golden set, same gate' + _caret() + "</span>"
        '<a class="arrow" href="#win-examples" data-open="examples" aria-label="Open the examples"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M6 11l6-6 6 6"/></svg></a>'
        "</div></div></div>"
    )
    tab3 = (
        '<div class="centered">' + _mark() + "<h2>Live from the latest run on main</h2>"
        + render_stats(numbers, dashboard_href) + "</div>"
    )
    tabs = (
        '<div class="tabs" role="tablist" aria-label="What RAGProbe does">'
        '<button class="tab" role="tab" id="tab-gate" aria-controls="panel-gate" aria-selected="true" type="button">Run the gate</button>'
        '<button class="tab" role="tab" id="tab-target" aria-controls="panel-target" aria-selected="false" type="button">Point it at your RAG</button>'
        '<button class="tab" role="tab" id="tab-numbers" aria-controls="panel-numbers" aria-selected="false" type="button">See the numbers</button>'
        "</div>"
        '<div class="tabframe">'
        '<div class="tabpanel active" role="tabpanel" id="panel-gate" aria-labelledby="tab-gate">' + tab1 + "</div>"
        '<div class="tabpanel" role="tabpanel" id="panel-target" aria-labelledby="tab-target">' + tab2 + "</div>"
        '<div class="tabpanel" role="tabpanel" id="panel-numbers" aria-labelledby="tab-numbers">' + tab3 + "</div>"
        "</div>"
    )
    return '<div class="homegrid">' + hero + setup + "</div>" + tabs


def _svg_icon(kind: str) -> str:
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


def _metrics_body(repo_url: str, dash_link: str) -> str:
    cards = [
        ("dataset", "#1D4AFF", "#fff", "Golden dataset", "Questions with expected chunks, required and forbidden keywords and refusal rules, in one YAML file next to the code.", repo_url + "#the-golden-dataset"),
        ("metrics", "#F54E00", "#fff", "Retrieval metrics", "<code>precision@k</code>, <code>recall@k</code>, hit rate and MRR, computed the strict way: precision divides by k and an undefined metric is <code>null</code>.", repo_url + "#retrieval-metrics"),
        ("evaluators", "#36C46F", "#151515", "Answer evaluators", "Keyword presence, forbidden terms, refusal in both directions, citation validity and an offline grounding check. The LLM judge is advisory.", repo_url + "#answer-quality-evaluators"),
        ("gate", "#F9BD2B", "#151515", "Regression gate", "<code>ragprobe diff</code> classifies every case as regressed, degraded, improved, flat, new or removed and exits 1 when the gate fails.", repo_url + "#the-regression-workflow"),
        ("history", "#B62AD9", "#fff", "History &amp; dashboard", "Every run is appended to a history store. The dashboard plots trends, marks config changes and attributes failures to retrieval or generation.", dash_link),
        ("offline", "#151515", "#fff", "Runs offline in CI", "A deterministic stub provider means the same input gives the same output on any machine. No key, no network, no flaky baseline.", repo_url + "#continuous-integration"),
    ]
    out = []
    for kind, bg, fg, title, body, href in cards:
        out.append(
            '<a class="product" href="' + esc(href) + '"><span class="icon" style="background:' + bg + ";color:" + fg + '">'
            + _svg_icon(kind) + "</span><h3>" + title + "</h3><p>" + body + "</p></a>"
        )
    return '<p class="muted">Six pieces, one package. Each writes to the same history.</p><div class="grid">' + "".join(out) + "</div>"


def _gate_body(repo_url: str) -> str:
    steps = [
        ("Write cases", "Describe a good answer in <code>golden_set.yaml</code>: expected chunks, keywords, refusals."),
        ("<code>ragprobe run</code>", "Ingest the corpus, answer every case, score retrieval and answers, append the run to history."),
        ("<code>ragprobe baseline</code>", "Promote the current behaviour to the regression contract and commit the file."),
        ("<code>ragprobe diff</code>", "Re-run after every change. A regressed case fails CI with exit code 1."),
    ]
    items = "".join(
        '<li class="step"><span class="num">' + str(i + 1) + "</span><h3>" + title + "</h3><p>" + body + "</p></li>"
        for i, (title, body) in enumerate(steps)
    )
    return (
        '<p class="muted">The same workflow as unit tests: write the expectation, record the baseline, fail the build on regression. '
        'Exit codes mean something: <code>0</code> passed, <code>1</code> a gate failed, <code>2</code> usage error.</p>'
        '<ol class="steps">' + items + "</ol>" + _terminal("ci - ragprobe diff", GATE_LINES)
        + '<p style="margin-top:14px"><a href="' + esc(repo_url + "#the-regression-workflow") + '">Read the regression workflow &rarr;</a></p>'
    )


def _golden_body(repo_url: str) -> str:
    yaml = (
        "cases:\n"
        "  - id: pto-annual-allowance\n"
        "    category: hr-policy\n"
        "    question: How many days of paid time off do full-time employees get?\n"
        "    expected_chunks: [employee_handbook#paid-time-off]\n"
        "    required_keywords: [&quot;20 days&quot;]\n"
        "    expected_answer: Full-time employees accrue 20 days of PTO per year.\n"
        "  - id: remote-onsite-days\n"
        "    category: hr-policy\n"
        "    question: How many days per week are employees expected on site?\n"
        "    expected_chunks: [employee_handbook#remote-work]\n"
        "    forbidden_keywords: [&quot;fully remote&quot;]"
    )
    return (
        "<p>A golden set is the regression contract in one YAML file. Every non-refusal case names the chunk ids that genuinely contain the answer; "
        "those drive precision@k, recall@k, hit rate and MRR. Chunk ids are heading anchors (<code>doc#slug</code>), so they survive re-chunking.</p>"
        "<p>Cases can also require or forbid keywords, demand a refusal, and give a reference answer for the advisory judge.</p>"
        "<pre><code>" + yaml + "</code></pre>"
        '<p><a href="' + esc(repo_url + "/blob/main/datasets/golden_set.yaml") + '">The shipped golden set (16 cases) &rarr;</a></p>'
    )


def _docs_body(repo_url: str, dash_link: str, report_href: Optional[str]) -> str:
    links = [
        (repo_url + "#quickstart", "Quickstart", "Three commands, no API key"),
        (repo_url + "#the-regression-workflow", "Regression workflow", "run, baseline, diff, exit codes"),
        (repo_url + "#retrieval-metrics", "Retrieval metrics", "precision@k, recall@k, hit rate, MRR"),
        (repo_url + "#answer-quality-evaluators", "Answer evaluators", "keywords, refusals, citations, grounding"),
        (repo_url + "#known-weaknesses-of-llm-as-judge", "LLM-as-judge caveats", "why the judge is advisory"),
        (repo_url + "#cli-reference", "CLI reference", "every command and flag"),
        (repo_url + "#dashboard", "Dashboard", "trends, breakdowns, insights"),
        (dash_link, "Live dashboard", "rendered from the run history"),
    ]
    if report_href:
        links.append((report_href, "Latest HTML report", "the newest run, case by case"))
    return (
        '<ul class="links">'
        + "".join('<li><a href="' + esc(h) + '">' + esc(t) + "<small>" + esc(s) + "</small></a></li>" for h, t, s in links)
        + "</ul>"
    )


def _demo_body(repo_url: str) -> str:
    return (
        '<p class="muted">What CI prints when a prompt change breaks a case: the shape of <code>ragprobe diff</code> output for the shipped golden set.</p>'
        + _terminal("demo - ragprobe diff", GATE_LINES)
        + '<p style="margin-top:14px"><a href="' + esc(repo_url + "#quickstart") + '">Run it yourself in three commands &rarr;</a></p>'
    )


def _author_body(repo_url: str) -> str:
    return (
        "<p>RAGProbe is built and maintained by Khushi Jain. Questions, bug reports and ideas are welcome on the repository; "
        "issues get answered, and pull requests that come with a test get merged.</p>"
        '<ul><li><a href="' + esc(repo_url + "/issues") + '">Open an issue</a></li>'
        '<li><a href="' + esc(repo_url + "/graphs/contributors") + '">Khushi Jain on GitHub</a></li></ul>'
    )


def _about_body() -> str:
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

    body = "".join('<tr><td>' + label + "</td>" + cell(a) + cell(b) + cell(c) + "</tr>" for label, a, b, c in rows)
    body += (
        '<tr><td>Cost</td><td class="c"><span class="txt">Free, MIT</span></td>'
        '<td class="c"><span class="txt">Your afternoon, every time</span></td>'
        '<td class="c"><span class="txt">Per seat, per month</span></td></tr>'
    )
    return (
        "<p>Prompt changes are code changes, but most RAG systems are tested by re-reading answers in a notebook, or by paying for an eval product "
        "that needs a key, a network and a budget. RAGProbe is the third option: a golden set and a diff that run offline, deterministically, "
        "and fail the build when a case gets worse.</p>"
        '<div class="tscroll"><table class="compare"><thead><tr><th></th><th class="us">RAGProbe</th><th>Eyeballing in a notebook</th><th>Paid eval SaaS</th></tr></thead>'
        "<tbody>" + body + "</tbody></table></div>"
    )


def _changelog_body(changelog: List[str], repo_url: str) -> str:
    if changelog:
        items = "".join("<li>" + esc(subject) + "</li>" for subject in changelog[:6])
        body = '<ul class="log">' + items + "</ul>"
    else:
        body = '<p class="muted">No git history was available when this page was built.</p>'
    return body + '<p style="margin-top:14px"><a href="' + esc(repo_url + "/commits/main") + '">Full history on GitHub &rarr;</a></p>'


def _casestudy_body() -> str:
    return (
        "<p>A documentation assistant over the Playwright guides, evaluated with the same golden set before and after swapping the retriever "
        "from TF-IDF to the bge-small embedding model.</p>"
        '<p class="muted">Numbers land here once the live run finishes.</p>'
        '<div class="tscroll"><table class="plain"><thead><tr><th>Metric</th><th>TF-IDF</th><th>bge-small</th><th>Change</th></tr></thead><tbody>'
        '<tr><td>hit rate@3</td><td class="n">0.603</td><td class="n">0.707</td><td class="n up">+0.104</td></tr>'
        '<tr><td>MRR</td><td class="n">0.537</td><td class="n">0.592</td><td class="n up">+0.055</td></tr>'
        '<tr><td>recall@3</td><td class="n">0.586</td><td class="n">0.655</td><td class="n up">+0.069</td></tr>'
        "</tbody></table></div>"
    )


def _examples_body(repo_url: str) -> str:
    items = [
        ("langchain_target.py", "LangChain retriever + chat model, wrapped as a class the harness calls per question."),
        ("llamaindex_target.py", "A LlamaIndex query engine exposed as a single <code>answer()</code> function."),
        ("fastapi_service.py", "Any service behind HTTP: <code>uvicorn fastapi_service:app</code>, then point <code>--target</code> at the URL."),
    ]
    return (
        "<p>Each example is a complete target. Copy the one closest to your stack next to your code and run "
        "<code>ragprobe run --target &lt;module&gt;:&lt;name&gt;</code>. None of these frameworks is a RAGProbe dependency.</p>"
        "<ul>" + "".join("<li><code>" + esc(name) + "</code> &mdash; " + text + "</li>" for name, text in items) + "</ul>"
        '<p><a href="' + esc(repo_url + "/tree/main/examples") + '">Browse the examples &rarr;</a></p>'
    )


def _hire_body(repo_url: str) -> str:
    return (
        "<p><strong>Open to SDET / QA automation roles.</strong> RAGProbe is the kind of work involved: a test harness with a strict metric "
        "implementation, deterministic fixtures, a CI gate with meaningful exit codes and 370+ tests that check the checker.</p>"
        '<ul><li><a href="' + esc(repo_url + "/graphs/contributors") + '">Khushi Jain on GitHub</a></li>'
        '<li><a href="' + esc(repo_url) + '">This repository</a></li></ul>'
    )


def _trash_body() -> str:
    return (
        "<p><strong>Not deleted. Kept as documented failures.</strong> Two golden cases fail on the shipped configuration on purpose: "
        "they are real defects the harness found in its own pipeline, and a golden set that is green on day one is usually not asserting anything.</p>"
        '<div class="trash-item"><span class="tag">known_failure</span><div><strong>Perfect retrieval, wrong answer</strong>'
        "<p>Every expected chunk came back at rank one; the answer still named the wrong plan tier. Attribution: generation.</p></div></div>"
        '<div class="trash-item"><span class="tag">known_failure</span><div><strong>Sentence selection inside the right chunk</strong>'
        "<p>Retrieval found the chunk; the extractive answer picked the neighbouring sentence. The case stays so the fix can be measured.</p></div></div>"
        '<p class="muted">Deleting a failing case does not help either: <code>ragprobe diff</code> counts it as removed and the gate fails.</p>'
    )


def render(
    numbers: Dict[str, str],
    dashboard_href: Optional[str],
    report_href: Optional[str],
    repo_url: str,
    title: str = TITLE,
    changelog: Optional[List[str]] = None,
) -> str:
    """The whole page as one self-contained HTML string."""
    dash_link = dashboard_href or (repo_url + "#dashboard")
    readme = repo_url + "#readme"
    changelog = list(changelog or [])

    bodies: Dict[str, Tuple[str, str]] = {
        "gate": ("The regression gate", _gate_body(repo_url)),
        "golden": ("Golden sets", _golden_body(repo_url)),
        "metrics": ("Metrics", _metrics_body(repo_url, dash_link)),
        "docs": ("Docs", _docs_body(repo_url, dash_link, report_href)),
        "demo": ("Demo", _demo_body(repo_url)),
        "author": ("Talk to the author", _author_body(repo_url)),
        "about": ("About RAGProbe", _about_body()),
        "changelog": ("Changelog", _changelog_body(changelog, repo_url)),
        "casestudy": ("Case study: a docs assistant over the Playwright guides", _casestudy_body()),
        "examples": ("Examples", _examples_body(repo_url)),
        "hire": ("Hire me", _hire_body(repo_url)),
        "trash": ("Trash", _trash_body()),
    }
    windows = [_window("home", title + " - " + TAGLINE, _home_body(numbers, dashboard_href, readme, repo_url), main=True)]
    for key in WINDOW_KEYS:
        if key == "home":
            continue
        heading, body = bodies[key]
        windows.append(_window(key, heading, body))

    css = CSS.replace("TILE_LIGHT", LIGHT_TILE).replace("TILE_DARK", DARK_TILE)
    parts: List[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en" class="no-js"><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append("<title>" + esc(title) + " - " + esc(TAGLINE) + "</title>")
    parts.append('<meta name="description" content="' + esc(title + ": an evaluation and regression-testing harness for RAG pipelines. Golden dataset, retrieval metrics, answer evaluators and a CI gate that fails on regression.") + '">')
    parts.append("<style>" + css + "</style></head><body>")
    parts.append(_menubar(dash_link, repo_url))
    parts.append('<main class="stage" id="stage">')
    parts.append('<nav class="icons left" aria-label="Desktop">' + "".join(_desktop_icon(k, l) for k, l in LEFT_ICONS) + "</nav>")
    parts.append('<nav class="icons right" aria-label="More">' + "".join(_desktop_icon(k, l) for k, l in RIGHT_ICONS) + "</nav>")
    parts.extend(windows)
    parts.append("</main>")
    parts.append('<div class="credit">MIT licensed &middot; Built by Khushi Jain &middot; <a href="' + esc(repo_url) + '">GitHub</a></div>')
    parts.append("<script>" + JS + "</script></body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------
def build(
    history_dir: Path,
    out: Path,
    dashboard: Optional[str],
    report: Optional[str],
    repo_url: str,
    changelog: Optional[List[str]] = None,
) -> Path:
    """Render the page to ``out`` and return the path.

    ``dashboard`` and ``report`` are hrefs relative to the page. They are only
    linked when the target file exists next to the page (or when it is an
    absolute URL), so a site published without a dashboard has no dead link.
    ``changelog`` is an optional list of recent commit subjects for the
    Changelog window; omit it and the window says so.
    """
    runs = load_runs(history_dir)
    numbers = stats(runs)

    def usable(href: Optional[str]) -> Optional[str]:
        if not href:
            return None
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return href if (out.parent / href).is_file() else None

    page = render(numbers, usable(dashboard), usable(report), repo_url, changelog=changelog)
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
    parser.add_argument("--no-changelog", action="store_true", help="do not read recent commits from git")
    args = parser.parse_args(argv)

    changelog = [] if args.no_changelog else recent_commits()
    out = build(Path(args.history_dir), Path(args.out), args.dashboard, args.report, args.repo_url, changelog=changelog)
    runs = len(load_runs(Path(args.history_dir)))
    print("site -> " + str(out) + " (" + str(runs) + " run(s) in history)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
