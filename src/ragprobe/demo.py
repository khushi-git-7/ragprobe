"""`ragprobe demo` - the whole story in one command, offline.

A guided walkthrough against "Acme Helpdesk", a fictional support assistant that is
deliberately vulnerable (it is the simulated always-obey victim, which says so on
screen). It follows the loop a real team goes through:

1. scan the app as it ships and see how it grades;
2. turn on one defence and rescan - and see why a single prompt-level tweak is not
   enough;
3. turn on the layered defence and rescan;
4. check the defence is not just blocking everyone (the false-block rate).

Every number comes from a real suite run (nothing is scripted), so the demo is also
a smoke test of the whole pipeline. It never touches the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ragprobe.security.benign import false_block_rates, generate_benign
from ragprobe.security.report import GRADE_BANDS, grade_for, scorecard
from ragprobe.security.suite import run_suite
from ragprobe.security.victims import get_victim

APP = "Acme Helpdesk"

# The stages, in the order a team would try them.
STAGES = [
    ("none", "As it ships - no defences"),
    ("hardened", "Add a hardened system prompt"),
    ("detector", "Add an input screen (injection detector)"),
    ("layered", "Turn on the layered defence"),
]


def _overall(results: Dict[str, Any], defense: str) -> Dict[str, Any]:
    block = results["summary"]["by_defense"][defense]
    return {"defense": defense, "asr": block["asr"], "ci": block["asr_ci95"],
            "grade": grade_for(block["asr"]),
            "successes": block["successes"], "trials": block["trials"]}


def run_demo(attacks_path: Path = Path("datasets/security/attacks.yaml"),
             base_dir: Optional[Path] = None, seed: int = 7) -> Dict[str, Any]:
    """Run every stage against the simulated Acme Helpdesk and collect the story."""
    victim = get_victim("simulated")
    defenses = [d for d, _ in STAGES]
    results = run_suite(Path(attacks_path), victim, defenses=defenses, seed=seed,
                        base_dir=base_dir or Path.cwd())
    fb = false_block_rates(defenses, generate_benign())
    fb_map = {d["defense"]: d["false_block_rate"] for d in fb["defenses"]}

    stages: List[Dict[str, Any]] = []
    for defense, label in STAGES:
        stage = _overall(results, defense)
        stage["label"] = label
        stage["false_block"] = fb_map.get(defense, 0.0)
        card = scorecard(results, defense=defense)
        stage["risks"] = [{"owasp": r["owasp"], "name": r["name"], "grade": r["grade"],
                           "asr": r["asr_defended"]} for r in card["rows"]]
        stages.append(stage)
    return {"kind": "demo", "app": APP, "attacks": results["attack_count"],
            "victim": results["victim"], "stages": stages}


def _bar(asr: float, width: int = 20) -> str:
    filled = round(asr * width)
    return "#" * filled + "." * (width - filled)


def render(report: Dict[str, Any]) -> str:
    out: List[str] = []
    stages = report["stages"]
    out.append(f"RAGProbe demo - {report['app']}")
    out.append("=" * 60)
    out.append(f"{report['app']} is a fictional support assistant, built to be vulnerable.")
    out.append(f"{report['attacks']} attacks across the OWASP LLM Top 10 will try to take it over.")
    out.append("(Simulated always-obey victim: a worst-case drill, not a real model.)")
    for i, st in enumerate(stages, 1):
        out.append("")
        out.append(f"Step {i}: {st['label']}")
        out.append("-" * 60)
        lo, hi = st["ci"]
        out.append(f"  attacks that work  [{_bar(st['asr'])}] {st['asr']*100:3.0f}%  "
                   f"(95% CI {lo*100:.0f}-{hi*100:.0f}%)")
        out.append(f"  overall grade      {st['grade']}")
        risk_line = "  by risk            " + "  ".join(
            f"{r['owasp']}:{r['grade']}" for r in st["risks"])
        out.append(risk_line)
        out.append(f"  harmless requests wrongly blocked: {st['false_block']*100:.0f}%")
    first, last = stages[0], stages[-1]
    out.append("")
    out.append("=" * 60)
    out.append(f"Result: grade {first['grade']} -> {last['grade']}  "
               f"(attacks that work {first['asr']*100:.0f}% -> {last['asr']*100:.0f}%, "
               f"false blocks {last['false_block']*100:.0f}%)")
    mid = next((s for s in stages if s["defense"] == "hardened"), None)
    if mid is not None and mid["asr"] >= first["asr"]:
        out.append("Step 2 did not move the number because this simulated victim ignores "
                   "prompt-level wording by design - so the gain came from the code-level "
                   "layers (input screen, tool policy, output filter), which do not depend "
                   "on the model behaving. Against a live model, prompt hardening can help; "
                   "measure it with `ragprobe security run --victim live`.")
    out.append("")
    out.append("Try it on your own app:  ragprobe security run --html reports/security.html")
    return "\n".join(out)


def passes(report: Dict[str, Any]) -> bool:
    """The demo's own check: the story must actually improve end to end."""
    stages = report["stages"]
    return stages[-1]["asr"] < stages[0]["asr"] and \
        _grade_rank(stages[-1]["grade"]) < _grade_rank(stages[0]["grade"])


def _grade_rank(letter: str) -> int:
    order = [g for _, g in GRADE_BANDS]  # A..F, best first
    return order.index(letter)
