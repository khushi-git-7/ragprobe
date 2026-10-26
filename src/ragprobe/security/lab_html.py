"""The attack lab page: the "beyond one prompt" results, in the site's design.

Same shell, tokens and motion as the other pages (it reuses the security report's
styles and the shared top bar). It tells four short stories, each from a real run:
the guided demo (grade F to A), poisoned tools, multi-turn attacks and obfuscation -
and says plainly where a defence does NOT hold.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ragprobe import webui
from ragprobe.security.report_html import _CSS, REPO_URL, _bar, _pct, esc

GRADE_TONE = {"A": "pass", "B": "pass", "C": "warn", "D": "fail", "F": "fail"}

_EXTRA_CSS = """
.jump{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 4px}
.jump a{padding:7px 14px;border-radius:999px;border:1px solid var(--border-2);background:var(--panel);color:var(--muted);text-decoration:none;font-size:13.5px;font-weight:600;transition:border-color .15s,color .15s}
.jump a:hover{border-color:var(--accent);color:var(--ink)}
.take{border-left:3px solid var(--accent);background:var(--panel-2);border-radius:0 10px 10px 0;padding:12px 15px;margin:14px 0;font-size:14px;color:var(--muted)}
.take b{color:var(--ink)}
.cmd{display:inline-block;font-family:var(--mono);font-size:13px;color:var(--muted);background:var(--panel-2);border:1px solid var(--border);border-radius:10px;padding:7px 12px;margin:4px 0 10px;overflow-x:auto;max-width:100%}
.cmd b{color:var(--accent-text,var(--accent));font-weight:600}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
.sub{color:var(--faint);font-size:12.5px;font-family:var(--mono);margin-top:6px}
section.lab{scroll-margin-top:84px}
"""


def _tone_attack(asr: float) -> str:
    return "good" if asr <= 0.2 else "bad" if asr >= 0.6 else "mid"


def _tone_recall(recall: float) -> str:
    return "good" if recall >= 0.7 else "bad" if recall <= 0.2 else "mid"


def _ci(block: Dict[str, Any]) -> str:
    lo, hi = block["asr_ci95"]
    return f"{lo * 100:.0f}&ndash;{hi * 100:.0f}"


def _story(demo: Dict[str, Any]) -> str:
    cards: List[str] = []
    for i, st in enumerate(demo["stages"], 1):
        tone = GRADE_TONE.get(st["grade"], "warn")
        stopped = 1.0 - st["asr"]
        fill = {"pass": "var(--good)", "warn": "var(--warn)", "fail": "var(--bad)"}[tone]
        cards.append(
            "<div class='risk'><div class='r1'><div>"
            f"<div class='nm'>Step {i}: {esc(st['label'])}</div>"
            f"<div class='cd'>{esc(st['defense'])}</div></div>"
            f"<div class='gr {tone}'>{esc(st['grade'])}</div></div>"
            f"<div class='meter'><i style='width:{stopped * 100:.0f}%;background:{fill}'></i></div>"
            f"<div class='ms'><span>{_pct(st['asr'])} of attacks work</span>"
            f"<span>{_pct(stopped)} stopped</span></div>"
            f"<div class='sub'>wrongly blocks {_pct(st['false_block'])} of harmless requests</div></div>")
    first, last = demo["stages"][0], demo["stages"][-1]
    note = ""
    mid = demo["stages"][1] if len(demo["stages"]) > 1 else None
    if mid is not None and mid["asr"] >= first["asr"]:
        note = ("<div class='take'><b>Why step 2 changes nothing:</b> this simulated victim ignores "
                "prompt wording by design, so the gain comes from the code-level layers (input "
                "screen, tool policy, output filter), which do not depend on the model behaving. "
                "Against a live model prompt hardening can help &mdash; measure it with "
                "<code>ragprobe security run --victim live</code>.</div>")
    return (
        "<section class='lab' id='story'><h2 class='reveal'>The demo: Acme Helpdesk, grade "
        f"{esc(first['grade'])} to {esc(last['grade'])}</h2>"
        "<p class='muted'>A fictional support assistant, built to be vulnerable. Scan it as it "
        "ships, add defences one step at a time, rescan. Every number is a real run.</p>"
        "<div class='cmd'><b>$</b> ragprobe demo</div>"
        f"<div class='grid reveal'>{''.join(cards)}</div>{note}</section>")


def _mcp(mcp: Dict[str, Any]) -> str:
    rows = []
    for name, b in mcp["by_defense"].items():
        rows.append(
            f"<tr><td><code>{esc(name)}</code></td><td>{_bar(b['asr'], _tone_attack(b['asr']))}</td>"
            f"<td class='n'>{_ci(b)}</td><td class='n'>{b['withheld']}/{b['trials']}</td>"
            f"<td class='n'>{b['blocked_by_policy']}/{b['trials']}</td></tr>")
    return (
        "<section class='lab' id='mcp'><h2 class='reveal'>Poisoned tools (MCP)</h2>"
        "<p class='muted'>The attacker's text hides in a <b>tool</b> instead of the user's message: "
        "a tool description that orders a harmful action, a tool that turns malicious after you "
        "approve it (rug-pull), or a tool result that tells the agent to leak data through "
        f"another tool. {mcp['scenario_count']} scenarios against a worst-case obedient agent; "
        "an attack succeeds when a planted code leaves the sandbox by email.</p>"
        "<div class='cmd'><b>$</b> ragprobe security mcp</div>"
        "<table class='reveal'><tr><th>Defence</th><th>Data leaked</th><th class='n'>95% CI</th>"
        "<th class='n'>Poison withheld</th><th class='n'>Blocked by policy</th></tr>"
        + "".join(rows) + "</table>"
        "<div class='take'><b>The lesson:</b> a rule about what a tool may <i>do</i> (mail only to "
        "known contacts) stops this whole class however the poison arrives. A screen that reads "
        "the words only catches some of it, because the harm is an action, not text.</div></section>")


def _multiturn(mt: Dict[str, Any]) -> str:
    rows = []
    for name, b in mt["by_defense"].items():
        rows.append(
            f"<tr><td><code>{esc(name)}</code></td><td>{_bar(b['asr'], _tone_attack(b['asr']))}</td>"
            f"<td class='n'>{_ci(b)}</td><td class='n'>{b['any_turn_withheld']}/{b['trials']}</td></tr>")
    survivors = sorted({d["attack"] for d in mt["detail"]
                        if d["defense"] == "layered" and d["success"]})
    chips = "".join(f"<span class='chip fail'>{esc(s)}</span>" for s in survivors)
    gap = ""
    if survivors:
        gap = ("<div class='take'><b>An honest gap:</b> the layered defence does not stop every "
               "chain. These still get through, because no single message is suspicious and the "
               "assembled marker is not a secret the output filter redacts:"
               f"<div class='chips'>{chips}</div>Closing this needs a view of the whole "
               "conversation, not just each message &mdash; reported here, not hidden.</div>")
    return (
        "<section class='lab' id='multiturn'><h2 class='reveal'>Multi-turn attacks</h2>"
        "<p class='muted'>The attack is built over several turns and each turn looks harmless on "
        "its own: plant two halves of a code in a &ldquo;memory game&rdquo;, then ask for them "
        f"joined, or climb from a friendly &ldquo;audit&rdquo; to a direct request. "
        f"{mt['attack_count']} chains against the real simulated victim, which reads the whole "
        "history just as a model's context does.</p>"
        "<div class='cmd'><b>$</b> ragprobe security multiturn</div>"
        "<table class='reveal'><tr><th>Defence</th><th>Attack success</th><th class='n'>95% CI</th>"
        "<th class='n'>A turn withheld</th></tr>" + "".join(rows) + "</table>" + gap + "</section>")


def _obfuscation(ob: Dict[str, Any]) -> str:
    rows = []
    for r in ob["rows"]:
        label = "no obfuscation (baseline)" if r["obfuscation"] == "none" else r["obfuscation"]
        rows.append(
            f"<tr><td><code>{esc(label)}</code></td>"
            f"<td>{_bar(r['recall_raw'], _tone_recall(r['recall_raw']))}</td>"
            f"<td>{_bar(r['recall_normalized'], _tone_recall(r['recall_normalized']))}</td></tr>")
    return (
        "<section class='lab' id='obfuscation'><h2 class='reveal'>Hidden injections</h2>"
        "<p class='muted'>The words are still readable to the model, but a keyword detector no "
        "longer matches them: letters separated by invisible characters, look-alike letters from "
        "another alphabet, stretched spacing, or the instruction buried in HTML. The bars show how "
        f"many of {ob['injections']} injections the detector still catches &mdash; as received, and "
        "after the text is cleaned up first.</p>"
        "<div class='cmd'><b>$</b> ragprobe security obfuscation</div>"
        "<table class='reveal'><tr><th>Hiding trick</th><th>Caught, as received</th>"
        "<th>Caught, after cleaning</th></tr>" + "".join(rows) + "</table>"
        "<div class='take'><b>The lesson:</b> tricks that keep the words intact are caught anyway, "
        "but the character-level ones drop the detector to <b>0%</b> until the text is normalised "
        "first &mdash; which restores it, and leaves ordinary sentences untouched.</div></section>")


def render(lab: Dict[str, Any], title: str = "RAGProbe attack lab") -> str:
    demo = lab["demo"]
    first, last = demo["stages"][0], demo["stages"][-1]
    p: List[str] = []
    p.append("<!doctype html><html lang='en' data-theme='dark'><head><meta charset='utf-8'>")
    p.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    p.append(f"<title>{esc(title)}</title>")
    p.append(f"<style>{_CSS}{_EXTRA_CSS}{webui.NAV_CSS}{webui.REVEAL_CSS}{webui.FLOW_CSS}</style>")
    p.append(f"<script>{webui.THEME_BOOT}</script></head><body><div class='bgfx'></div>")
    p.append(webui.top_nav("lab", REPO_URL))
    p.append("<div class='wrap'>")
    p.append("<div class='hero reveal'><span class='eyebrow'>Attack lab</span>"
             f"<h1>{esc(title)}</h1>"
             "<p class='muted'>Attacks that go beyond a single prompt &mdash; and where the "
             "defences do and do not hold. Everything below is a real run of the code in this "
             "repository, rebuilt on every push.</p>"
             "<div class='bigstat'>"
             f"<span class='from'>{_pct(first['asr'])}</span><span class='arr'>&rarr;</span>"
             f"<span class='to'>{_pct(last['asr'])}</span>"
             f"<span class='cap'>of attacks work on the demo app: grade <b>{esc(first['grade'])}"
             f"</b> before, <b>{esc(last['grade'])}</b> after</span></div></div>")
    p.append("<div class='banner'><b>Worst-case drill.</b> The victim is a simulated model that "
             "obeys every instruction it can parse, so these rates test the harness and the "
             "code-level defences, not a real model. Live-model runs are separate.</div>")
    p.append("<nav class='jump' aria-label='On this page'>"
             "<a href='#story'>The demo</a><a href='#mcp'>Poisoned tools</a>"
             "<a href='#multiturn'>Multi-turn</a><a href='#obfuscation'>Hidden injections</a></nav>")
    p.append(_story(demo))
    p.append(_mcp(lab["mcp"]))
    p.append(_multiturn(lab["multiturn"]))
    p.append(_obfuscation(lab["obfuscation"]))
    p.append("<p class='foot'>Generated by RAGProbe &middot; reproduce with "
             "<code>ragprobe security lab</code></p></div>")
    p.append(webui.page_flow("lab", REPO_URL))
    p.append(f"<script>{webui.CHROME_JS}</script></body></html>")
    return "".join(p)
