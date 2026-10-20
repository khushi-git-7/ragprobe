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
                     "summary": result["summary"], "trials_per_cell": result["trials_per_cell"]})

    return {
        "kind": "security-compare",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "defenses": list(defenses),
        "duration_s": round(time.time() - started, 2),
        "models": runs,
    }


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
    lines.append("> " + "; ".join(f"`{r['model']}` = {r['note']}" for r in report["models"]
                                   if r["note"]))
    lines.append("")
    return "\n".join(lines)
