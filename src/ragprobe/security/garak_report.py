"""Read a garak report and line its results up with RAGProbe's, by OWASP risk.

garak (NVIDIA, Apache-2.0) probes the model; RAGProbe probes the app built on it:
the retrieval, the documents and the tools around the model. A team running both
gets two reports in two vocabularies. This module reads garak's ``report.jsonl``
and puts its results in the same table as RAGProbe's, one row per OWASP risk, so
the model layer and the app layer can be read side by side.

garak tags its probes with the OWASP Top 10 for LLM Applications v1.1 (2023,
``owasp:llm01`` .. ``owasp:llm10``); RAGProbe uses the 2025 list. The two number
the same risks differently (v1.1's LLM02, insecure output handling, is 2025's
LLM05), so each tag is mapped to the 2025 risk it became. Two v1.1 risks have no
2025 entry, insecure plugin design and model theft; they keep their v1.1 names.

Only garak's own counts are used: for each probe and detector, how many outputs
the detector passed and how many it failed (a fail is a hit: the attack worked).
Nothing is re-scored, and an output garak could not score (``nones``) is left out
of the rate, as garak leaves it out. A probe counts once, by its detector with the
highest hit rate.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ragprobe.errors import RagprobeError
from ragprobe.security.attacks import OWASP
from ragprobe.security.report import scorecard
from ragprobe.stats import wilson_interval

#: garak's v1.1 tag -> the 2025 risk it became.
V11_TO_2025 = {
    "llm01": "LLM01",  # Prompt Injection
    "llm02": "LLM05",  # Insecure Output Handling -> Improper Output Handling
    "llm03": "LLM04",  # Training Data Poisoning -> Data and Model Poisoning
    "llm04": "LLM10",  # Model Denial of Service -> Unbounded Consumption
    "llm05": "LLM03",  # Supply Chain Vulnerabilities -> Supply Chain
    "llm06": "LLM02",  # Sensitive Information Disclosure
    "llm08": "LLM06",  # Excessive Agency
    "llm09": "LLM09",  # Overreliance -> Misinformation
}
#: v1.1 risks with no 2025 entry, kept under their v1.1 names.
V11_ONLY = {"llm07": "v1.1-LLM07", "llm10": "v1.1-LLM10"}

NAMES = {
    **OWASP,
    "LLM03": "Supply Chain",
    "LLM04": "Data and Model Poisoning",
    "v1.1-LLM07": "Insecure Plugin Design (OWASP v1.1)",
    "v1.1-LLM10": "Model Theft (OWASP v1.1)",
}


class GarakReportError(RagprobeError, ValueError):
    """The file isn't a garak report RAGProbe can read."""


def owasp_risks(tags: List[str]) -> List[str]:
    """The risks a garak probe's tags name: the 2025 id, or the v1.1 one 2025 dropped."""
    risks: List[str] = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.lower().startswith("owasp:"):
            continue
        key = tag.split(":", 1)[1].lower()
        risk = V11_TO_2025.get(key) or V11_ONLY.get(key)
        if risk and risk not in risks:
            risks.append(risk)
    return risks


def read_report(path: Path) -> Dict[str, Any]:
    """The run, the target, and one row per probe and detector of a garak ``report.jsonl``.

    Raises GarakReportError when the file has no ``eval`` entry, which is what a
    run that never finished, or a file that isn't a garak report, looks like.
    """
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise GarakReportError(f"cannot read the garak report {path}: {e}") from None
    meta: Dict[str, Any] = {"garak_version": None, "run": None, "start_time": None,
                            "target": None}
    tags: Dict[str, List[str]] = {}
    rows: List[Dict[str, Any]] = []
    malformed = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if not isinstance(entry, dict):
            malformed += 1
            continue
        kind = entry.get("entry_type")
        if kind == "init":
            meta.update(garak_version=entry.get("garak_version"), run=entry.get("run"),
                        start_time=entry.get("start_time"))
        elif kind == "start_run setup":
            target = entry.get("plugins.target_type")
            name = entry.get("plugins.target_name")
            meta["target"] = f"{target} {name}" if target and name else target
        elif kind == "plugin_cache":
            probes = (entry.get("plugin_cache") or {}).get("probes") or {}
            for name, info in probes.items():
                if isinstance(info, dict) and isinstance(info.get("tags"), list):
                    tags[name.removeprefix("probes.")] = info["tags"]
        elif kind == "eval":
            row = _eval_row(entry)
            if row is None:
                malformed += 1
            else:
                rows.append(row)
    if not rows:
        raise GarakReportError(
            f"{path} has no garak results (no 'eval' entry): is it a finished garak report?")
    for row in rows:
        row["owasp"] = owasp_risks(tags.get(row["probe"], []))
    return {**meta, "report": str(path), "rows": rows, "malformed": malformed}


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _eval_row(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One probe x detector result: the hits are the outputs the detector failed."""
    probe, detector = entry.get("probe"), entry.get("detector")
    passed = entry.get("passed")
    total = entry.get("total_evaluated", entry.get("total"))
    fails = entry.get("fails")
    if fails is None and _count(total) and _count(passed):
        fails = total - passed   # garak before 0.13 wrote only passed and total
    if not (isinstance(probe, str) and isinstance(detector, str)
            and _count(total) and _count(fails) and fails <= total):
        return None
    return {"probe": probe, "detector": detector.removeprefix("detector."), "hits": fails,
            "total": total, "nones": entry.get("nones") or 0}


def _rate(hits: int, total: int) -> Dict[str, Any]:
    lo, hi = wilson_interval(hits, total) if total else (0.0, 0.0)
    return {"hits": hits, "total": total, "asr": hits / total if total else None,
            "ci95": [lo, hi]}


def summarise(report: Dict[str, Any]) -> Dict[str, Any]:
    """garak's results by OWASP risk, and by probe, most hits first.

    garak runs several detectors over the same outputs, so a probe counts once, by
    its detector with the highest hit rate: adding up every detector would count
    each output several times.
    """
    worst: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    for row in report["rows"]:
        rate = row["hits"] / row["total"] if row["total"] else 0.0
        if row["probe"] not in worst or rate > worst[row["probe"]][0]:
            worst[row["probe"]] = (rate, row)
    by_risk: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    untagged = [0, 0]
    for _, row in worst.values():
        for risk in row["owasp"] or [None]:
            bucket = by_risk[risk] if risk else untagged
            bucket[0] += row["hits"]
            bucket[1] += row["total"]
    probes = [{"probe": r["probe"], "detector": r["detector"], "owasp": r["owasp"],
               **_rate(r["hits"], r["total"])} for _, r in worst.values()]
    probes.sort(key=lambda p: (-(p["asr"] or 0.0), -p["hits"], p["probe"]))
    return {
        **{k: report[k] for k in ("garak_version", "target", "run", "start_time", "report",
                                  "malformed")},
        "by_owasp": {risk: {"name": NAMES.get(risk, risk), **_rate(*by_risk[risk])}
                     for risk in sorted(by_risk)},
        "untagged": _rate(*untagged),
        "probes": probes,
    }


def combine(garak: Dict[str, Any], ragprobe: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One row per OWASP risk: garak's model-level rate beside RAGProbe's app-level scorecard."""
    card = scorecard(ragprobe) if ragprobe else None
    app = {row["owasp"]: row for row in card["rows"]} if card else {}
    rows = []
    for risk in sorted(set(garak["by_owasp"]) | set(app)):
        g, a = garak["by_owasp"].get(risk), app.get(risk)
        rows.append({
            "owasp": risk, "name": NAMES.get(risk, risk),
            "garak": g and {k: g[k] for k in ("hits", "total", "asr", "ci95")},
            "ragprobe": a and {k: a[k] for k in ("asr_undefended", "asr_defended", "grade",
                                                 "trials")},
        })
    return {"garak": {k: garak[k] for k in ("garak_version", "target", "run", "report")},
            "ragprobe_defense": card["defense"] if card else None,
            "ragprobe_victim": (ragprobe or {}).get("victim"), "rows": rows}


def _pct(rate: Optional[float]) -> str:
    return "-" if rate is None else f"{rate * 100:.0f}%"


def _ci(r: Dict[str, Any]) -> str:
    return f"{_pct(r['asr'])} ({_pct(r['ci95'][0])}-{_pct(r['ci95'][1])})"


def render_markdown(summary: Dict[str, Any], combined: Optional[Dict[str, Any]] = None,
                    top: int = 10) -> str:
    """garak's results as Markdown, with the side-by-side table when RAGProbe's are given."""
    out = [
        "# garak results, by OWASP risk\n",
        f"garak {summary['garak_version'] or '?'} against `{summary['target'] or '?'}` "
        f"(run {summary['run'] or '?'}). A hit is an output garak's detector failed; the rate "
        "leaves out outputs garak could not score. Risks follow the OWASP Top 10 for LLM "
        "Applications 2025, with garak's v1.1 tags mapped to it.\n",
    ]
    if combined:
        victim = combined.get("ragprobe_victim") or {}
        out.append("## The model (garak) and the app (RAGProbe)\n")
        out.append(f"RAGProbe: {victim.get('name', '?')} ({victim.get('model', '?')}), "
                   f"defence `{combined['ragprobe_defense']}`.\n")
        out.append("| Risk | | garak hits | garak rate (95% CI) | RAGProbe undefended "
                   "| RAGProbe defended | grade |")
        out.append("|---|---|---|---|---|---|---|")
        for row in combined["rows"]:
            g, a = row["garak"], row["ragprobe"]
            gcells = f"{g['hits']}/{g['total']} | {_ci(g)}" if g else "- | not probed"
            acells = (f"{_pct(a['asr_undefended'])} | {_pct(a['asr_defended'])} | {a['grade']}"
                      if a else "- | - | not probed")
            out.append(f"| {row['owasp']} | {row['name']} | {gcells} | {acells} |")
        out.append("")
    out.append("## By risk\n")
    out.append("| Risk | | hits | rate (95% CI) |")
    out.append("|---|---|---|---|")
    for risk, r in summary["by_owasp"].items():
        out.append(f"| {risk} | {r['name']} | {r['hits']}/{r['total']} | {_ci(r)} |")
    u = summary["untagged"]
    if u["total"]:
        out.append(f"| - | no OWASP tag | {u['hits']}/{u['total']} | {_ci(u)} |")
    out.append(f"\n## Probes with the most hits (top {top})\n")
    out.append("| probe | worst detector | hits | rate | risks |")
    out.append("|---|---|---|---|---|")
    for p in summary["probes"][:top]:
        out.append(f"| `{p['probe']}` | `{p['detector']}` | {p['hits']}/{p['total']} | "
                   f"{_pct(p['asr'])} | {', '.join(p['owasp']) or '-'} |")
    if summary["malformed"]:
        out.append(f"\n{summary['malformed']} line(s) of the report could not be read and "
                   "were skipped.")
    return "\n".join(out) + "\n"


def render_terminal(summary: Dict[str, Any], combined: Optional[Dict[str, Any]] = None) -> str:
    """A short plain-text view for the terminal."""
    out = ["", f"garak {summary['garak_version'] or '?'} against {summary['target'] or '?'}",
           "-" * 60]
    if combined:
        out.append(f"  {'risk':<11}{'garak (model)':>16}   "
                   f"RAGProbe (app, {combined['ragprobe_defense']})")
        for row in combined["rows"]:
            g, a = row["garak"], row["ragprobe"]
            gtxt = f"{g['hits']}/{g['total']} {_pct(g['asr']):>4}" if g else "not probed"
            atxt = (f"{_pct(a['asr_undefended'])} -> {_pct(a['asr_defended'])}  {a['grade']}"
                    if a else "not probed")
            out.append(f"  {row['owasp']:<11}{gtxt:>16}   {atxt}")
    else:
        for risk, r in summary["by_owasp"].items():
            out.append(f"  {risk:<11}{r['name'][:36]:<38}{r['hits']:>5}/{r['total']:<5}"
                       f"{_pct(r['asr']):>5}")
    if summary["probes"]:
        p = summary["probes"][0]
        out.append(f"\n  most hits: {p['probe']} ({p['hits']}/{p['total']}, {_pct(p['asr'])})")
    out.append("")
    return "\n".join(out)
