"""Run the benchmark reproducibly and record how it was produced.

``run_bench`` takes the verifiable attacks from a frozen catalogue (by default the
held-out *test* split), runs them through the security suite against a victim, and
writes a results object with a **manifest** - the package version, git commit,
victim and sampling settings, seed, and a fingerprint of the exact attacks - so
anyone can see, and repeat, how a number was made. With a cache directory, live
model replies are stored and replayed, making a rerun free and identical.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ragprobe.bench.cache import CachingVictim
from ragprobe.bench.dataset import load_jsonl
from ragprobe.bench.schema import BenchItem, to_attack
from ragprobe.security.suite import run_suite

try:
    from ragprobe import __version__
except Exception:  # pragma: no cover - version is always importable in practice
    __version__ = "0"

BENCH_VERSION = "v1"


def select_attacks(items: Sequence[BenchItem], split: Optional[str] = None) -> List[BenchItem]:
    """The verifiable ``attack`` items, optionally limited to one split."""
    return [i for i in items if i.kind == "attack" and (split is None or i.split == split)]


def _attacks_yaml(items: Sequence[BenchItem], path: Path) -> Path:
    """Write the selected attacks as a suite-readable corpus (Attack fields only)."""
    import yaml

    rows = []
    for item in items:
        attack = to_attack(item)  # validates; raises on a malformed item
        row: Dict[str, Any] = {
            "id": attack.id, "vector": attack.vector, "goal": attack.goal,
            "technique": attack.technique, "payload": attack.payload,
            "owasp": attack.owasp, "language": attack.language,
        }
        if attack.question:
            row["question"] = attack.question
        if attack.cover:
            row["cover"] = attack.cover
        if attack.expect:
            row["expect"] = list(attack.expect)
        rows.append(row)
    path.write_text("", encoding="utf-8")
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump({"attacks": rows}, fh, allow_unicode=True, sort_keys=True)
    return path


def _fingerprint(items: Sequence[BenchItem]) -> str:
    payload = json.dumps([i.to_dict() for i in sorted(items, key=lambda x: x.id)],
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _git_sha(cwd: Path) -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd),
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def run_bench(
    catalogue: Path,
    victim,  # noqa: ANN001 - a Victim
    split: Optional[str] = "test",
    defenses: Sequence[str] = ("none", "layered"),
    trials: int = 1,
    seed: int = 42,
    cache_dir: Optional[Path] = None,
    base_dir: Optional[Path] = None,
    corpus_dir: str = "datasets/docs",
) -> Dict[str, Any]:
    """Run the benchmark and return a results object carrying its manifest."""
    catalogue = Path(catalogue)
    items = load_jsonl(catalogue)
    selected = select_attacks(items, split)
    if not selected:
        raise ValueError(f"no runnable attacks in {catalogue} for split={split!r}")

    runner = CachingVictim(victim, cache_dir) if cache_dir else victim
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        yaml_path = _attacks_yaml(selected, Path(tmp) / "attacks.yaml")
        result = run_suite(yaml_path, runner, defenses=list(defenses), trials=trials,
                           seed=seed, base_dir=base_dir, corpus_dir=corpus_dir)

    manifest = {
        "ragprobe_version": __version__,
        "git_sha": _git_sha(base_dir or Path.cwd()),
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bench_version": BENCH_VERSION,
        "catalogue": catalogue.as_posix(),
        "catalogue_fingerprint": _fingerprint(selected),
        "split": split,
        "attack_count": len(selected),
        "defenses": list(defenses),
        "trials": trials,
        "seed": seed,
        "victim": {"name": getattr(victim, "name", "?"),
                   "model": getattr(victim, "model", None),
                   "deterministic": getattr(victim, "deterministic", False),
                   "temperature": getattr(victim, "temperature", None)},
        "duration_s": round(time.time() - started, 2),
    }
    if cache_dir:
        manifest["cache"] = runner.stats()

    return {
        "kind": "bench-run",
        "manifest": manifest,
        "summary": result["summary"],
        "trials_per_cell": result["trials_per_cell"],
        "trials_detail": result["trials_detail"],
    }


def render_markdown(result: Dict[str, Any]) -> str:
    """A compact, reproducible report: the manifest, then attack-success per defence."""
    m = result["manifest"]
    by = result["summary"]["by_defense"]
    lines = [
        f"# Bench {m['bench_version']} run\n",
        f"Victim **{m['victim']['name']}**"
        + (f" (`{m['victim']['model']}`)" if m['victim'].get('model') else "")
        + f" &middot; split **{m['split']}** &middot; {m['attack_count']} attacks "
        f"&middot; seed {m['seed']}\n",
        "| Defence | Attack-success | 95% CI | Trials |",
        "|---|--:|--:|--:|",
    ]
    for name, block in by.items():
        lo, hi = block["asr_ci95"]
        lines.append(f"| `{name}` | {block['asr']*100:.0f}% | "
                     f"{lo*100:.0f}&ndash;{hi*100:.0f}% | {block['trials']} |")
    lines += [
        "",
        "## Manifest",
        "",
        f"- ragprobe `{m['ragprobe_version']}`"
        + (f", commit `{m['git_sha'][:12]}`" if m.get("git_sha") else ""),
        f"- catalogue `{m['catalogue']}` (fingerprint `{m['catalogue_fingerprint']}`)",
        f"- defences: {', '.join('`'+d+'`' for d in m['defenses'])}; trials {m['trials']}",
        f"- generated {m['created']}",
        "",
        "Rerun: `ragprobe bench run --split "
        f"{m['split']} --seed {m['seed']}` against the same victim reproduces these "
        "numbers (live victims via the response cache).",
        "",
    ]
    return "\n".join(lines)
