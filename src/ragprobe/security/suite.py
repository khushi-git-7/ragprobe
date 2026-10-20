"""Run the security suite: every attack x every defence x N trials, scored.

The output is a results document in the same spirit as the quality harness: plain
JSON, provenance stamped in (victim, determinism, attack-corpus fingerprint, seed),
and stable under re-running in simulated mode so the regression gate is meaningful.

The headline metric is **attack-success rate** (ASR) per (defence, OWASP category):
the fraction of trials whose oracle fired. Alongside it, for the ``none`` defence,
sits the **false-positive rate** of each detector on benign inputs, because an ASR
you bought by blocking real users is not a real defence - that trade-off is the
whole report.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ragprobe.security.attacks import Attack, corpus_fingerprint, load_attacks, select
from ragprobe.security.canary import make_canaries
from ragprobe.security.defenses import DefenseStack, build_defense
from ragprobe.security.oracles import judge, utility_ok
from ragprobe.security.scenarios import _Retriever, run_agent, run_chat, run_rag
from ragprobe.security.victims import Victim

SCHEMA_VERSION = 1


@dataclass
class TrialResult:
    attack_id: str
    owasp: str
    scenario: str
    goal: str
    defense: str
    trial: int
    success: bool
    detail: str
    leak_encoding: Optional[str]
    utility_ok: Optional[bool]
    blocked_pre: bool
    poison_retrieved: Optional[bool]
    output_tokens: int
    defense_events: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


def _wilson(successes: int, total: int, z: float = 1.96) -> List[float]:
    """Wilson 95% interval: honest error bars on small, live-model samples."""
    if total == 0:
        return [0.0, 0.0]
    phat = successes / total
    denom = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total))) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def run_trial(attack: Attack, defense: DefenseStack, victim: Victim, trial: int,
              seed: int, retriever: Optional[_Retriever]) -> TrialResult:
    canaries = make_canaries(seed, attack.id, trial)
    if attack.scenario == "chat":
        outcome = run_chat(attack, canaries, victim, defense)
    elif attack.scenario == "rag":
        if retriever is None:
            raise ValueError("rag attacks need a retriever")
        outcome = run_rag(attack, canaries, victim, defense, retriever)
    else:
        outcome = run_agent(attack, canaries, victim, defense)
    verdict = judge(attack, outcome, canaries)
    return TrialResult(
        attack_id=attack.id, owasp=attack.owasp, scenario=attack.scenario,
        goal=attack.goal, defense=defense.name, trial=trial,
        success=verdict.success, detail=verdict.detail, leak_encoding=verdict.leak_encoding,
        utility_ok=utility_ok(attack, outcome), blocked_pre=outcome.blocked_pre,
        poison_retrieved=outcome.poison_retrieved, output_tokens=outcome.output_tokens,
        defense_events=[vars(e) for e in outcome.defense_events],
    )


def _rate_block(trials: Sequence[TrialResult]) -> Dict[str, Any]:
    n = len(trials)
    s = sum(1 for t in trials if t.success)
    utils = [t.utility_ok for t in trials if t.utility_ok is not None]
    return {
        "trials": n,
        "successes": s,
        "asr": round(s / n, 4) if n else 0.0,
        "asr_ci95": _wilson(s, n),
        "blocked_pre": sum(1 for t in trials if t.blocked_pre),
        "utility_ok_rate": round(sum(utils) / len(utils), 4) if utils else None,
    }


def summarise(trials: List[TrialResult]) -> Dict[str, Any]:
    """Group trials into the tables a report needs: by defence, and by OWASP."""
    by_defense: Dict[str, List[TrialResult]] = {}
    by_defense_owasp: Dict[str, Dict[str, List[TrialResult]]] = {}
    for t in trials:
        by_defense.setdefault(t.defense, []).append(t)
        by_defense_owasp.setdefault(t.defense, {}).setdefault(t.owasp, []).append(t)
    return {
        "by_defense": {d: _rate_block(ts) for d, ts in by_defense.items()},
        "by_defense_owasp": {
            d: {o: _rate_block(ts) for o, ts in cats.items()}
            for d, cats in by_defense_owasp.items()
        },
    }


def run_suite(
    attacks_path: Path,
    victim: Victim,
    defenses: Sequence[str],
    trials: int = 1,
    seed: int = 7,
    base_dir: Optional[Path] = None,
    corpus_dir: str = "datasets/docs",
    vectors: Optional[Sequence[str]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    attacks = select(load_attacks(attacks_path), vectors=vectors)
    if not attacks:
        raise ValueError("no attacks selected")
    stacks = [build_defense(spec) for spec in defenses]
    base = Path(base_dir) if base_dir else Path.cwd()
    retriever = _Retriever(base, corpus_dir, _rag_retrieval_cfg())
    # A deterministic victim gains nothing from repeats; force one trial each.
    effective_trials = 1 if victim.deterministic else max(1, trials)

    results: List[TrialResult] = []
    total = len(attacks) * len(stacks) * effective_trials
    done = 0
    started = time.time()
    for attack in attacks:
        for stack in stacks:
            for trial in range(effective_trials):
                results.append(run_trial(attack, stack, victim, trial, seed, retriever))
                done += 1
                if progress:
                    progress(done, total)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "security",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "victim": {"name": victim.name, "model": victim.model,
                   "deterministic": victim.deterministic},
        "seed": seed,
        "trials_per_cell": effective_trials,
        "attack_corpus": corpus_fingerprint(attacks),
        "attack_count": len(attacks),
        "defenses": [s.name for s in stacks],
        "duration_s": round(time.time() - started, 2),
        "summary": summarise(results),
        "trials_detail": [t.to_dict() for t in results],
    }


def _rag_retrieval_cfg():  # noqa: ANN202
    from ragprobe.config import RetrievalConfig
    return RetrievalConfig(embedder="tfidf", top_k=4)
