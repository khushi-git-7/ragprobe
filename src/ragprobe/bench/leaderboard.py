"""Rank several models on the benchmark, with intervals and paired significance.

The question a team asks is "which model should we build on?" This runs the same
benchmark (the held-out test split by default) against each model, through the
same defences, and ranks them by attack-success. Because every model faces the
*identical* attacks, the comparison is paired: a McNemar test against the leader
says whether a gap is real or just sampling noise. Each run carries the runner's
manifest and uses the response cache, so a leaderboard built over several days of
rate-limited free-tier calls is reproducible and resumable.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from ragprobe.bench.run import run_bench
from ragprobe.security.compare import _per_attack_success
from ragprobe.security.models import ModelSpec, build_victim, resolve
from ragprobe.stats import mcnemar_from_pairs

import os


def run_leaderboard(
    catalogue: Path,
    model_specs: Sequence[str],
    split: Optional[str] = "test",
    defenses: Sequence[str] = ("none", "layered"),
    trials: int = 1,
    seed: int = 42,
    cache_dir: Optional[Path] = None,
    base_dir: Optional[Path] = None,
    corpus_dir: str = "datasets/docs",
    max_tokens: int = 512,
    get_key: Callable[[str], Optional[str]] = os.environ.get,
    build: Callable = build_victim,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, object]:
    """Run the benchmark against each model and rank them (lower attack-success is better)."""
    specs = [resolve(s) for s in model_specs]
    missing = [s.name for s in specs if not get_key(s.key_env)]
    if missing:
        needed = {s.name: s.key_env for s in specs if s.name in missing}
        raise ValueError("no API key for: "
                         + ", ".join(f"{n} (set {e})" for n, e in needed.items()))

    base = defenses[0]
    best_defense = defenses[-1]
    started = time.time()
    rows: List[Dict[str, object]] = []
    for spec in specs:
        if progress:
            progress(spec.name)
        victim = build(spec, get_key(spec.key_env), max_tokens=max_tokens)
        cache = (Path(cache_dir) / spec.name) if cache_dir else None
        result = run_bench(catalogue, victim, split=split, defenses=list(defenses),
                           trials=trials, seed=seed, cache_dir=cache, base_dir=base_dir,
                           corpus_dir=corpus_dir)
        rows.append({
            "model": spec.name, "note": spec.note, "endpoint": spec.model,
            "summary": result["summary"], "manifest": result["manifest"],
            "per_attack_base": _per_attack_success(result["trials_detail"], base),
        })

    # rank by attack-success under the strongest (last) defence, then undefended
    def key(row):
        by = row["summary"]["by_defense"]
        return (by.get(best_defense, {}).get("asr", 1.0), by.get(base, {}).get("asr", 1.0))

    rows.sort(key=key)
    for i, row in enumerate(rows, 1):
        row["rank"] = i

    report: Dict[str, object] = {
        "kind": "bench-leaderboard",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "split": split,
        "defenses": list(defenses),
        "duration_s": round(time.time() - started, 2),
        "models": rows,
    }
    report["paired_mcnemar"] = _leader_mcnemar(rows, best_defense)
    return report


def _leader_mcnemar(rows: List[Dict[str, object]], defense: str) -> List[Dict[str, object]]:
    """McNemar of the top-ranked model against each other, on the shared attacks."""
    scored = [r for r in rows if r.get("per_attack_base")]
    if len(scored) < 2:
        return []
    leader = scored[0]
    out = []
    for other in scored[1:]:
        ids = sorted(set(leader["per_attack_base"]) & set(other["per_attack_base"]))
        if not ids:
            continue
        wins_leader = [not leader["per_attack_base"][i] for i in ids]
        wins_other = [not other["per_attack_base"][i] for i in ids]
        test = mcnemar_from_pairs(wins_leader, wins_other)
        out.append({"leader": leader["model"], "other": other["model"],
                    "attacks": len(ids), **test})
    return out


def render_markdown(report: Dict[str, object]) -> str:
    defenses = report["defenses"]
    lines = ["# Model security leaderboard\n",
             f"The benchmark's **{report['split']}** split against each model, same attacks and "
             "defences. Lower attack-success rate (ASR) is better; rates carry a Wilson 95% "
             "interval.\n",
             "| Rank | Model | " + " | ".join(f"ASR ({d})" for d in defenses) + " | Endpoint |",
             "|--:|---|" + "|".join("--:" for _ in defenses) + "|---|"]
    for row in report["models"]:
        cells = []
        for d in defenses:
            block = row["summary"]["by_defense"].get(d, {})
            if block:
                lo, hi = block["asr_ci95"]
                cells.append(f"{block['asr']*100:.0f}% ({lo*100:.0f}-{hi*100:.0f})")
            else:
                cells.append("-")
        lines.append(f"| {row['rank']} | `{row['model']}` | " + " | ".join(cells)
                     + f" | `{row['endpoint']}` |")
    lines.append("")

    paired = report.get("paired_mcnemar") or []
    if paired:
        leader = paired[0]["leader"]
        lines.append(f"## Is the gap to the leader real? (McNemar, defence: `{report['defenses'][-1]}`)\n")
        lines.append(f"Each row tests the leader (`{leader}`) against another model on the identical "
                     "attacks. p < 0.05 means the difference is unlikely to be chance.\n")
        lines.append("| Leader | vs | Attacks | Discordant | p-value | Verdict |")
        lines.append("|---|---|--:|--:|--:|---|")
        for t in paired:
            verdict = "significant" if t["p_value"] < 0.05 else "not significant"
            lines.append(f"| `{t['leader']}` | `{t['other']}` | {t['attacks']} | "
                         f"{t['discordant']} | {t['p_value']:.4f} | {verdict} |")
        lines.append("")
    cut = [(r["model"], r["manifest"].get("truncated_replies", 0)) for r in report["models"]]
    cut = [(m, n) for m, n in cut if n]
    if cut:
        lines.append("> **Warning:** some replies hit the token limit and came back cut off or empty "
                     "(" + ", ".join(f"`{m}`: {n}" for m, n in cut) + "). Those count as "
                     "\"no attack succeeded\", so the rates for these models may be too low; "
                     "re-run with a larger `--max-tokens`.")
        lines.append("")
    notes = "; ".join(f"`{r['model']}` = {r['note']}" for r in report["models"] if r["note"])
    if notes:
        lines.append("> " + notes)
        lines.append("")
    return "\n".join(lines)
