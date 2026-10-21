"""Attack several models with the same suite and compare how they hold up.

The security suite answers "is this app safe?" for one target. This answers the
question a team actually asks when choosing a model: "which of these models resists
attacks best, and does a defence change the ranking?" It runs the identical attack
corpus and defences against each model and lays the results side by side, with the
same checkable oracles - so the comparison is apples to apples, not vibes.

Live models are nondeterministic, so every rate carries a Wilson 95% interval and
the number of trials is reported; a small gap between two models is not a result.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from ragprobe.security.models import ModelSpec, build_victim, resolve
from ragprobe.security.suite import run_suite
from ragprobe.stats import mcnemar_from_pairs


def _per_attack_success(trials_detail, defense: str) -> Dict[str, bool]:
    """Collapse a model's trials under one defence to one verdict per attack.

    An attack counts as a success if it got through on *any* trial (the attacker
    only needs to win once). This gives the paired, per-attack vector McNemar's
    test needs to compare two models on the same attacks.
    """
    out: Dict[str, bool] = {}
    for t in trials_detail:
        if t["defense"] != defense:
            continue
        out[t["attack_id"]] = out.get(t["attack_id"], False) or bool(t["success"])
    return out


def paired_mcnemar(report: Dict[str, object]) -> List[Dict[str, object]]:
    """McNemar's test between the strongest model and every other, on shared attacks.

    "Strongest" = lowest attack-success rate under the base (first) defence. A
    small p-value means the gap to that model is real, not sampling noise.
    """
    models = report.get("models", [])
    base = report["defenses"][0] if report.get("defenses") else None
    scored = [m for m in models if m.get("per_attack_base")]
    if base is None or len(scored) < 2:
        return []
    best = min(scored, key=lambda m: m["summary"]["by_defense"].get(base, {}).get("asr", 1.0))
    results: List[Dict[str, object]] = []
    for other in scored:
        if other["model"] == best["model"]:
            continue
        ids = sorted(set(best["per_attack_base"]) & set(other["per_attack_base"]))
        if not ids:
            continue
        wins_best = [not best["per_attack_base"][i] for i in ids]   # "win" = blocked the attack
        wins_other = [not other["per_attack_base"][i] for i in ids]
        test = mcnemar_from_pairs(wins_best, wins_other)
        results.append({"strongest": best["model"], "other": other["model"],
                        "attacks": len(ids), **test})
    return results


def compare_models(
    attacks_path: Path,
    model_specs: Sequence[str],
    defenses: Sequence[str],
    trials: int = 1,
    seed: int = 7,
    base_dir: Optional[Path] = None,
    corpus_dir: str = "datasets/docs",
    vectors: Optional[Sequence[str]] = None,
    max_tokens: int = 512,
    get_key: Callable[[str], Optional[str]] = os.environ.get,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, object]:
    specs = [resolve(s) for s in model_specs]
    missing = [s.name for s in specs if not get_key(s.key_env)]
    if missing:
        needed = {s.name: s.key_env for s in specs if s.name in missing}
        raise ValueError(
            "no API key for: " + ", ".join(f"{n} (set {e})" for n, e in needed.items())
        )

    runs = []
    started = time.time()
    for spec in specs:
        if progress:
            progress(spec.name)
        victim = build_victim(spec, get_key(spec.key_env), max_tokens=max_tokens)
        result = run_suite(attacks_path, victim, defenses=defenses, trials=trials, seed=seed,
                           base_dir=base_dir, corpus_dir=corpus_dir, vectors=vectors)
        runs.append({"model": spec.name, "note": spec.note, "endpoint": spec.model,
                     "summary": result["summary"], "trials_per_cell": result["trials_per_cell"],
                     "per_attack_base": _per_attack_success(result["trials_detail"], defenses[0])})

    report: Dict[str, object] = {
        "kind": "security-compare",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "defenses": list(defenses),
        "duration_s": round(time.time() - started, 2),
        "models": runs,
    }
    report["paired_mcnemar"] = paired_mcnemar(report)
    return report


def render_markdown(report: Dict[str, object]) -> str:
    defenses = report["defenses"]
    lines = ["# Model security comparison\n",
             "Same attack corpus and defences against each model; lower attack-success "
             "rate (ASR) is better. Live models are nondeterministic, so rates carry a "
             "Wilson 95% interval.\n"]
    # Overall ASR per model per defence.
    lines.append("## Attack-success rate by model\n")
    lines.append("| Model | " + " | ".join(f"ASR ({d})" for d in defenses) + " | Endpoint |")
    lines.append("|---|" + "|".join("--:" for _ in defenses) + "|---|")
    for run in report["models"]:
        cells = []
        for d in defenses:
            block = run["summary"]["by_defense"].get(d, {})
            if block:
                lo, hi = block["asr_ci95"]
                cells.append(f"{block['asr']*100:.0f}% ({lo*100:.0f}-{hi*100:.0f})")
            else:
                cells.append("-")
        lines.append(f"| `{run['model']}` | " + " | ".join(cells) + f" | `{run['endpoint']}` |")
    lines.append("")

    # Per-OWASP, undefended, to show where each model is weak.
    base = defenses[0]
    cats = sorted({o for run in report["models"]
                   for o in run["summary"]["by_defense_owasp"].get(base, {})})
    if cats:
        lines.append(f"## Attack-success rate by OWASP category (defence: `{base}`)\n")
        lines.append("| Model | " + " | ".join(cats) + " |")
        lines.append("|---|" + "|".join("--:" for _ in cats) + "|")
        for run in report["models"]:
            row = run["summary"]["by_defense_owasp"].get(base, {})
            cells = [f"{row[o]['asr']*100:.0f}%" if o in row else "-" for o in cats]
            lines.append(f"| `{run['model']}` | " + " | ".join(cells) + " |")
        lines.append("")
    # Paired significance: is the gap to the strongest model real?
    paired = report.get("paired_mcnemar") or []
    if paired:
        strongest = paired[0]["strongest"]
        base = report["defenses"][0]
        lines.append(f"## Is the gap real? (McNemar, paired on the same attacks, defence: `{base}`)\n")
        lines.append(f"Each row tests the strongest model (`{strongest}`, lowest ASR) against "
                     "another on the identical attacks. p < 0.05 means the difference is unlikely "
                     "to be chance.\n")
        lines.append("| Strongest | vs | Attacks | Discordant | p-value | Verdict |")
        lines.append("|---|---|--:|--:|--:|---|")
        for t in paired:
            verdict = "significant" if t["p_value"] < 0.05 else "not significant"
            lines.append(f"| `{t['strongest']}` | `{t['other']}` | {t['attacks']} | "
                         f"{t['discordant']} | {t['p_value']:.4f} | {verdict} |")
        lines.append("")
    lines.append("> " + "; ".join(f"`{r['model']}` = {r['note']}" for r in report["models"]
                                   if r["note"]))
    lines.append("")
    return "\n".join(lines)
