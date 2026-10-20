"""A self-contained HTML security report, in the site's dark product style.

One file, no external assets, no CDN, no network - so it opens offline from a CI
artifact, an email attachment or the published page, in light or dark theme. It
shares the landing page's look: a headline stat, an A-F OWASP scorecard as
grade-badge cards with meters, the attack-success rate per defence as bars, and
the per-attack detail with which defence layer stopped what. Plain string
building, no template engine, to keep the base install dependency-free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping

from ragprobe.security.attacks import OWASP
from ragprobe.security.report import scorecard

GRADE_TONE = {"A": "pass", "B": "pass", "C": "warn", "D": "fail", "F": "fail"}

_CSS = """
:root{--bg:#07090d;--panel:#0e1219;--panel-2:#121823;--border:#1c2430;--border-2:#273243;
--ink:#eef2f8;--muted:#9aa6b6;--faint:#5f6b7c;--accent:#ff5a1f;--accent-2:#ffb547;--glow:rgba(255,90,31,.35);
--good:#38e08a;--warn:#ffb547;--bad:#ff5a6a;--track:#161d28;
--font:"Inter","Segoe UI",system-ui,-apple-system,sans-serif;--mono:"JetBrains Mono","SF Mono","Consolas",monospace;color-scheme:dark}
:root[data-theme="light"]{--bg:#f5f6f8;--panel:#fff;--panel-2:#f6f7f9;--border:#e3e6ea;--border-2:#d5d9df;
--ink:#101418;--muted:#55606d;--faint:#8b95a1;--accent:#e5490f;--accent-2:#d98300;--glow:rgba(229,73,15,.18);
--good:#15a35b;--warn:#c67b00;--bad:#e5484d;--track:#e9eaee;color-scheme:light}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}
.bgfx{position:fixed;inset:0;z-index:-1;pointer-events:none;background:radial-gradient(800px 440px at 72% -10%,var(--glow),transparent 60%)}
.wrap{max-width:960px;margin:0 auto;padding:0 20px 80px}
h1,h2{letter-spacing:-.02em;margin:0;font-weight:800}h2{font-size:20px;margin:40px 0 6px}
.mono,code{font-family:var(--mono)}
.muted{color:var(--muted);font-size:14px;margin:4px 0 14px}
.hero{margin:26px 0 8px;border:1px solid var(--border-2);border-radius:22px;padding:28px;position:relative;overflow:hidden;
  background:linear-gradient(180deg,var(--panel),var(--panel-2))}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-weight:600}
.hero h1{font-size:26px;margin:10px 0 8px}
.bigstat{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-top:14px}
.bigstat .from{font-size:34px;font-weight:800;color:var(--bad);text-decoration:line-through;opacity:.7}
.bigstat .arr{color:var(--faint);font-size:22px}.bigstat .to{font-size:52px;font-weight:850;letter-spacing:-.03em;color:var(--good)}
.bigstat .cap{font-size:13px;color:var(--muted);align-self:center;max-width:220px}
.banner{background:var(--panel-2);border:1px solid var(--border);border-left:3px solid var(--warn);border-radius:0 10px 10px 0;padding:12px 15px;margin:16px 0;font-size:13.5px;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:16px 0}
.stat{border:1px solid var(--border);border-radius:16px;background:linear-gradient(180deg,var(--panel),var(--panel-2));padding:16px 18px}
.stat .k{color:var(--faint);font-size:11.5px;font-family:var(--mono);text-transform:uppercase;letter-spacing:.04em}
.stat .v{font-size:30px;font-weight:850;margin-top:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
.risk{border:1px solid var(--border);border-radius:16px;background:linear-gradient(180deg,var(--panel),var(--panel-2));padding:18px;transition:transform .16s,border-color .16s}
.risk:hover{transform:translateY(-4px);border-color:var(--accent)}
.risk .r1{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.risk .nm{font-weight:700;font-size:14.5px}.risk .cd{color:var(--faint);font-size:11.5px;font-family:var(--mono);margin-top:3px}
.gr{width:46px;height:46px;border-radius:13px;display:grid;place-items:center;font-weight:850;font-size:22px;flex:none}
.gr.pass{background:rgba(56,224,138,.14);color:var(--good);border:1px solid rgba(56,224,138,.3)}
.gr.warn{background:rgba(255,181,71,.14);color:var(--warn);border:1px solid rgba(255,181,71,.3)}
.gr.fail{background:rgba(255,90,106,.14);color:var(--bad);border:1px solid rgba(255,90,106,.3)}
.risk .meter{margin-top:14px;height:7px;border-radius:999px;background:var(--track);overflow:hidden}
.risk .meter i{display:block;height:100%;border-radius:999px}
.risk .ms{display:flex;justify-content:space-between;font-size:11.5px;color:var(--faint);margin-top:7px;font-family:var(--mono)}
table{width:100%;border-collapse:collapse;background:linear-gradient(180deg,var(--panel),var(--panel-2));border:1px solid var(--border);border-radius:16px;overflow:hidden;margin:8px 0}
th,td{padding:11px 14px;text-align:left;border-bottom:1px solid var(--border);font-size:14px}
th{font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:var(--faint);font-weight:700}
tr:last-child td{border-bottom:none}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.bar{position:relative;background:var(--track);border-radius:999px;height:24px;min-width:150px;overflow:hidden}
.bar>span{position:absolute;inset:0 auto 0 0;border-radius:999px}
.bar.good>span{background:linear-gradient(90deg,var(--good),#9ff5c6)}.bar.bad>span{background:linear-gradient(90deg,var(--bad),#ffab7a)}.bar.mid>span{background:linear-gradient(90deg,var(--warn),#ffd98a)}
.bar em{position:absolute;right:10px;top:0;line-height:24px;font-style:normal;font-size:12px;font-weight:800;color:var(--ink)}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:700;border-radius:999px;padding:3px 11px}
.chip.pass{background:rgba(56,224,138,.14);color:var(--good)}.chip.fail{background:rgba(255,90,106,.14);color:var(--bad)}
.foot{color:var(--faint);font-size:12.5px;margin-top:44px;border-top:1px solid var(--border);padding-top:14px;font-family:var(--mono)}
@media(max-width:620px){.cards{grid-template-columns:1fr}.bigstat .to{font-size:42px}}
"""

_JS = ("(function(){try{var t=localStorage.getItem('ragprobe-theme');"
       "if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();")


def esc(text: Any) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _pct(x: float) -> str:
    return f"{x*100:.0f}%"


def _bar(fraction: float, tone: str) -> str:
    return (f'<div class="bar {tone}"><span style="width:{max(0.0,min(1.0,fraction))*100:.0f}%"></span>'
            f'<em>{_pct(fraction)}</em></div>')


def render(results: Mapping[str, Any], title: str = "RAGProbe security report") -> str:
    victim = results["victim"]
    by_defense: Dict[str, Any] = results["summary"]["by_defense"]
    card = scorecard(results)
    worst = max(by_defense.items(), key=lambda kv: kv[1]["asr"])
    best = min(by_defense.items(), key=lambda kv: kv[1]["asr"])

    p: List[str] = []
    p.append("<!doctype html><html lang='en' data-theme='dark'><head><meta charset='utf-8'>")
    p.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    p.append(f"<title>{esc(title)}</title><style>{_CSS}</style><script>{_JS}</script>")
    p.append("</head><body><div class='bgfx'></div><div class='wrap'>")

    # hero
    p.append("<div class='hero'><span class='eyebrow'>Security report</span>")
    p.append(f"<h1>{esc(title)}</h1>")
    p.append(f"<p class='muted'>{results['attack_count']} attacks &middot; victim "
             f"<b>{esc(victim['name'])}</b>"
             f"{' (' + esc(victim['model']) + ')' if victim.get('model') else ''} "
             f"&middot; corpus <code>{esc(results['attack_corpus'])}</code> &middot; seed {esc(results['seed'])}</p>")
    p.append("<div class='bigstat'>"
             f"<span class='from'>{_pct(worst[1]['asr'])}</span><span class='arr'>&rarr;</span>"
             f"<span class='to'>{_pct(best[1]['asr'])}</span>"
             f"<span class='cap'>of attacks still work after the <b>{esc(best[0])}</b> defence</span></div>")
    p.append("</div>")

    if victim.get("deterministic"):
        p.append("<div class='banner'><b>Worst-case drill.</b> The victim obeys every instruction it "
                 "can parse, so these rates test the harness and the code-level defences, not a real model.</div>")

    # kpi
    reduction = worst[1]["asr"] - best[1]["asr"]
    p.append("<div class='cards'>"
             f"<div class='stat'><div class='k'>No defence</div><div class='v'>{_pct(worst[1]['asr'])}</div></div>"
             f"<div class='stat'><div class='k'>Best defence</div><div class='v'>{_pct(best[1]['asr'])}</div></div>"
             f"<div class='stat'><div class='k'>Attacks stopped</div><div class='v'>{_pct(reduction)}</div></div>"
             "</div>")

    # OWASP scorecard
    p.append(f"<h2>OWASP scorecard</h2>")
    p.append(f"<p class='muted'>Grade = attack-success under the <code>{esc(card['defense'])}</code> "
             "defence (A = almost nothing gets through). The meter shows how much of the undefended "
             "attack-success it removes.</p>")
    p.append("<div class='grid'>")
    for row in card["rows"]:
        tone = GRADE_TONE.get(row["grade"], "warn")
        undef = row["asr_undefended"]
        removed = 1.0 if (undef in (None, 0)) else max(0.0, (undef - row["asr_defended"]) / undef)
        undef_txt = _pct(undef) if undef is not None else "&ndash;"
        fill = {"pass": "var(--good)", "warn": "var(--warn)", "fail": "var(--bad)"}[tone]
        p.append(f"<div class='risk'><div class='r1'><div><div class='nm'>{esc(row['name'])}</div>"
                 f"<div class='cd'>{esc(row['owasp'])}</div></div><div class='gr {tone}'>{esc(row['grade'])}</div></div>"
                 f"<div class='meter'><i style='width:{removed*100:.0f}%;background:{fill}'></i></div>"
                 f"<div class='ms'><span>{undef_txt} &rarr; {_pct(row['asr_defended'])}</span><span>stopped</span></div></div>")
    p.append("</div>")

    # Defences compared
    p.append("<h2>Defences compared</h2>")
    p.append("<p class='muted'>Attack-success per defence, with its 95% confidence interval and what it "
             "costs the real user.</p>")
    p.append("<table><tr><th>Defence</th><th>Attack-success</th><th class='n'>95% CI</th>"
             "<th class='n'>Utility kept</th><th class='n'>Blocked early</th></tr>")
    for name, block in by_defense.items():
        tone = "good" if block["asr"] <= 0.2 else "bad" if block["asr"] >= 0.6 else "mid"
        ci = f"{block['asr_ci95'][0]*100:.0f}&ndash;{block['asr_ci95'][1]*100:.0f}"
        util = "&ndash;" if block["utility_ok_rate"] is None else _pct(block["utility_ok_rate"])
        p.append(f"<tr><td><code>{esc(name)}</code></td><td>{_bar(block['asr'], tone)}</td>"
                 f"<td class='n'>{ci}</td><td class='n'>{util}</td>"
                 f"<td class='n'>{block['blocked_pre']}/{block['trials']}</td></tr>")
    p.append("</table>")

    # Per-attack detail
    detail = results.get("trials_detail") or []
    show = ["none"] if "none" in by_defense else []
    if best[0] not in show:
        show.append(best[0])
    for dname in show:
        rows = [t for t in detail if t["defense"] == dname]
        if not rows:
            continue
        label = "with no defence" if dname == "none" else f"with the {dname} defence"
        p.append(f"<h2>Every attack, {esc(label)}</h2>")
        p.append("<table><tr><th>Attack</th><th>OWASP</th><th>Scenario</th><th>Outcome</th><th>Stopped by</th></tr>")
        for t in rows:
            chip = ("<span class='chip fail'>got through</span>" if t["success"]
                    else "<span class='chip pass'>blocked</span>")
            events = ", ".join(sorted({e["defense"] for e in t.get("defense_events", [])})) or "&ndash;"
            p.append(f"<tr><td class='mono'>{esc(t['attack_id'])}</td><td><code>{esc(t['owasp'])}</code></td>"
                     f"<td>{esc(t['scenario'])}</td><td>{chip}</td><td>{esc(events)}</td></tr>")
        p.append("</table>")

    p.append(f"<p class='foot'>Generated by RAGProbe &middot; {esc(results.get('created',''))}</p>")
    p.append("</div></body></html>")
    return "".join(p)


def write_report(results: Mapping[str, Any], out_path: Path,
                 title: str = "RAGProbe security report") -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(results, title=title), encoding="utf-8")
    return out_path
