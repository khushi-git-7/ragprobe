"""A self-contained HTML security report.

One file, no external assets, no CDN, no network - so it opens offline from a CI
artifact, an email attachment or a published page, in light or dark theme. It
renders what a reader needs to grasp a security run at a glance: an A-F scorecard
per OWASP category, how each defence changes the attack-success rate, and the
per-attack detail with which defence layer stopped what.

Plain string building, no template engine, to keep the base install dependency-free
(the same choice the quality report makes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping

from ragprobe.security.attacks import OWASP
from ragprobe.security.report import GRADE_BANDS, scorecard

GRADE_TONE = {"A": "pass", "B": "pass", "C": "warn", "D": "fail", "F": "fail"}

_CSS = """
:root {
  --bg:#f6f7f9; --surface:#fff; --surface-2:#f0f2f5; --border:#d9dde3;
  --text:#16191d; --text-dim:#5c6570; --accent:#2f5bd7;
  --pass:#1a7f4b; --pass-bg:#e6f4ec; --fail:#c0392b; --fail-bg:#fbeaea;
  --warn:#9a6700; --warn-bg:#fff6e0; --flat:#6b7280; --track:#e4e8ee;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --bg:#0f1216; --surface:#171b21; --surface-2:#1e242c; --border:#2b323b;
  --text:#e6e9ed; --text-dim:#9aa4b1; --accent:#7ea2ff;
  --pass:#4ade80; --pass-bg:#13301f; --fail:#f87171; --fail-bg:#331616;
  --warn:#fbbf24; --warn-bg:#332813; --flat:#9aa4b1; --track:#232b34; }}
:root[data-theme="dark"]{
  --bg:#0f1216; --surface:#171b21; --surface-2:#1e242c; --border:#2b323b;
  --text:#e6e9ed; --text-dim:#9aa4b1; --accent:#7ea2ff;
  --pass:#4ade80; --pass-bg:#13301f; --fail:#f87171; --fail-bg:#331616;
  --warn:#fbbf24; --warn-bg:#332813; --flat:#9aa4b1; --track:#232b34; }
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:15px;line-height:1.55}
.wrap{max-width:960px;margin:0 auto;padding:32px 16px 80px}
h1{font-size:26px;margin:0 0 4px} h2{font-size:18px;margin:36px 0 12px}
.sub{color:var(--text-dim);margin:0 0 8px}
.banner{background:var(--warn-bg);border:1px solid var(--border);border-radius:10px;
  padding:12px 16px;margin:16px 0;color:var(--text);font-size:14px}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:14px 16px;min-width:150px;flex:1}
.card .k{color:var(--text-dim);font-size:13px} .card .v{font-size:24px;font-weight:650;margin-top:2px}
table{width:100%;border-collapse:collapse;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;overflow:hidden;margin:8px 0}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);font-size:14px}
th{background:var(--surface-2);font-weight:600} tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.grade{display:inline-block;min-width:26px;text-align:center;font-weight:800;
  border-radius:7px;padding:2px 8px}
.grade.pass{background:var(--pass-bg);color:var(--pass)} .grade.warn{background:var(--warn-bg);color:var(--warn)}
.grade.fail{background:var(--fail-bg);color:var(--fail)}
.bar{position:relative;background:var(--track);border-radius:6px;height:22px;min-width:120px}
.bar>span{position:absolute;left:0;top:0;bottom:0;border-radius:6px;background:var(--accent)}
.bar.good>span{background:var(--pass)} .bar.bad>span{background:var(--fail)} .bar.mid>span{background:var(--warn)}
.bar em{position:absolute;right:6px;top:0;line-height:22px;font-style:normal;font-size:12px;color:var(--text)}
code,.mono{font-family:var(--mono)}
.foot{color:var(--text-dim);font-size:13px;margin-top:40px;border-top:1px solid var(--border);padding-top:12px}
.pill{font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid var(--border);color:var(--text-dim)}
"""

_THEME_JS = """
(function(){try{var t=localStorage.getItem('ragprobe-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();
"""


def esc(text: Any) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _pct(x: float) -> str:
    return f"{x*100:.0f}%"


def _bar(fraction: float, tone: str = "") -> str:
    width = max(0.0, min(1.0, fraction)) * 100
    cls = {"good": "good", "bad": "bad", "mid": "mid"}.get(tone, "")
    return (f'<div class="bar {cls}"><span style="width:{width:.0f}%"></span>'
            f'<em>{_pct(fraction)}</em></div>')


def render(results: Mapping[str, Any], title: str = "RAGProbe security report") -> str:
    victim = results["victim"]
    summary = results["summary"]
    by_defense: Dict[str, Any] = summary["by_defense"]
    card = scorecard(results)

    parts: List[str] = []
    parts.append(f"<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    parts.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    parts.append(f"<title>{esc(title)}</title><style>{_CSS}</style>")
    parts.append(f"<script>{_THEME_JS}</script></head><body><div class='wrap'>")

    parts.append(f"<h1>{esc(title)}</h1>")
    parts.append(f"<p class='sub'>Victim <code>{esc(victim['name'])}</code>"
                 f"{' (' + esc(victim['model']) + ')' if victim.get('model') else ''} "
                 f"&middot; {results['attack_count']} attacks "
                 f"&middot; corpus <code>{esc(results['attack_corpus'])}</code> "
                 f"&middot; seed {esc(results['seed'])}</p>")
    if victim.get("deterministic"):
        parts.append("<div class='banner'><b>Simulated worst-case victim.</b> These "
                     "rates come from a model that obeys every instruction it can parse. "
                     "They are a deterministic check of the harness and the code-level "
                     "defences, not a measurement of any real model.</div>")

    # KPI cards: best/worst defence.
    best = min(by_defense.items(), key=lambda kv: kv[1]["asr"])
    worst = max(by_defense.items(), key=lambda kv: kv[1]["asr"])
    parts.append("<div class='cards'>")
    parts.append(f"<div class='card'><div class='k'>Attack-success, no defence</div>"
                 f"<div class='v'>{_pct(worst[1]['asr'])}</div></div>")
    parts.append(f"<div class='card'><div class='k'>Best defence (<code>{esc(best[0])}</code>)</div>"
                 f"<div class='v'>{_pct(best[1]['asr'])}</div></div>")
    reduction = worst[1]["asr"] - best[1]["asr"]
    parts.append(f"<div class='card'><div class='k'>Reduction</div>"
                 f"<div class='v'>{_pct(reduction)}</div></div>")
    parts.append("</div>")

    # Scorecard.
    parts.append(f"<h2>OWASP scorecard &mdash; defence <code>{esc(card['defense'])}</code></h2>")
    parts.append("<table><tr><th>OWASP</th><th>Risk</th><th class='num'>Undefended</th>"
                 "<th class='num'>Defended</th><th>Grade</th></tr>")
    for row in card["rows"]:
        tone = GRADE_TONE.get(row["grade"], "flat")
        undef = _pct(row["asr_undefended"]) if row["asr_undefended"] is not None else "&ndash;"
        parts.append(f"<tr><td><code>{esc(row['owasp'])}</code></td><td>{esc(row['name'])}</td>"
                     f"<td class='num'>{undef}</td><td class='num'>{_pct(row['asr_defended'])}</td>"
                     f"<td><span class='grade {tone}'>{esc(row['grade'])}</span></td></tr>")
    parts.append("</table>")

    # Defences compared, with bars.
    parts.append("<h2>Defences compared</h2>")
    parts.append("<table><tr><th>Defence</th><th>Attack-success rate</th>"
                 "<th class='num'>95% CI</th><th class='num'>Utility kept</th>"
                 "<th class='num'>Blocked early</th></tr>")
    for name, block in by_defense.items():
        tone = "good" if block["asr"] <= 0.2 else "bad" if block["asr"] >= 0.6 else "mid"
        ci = f"{block['asr_ci95'][0]*100:.0f}&ndash;{block['asr_ci95'][1]*100:.0f}"
        util = "&ndash;" if block["utility_ok_rate"] is None else _pct(block["utility_ok_rate"])
        parts.append(f"<tr><td><code>{esc(name)}</code></td><td>{_bar(block['asr'], tone)}</td>"
                     f"<td class='num'>{ci}</td><td class='num'>{util}</td>"
                     f"<td class='num'>{block['blocked_pre']}/{block['trials']}</td></tr>")
    parts.append("</table>")

    # Per-attack detail for the first and last defence (none vs best, if present).
    detail = results.get("trials_detail") or []
    show_defs = []
    if "none" in by_defense:
        show_defs.append("none")
    if best[0] not in show_defs:
        show_defs.append(best[0])
    for dname in show_defs:
        rows = [t for t in detail if t["defense"] == dname]
        if not rows:
            continue
        parts.append(f"<h2>Attacks under <code>{esc(dname)}</code></h2>")
        parts.append("<table><tr><th>Attack</th><th>OWASP</th><th>Scenario</th>"
                     "<th>Result</th><th>Stopped by</th></tr>")
        for t in rows:
            succeeded = t["success"]
            tone = "fail" if succeeded else "pass"
            label = "attack succeeded" if succeeded else "blocked / resisted"
            events = ", ".join(sorted({e["defense"] for e in t.get("defense_events", [])})) or "&ndash;"
            parts.append(f"<tr><td class='mono'>{esc(t['attack_id'])}</td>"
                         f"<td><code>{esc(t['owasp'])}</code></td><td>{esc(t['scenario'])}</td>"
                         f"<td><span class='grade {tone}'>{label}</span></td>"
                         f"<td>{esc(events)}</td></tr>")
        parts.append("</table>")

    parts.append(f"<p class='foot'>Generated by RAGProbe &middot; "
                 f"{esc(results.get('created',''))} &middot; "
                 f"<span class='pill'>{esc(results.get('kind','security'))}</span></p>")
    parts.append("</div></body></html>")
    return "".join(parts)


def write_report(results: Mapping[str, Any], out_path: Path,
                 title: str = "RAGProbe security report") -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(results, title=title), encoding="utf-8")
    return out_path
