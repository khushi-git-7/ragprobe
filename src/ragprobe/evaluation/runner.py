"""Suite orchestration: run every golden case and assemble a results document.

The results document is the unit of currency in RAGProbe. It is plain JSON, it is
stable under re-running in stub mode, and it carries enough provenance
(config fingerprint, dataset fingerprint, provider, determinism flag) that the diff
tool can tell you when a comparison is invalid instead of silently producing a
misleading answer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ragprobe import __version__
from ragprobe.config import ProbeConfig
from ragprobe.evaluation import metrics as metrics_mod
from ragprobe.evaluation.dataset import GoldenCase, dataset_fingerprint
from ragprobe.evaluation.evaluators import (
    CheckResult,
    citation_present,
    exact_match,
    expected_citation_overlap,
    forbidden_absent,
    fuzzy_match,
    keyword_presence,
    refusal_behaviour,
)
from ragprobe.evaluation.judge import assess_faithfulness, grounding_check, judge_check
from ragprobe.pipeline.rag import RagResult, RetrievedChunk
from ragprobe.targets import get_target

SCHEMA_VERSION = 1


@dataclass
class CaseResult:
    """Evaluation outcome for one golden case."""

    id: str
    question: str
    category: str
    answer: str
    refused: bool
    passed: bool
    score: float
    checks: List[CheckResult]
    retrieval: Dict[str, Optional[float]]
    retrieved: List[Dict[str, Any]]
    expected_chunks: List[str]
    faithfulness: Dict[str, Any]
    error: Optional[str] = None
    #: What the golden set asserted, copied into the results so a report can show
    #: "expected" next to "actual" without re-reading the dataset. Additive: older
    #: results files simply lack it.
    golden: Dict[str, Any] = field(default_factory=dict)

    @property
    def failed_checks(self) -> List[str]:
        return [check.name for check in self.checks if check.applicable and not check.passed]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "category": self.category,
            "answer": self.answer,
            "refused": self.refused,
            "passed": self.passed,
            "score": round(self.score, 4),
            "checks": [check.to_dict() for check in self.checks],
            "retrieval": {
                key: (round(value, 4) if value is not None else None)
                for key, value in self.retrieval.items()
            },
            "retrieved": self.retrieved,
            "expected_chunks": self.expected_chunks,
            "faithfulness": self.faithfulness,
            "failed_checks": self.failed_checks,
            "error": self.error,
            "golden": self.golden,
        }


@dataclass
class RunResult:
    """A complete suite run."""

    cases: List[CaseResult]
    config: Dict[str, Any]
    config_fingerprint: str
    dataset_fingerprint: str
    provider: str
    deterministic: bool
    pipeline_stats: Dict[str, Any]
    started_at: str
    duration_seconds: float
    ragprobe_version: str = __version__
    schema_version: int = SCHEMA_VERSION
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------- summaries

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for case in self.cases if case.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def mean_score(self) -> float:
        return sum(case.score for case in self.cases) / self.total if self.total else 0.0

    def aggregate_retrieval(self) -> Dict[str, Optional[float]]:
        return metrics_mod.aggregate_metrics([case.retrieval for case in self.cases])

    def by_category(self) -> Dict[str, Dict[str, Any]]:
        buckets: Dict[str, List[CaseResult]] = {}
        for case in self.cases:
            buckets.setdefault(case.category, []).append(case)
        return {
            category: {
                "total": len(items),
                "passed": sum(1 for item in items if item.passed),
                "pass_rate": sum(1 for item in items if item.passed) / len(items),
                "mean_score": sum(item.score for item in items) / len(items),
            }
            for category, items in sorted(buckets.items())
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
            "mean_score": round(self.mean_score, 4),
            "retrieval": {
                key: (round(value, 4) if value is not None else None)
                for key, value in self.aggregate_retrieval().items()
            },
            "by_category": self.by_category(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ragprobe_version": self.ragprobe_version,
            "started_at": self.started_at,
            "duration_seconds": round(self.duration_seconds, 3),
            "provider": self.provider,
            "deterministic": self.deterministic,
            "config_fingerprint": self.config_fingerprint,
            "dataset_fingerprint": self.dataset_fingerprint,
            "config": self.config,
            "pipeline": self.pipeline_stats,
            "summary": self.summary(),
            "cases": [case.to_dict() for case in self.cases],
            "metadata": self.metadata,
        }


def _golden_block(case: GoldenCase) -> Dict[str, Any]:
    return {
        "expected_answer": case.expected_answer,
        "required_keywords": list(case.required_keywords),
        "forbidden_keywords": list(case.forbidden_keywords),
        "should_refuse": bool(case.should_refuse),
        "notes": case.notes,
    }


def _score_case(checks: Sequence[CheckResult]) -> float:
    """Mean score over applicable checks.

    Skipped checks are excluded rather than counted as zero. Counting a skipped
    check as zero would punish a dataset case for not declaring an optional field,
    which would push authors towards padding cases with meaningless assertions.
    """
    applicable = [check for check in checks if check.applicable]
    if not applicable:
        return 0.0
    return sum(check.score for check in applicable) / len(applicable)


def evaluate_case(
    case: GoldenCase,
    result: RagResult,
    config: ProbeConfig,
    provider=None,
) -> CaseResult:
    """Apply every evaluator to one pipeline result."""
    eval_cfg = config.evaluation
    is_refusal = result.refused

    faithfulness = assess_faithfulness(
        question=case.question,
        answer=result.answer,
        contexts=[chunk.as_context() for chunk in result.retrieved],
        provider=provider if eval_cfg.judge_enabled else None,
        claim_threshold=eval_cfg.claim_support_threshold,
        grounding_threshold=eval_cfg.grounding_threshold,
        run_judge=eval_cfg.judge_enabled and not is_refusal,
    )

    checks: List[CheckResult] = [
        exact_match(result.answer, case.expected_answer),
        fuzzy_match(result.answer, case.expected_answer, eval_cfg.fuzzy_threshold),
        keyword_presence(result.answer, case.required_keywords),
        forbidden_absent(result.answer, case.forbidden_keywords),
        refusal_behaviour(result.answer, case.should_refuse),
        citation_present(
            result.answer,
            result.retrieved_ids,
            required=config.generation.include_citations,
            is_refusal=is_refusal,
        ),
        expected_citation_overlap(result.answer, case.expected_chunks),
        grounding_check(faithfulness, eval_cfg.grounding_threshold, is_refusal),
        judge_check(faithfulness, is_refusal),
    ]

    retrieval = metrics_mod.retrieval_metrics(
        result.retrieved_ids, case.expected_chunks, config.retrieval.top_k
    )

    # A case fails only on a *required* check. Everything else is advisory, so a
    # nondeterministic judge or a brittle exact-match cannot fail the build.
    required = set(eval_cfg.required_checks)
    passed = all(
        check.passed
        for check in checks
        if check.applicable and check.name in required
    )

    return CaseResult(
        id=case.id,
        question=case.question,
        category=case.category,
        answer=result.answer,
        refused=result.refused,
        passed=passed,
        score=_score_case(checks),
        checks=checks,
        retrieval=retrieval,
        retrieved=[chunk.to_dict() for chunk in result.retrieved],
        expected_chunks=list(case.expected_chunks),
        faithfulness=faithfulness.to_dict(),
        golden=_golden_block(case),
    )


def run_suite(
    cases: Sequence[GoldenCase],
    config: ProbeConfig,
    base_dir: Optional[Path] = None,
    pipeline: Optional[Any] = None,
    progress: Optional[Callable[[int, int, GoldenCase], None]] = None,
    target: Optional[Any] = None,
) -> RunResult:
    """Run the full golden set against a target and return a ``RunResult``.

    ``target`` is any ``ragprobe.targets.Target`` - the built-in pipeline by default,
    or an HTTP service / Python callable when ``config.target`` says so. ``pipeline``
    is the older name for the same parameter and still works.
    """
    started = time.time()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))

    pipeline = target or pipeline or get_target(config, base_dir=base_dir)
    pipeline.ingest()

    results: List[CaseResult] = []
    for index, case in enumerate(cases, start=1):
        if progress:
            progress(index, len(cases), case)
        try:
            rag_result = pipeline.answer(case.question)
            results.append(evaluate_case(case, rag_result, config, provider=pipeline.provider))
        except Exception as exc:  # noqa: BLE001 - one bad case must not kill the run
            # A crashed case is a failed case, not a crashed suite. Losing the other
            # 19 results because case 7 threw is how people stop trusting a harness.
            results.append(
                CaseResult(
                    id=case.id,
                    question=case.question,
                    category=case.category,
                    answer="",
                    refused=False,
                    passed=False,
                    score=0.0,
                    checks=[],
                    retrieval=metrics_mod.retrieval_metrics(
                        [], case.expected_chunks, config.retrieval.top_k
                    ),
                    retrieved=[],
                    expected_chunks=list(case.expected_chunks),
                    faithfulness={},
                    error=f"{type(exc).__name__}: {exc}",
                    golden=_golden_block(case),
                )
            )

    return RunResult(
        cases=results,
        config=config.to_dict(),
        config_fingerprint=config.fingerprint(),
        dataset_fingerprint=dataset_fingerprint(cases),
        provider=pipeline.provider_name,
        deterministic=pipeline.deterministic,
        pipeline_stats=pipeline.stats(),
        started_at=started_at,
        duration_seconds=time.time() - started,
    )


def rescore(
    payload: Mapping[str, Any],
    cases: Sequence[GoldenCase],
    config: Optional[ProbeConfig] = None,
) -> RunResult:
    """Re-run every evaluator over the answers saved in a results document.

    Live-model answers are expensive and nondeterministic; the evaluators are
    neither. When an evaluator is fixed or a threshold re-tuned, this re-scores the
    recorded answers and retrieved chunks without calling the model again, so the
    effect of the evaluator change can be measured on its own. The LLM judge is not
    re-run (it would need the model); the offline grounding heuristic is.
    """
    config = config or ProbeConfig.from_dict(payload.get("config") or {}, source="<results>")
    config = config.apply_overrides({"evaluation.judge_enabled": False})
    by_id = {case.id: case for case in cases}
    started = time.time()
    results: List[CaseResult] = []
    for saved in payload.get("cases", []):
        case = by_id.get(saved.get("id"))
        if case is None:
            continue  # the dataset no longer has this case; nothing to score against
        rag_result = RagResult(
            question=saved.get("question", case.question),
            answer=saved.get("answer", ""),
            refused=bool(saved.get("refused", False)),
            retrieved=[
                RetrievedChunk(
                    chunk_id=str(chunk.get("chunk_id", "")),
                    doc_id=str(chunk.get("doc_id", "")),
                    heading=str(chunk.get("heading", "")),
                    text=str(chunk.get("text", "")),
                    score=float(chunk.get("score", 0.0) or 0.0),
                    rank=int(chunk.get("rank", index)),
                )
                for index, chunk in enumerate(saved.get("retrieved", []), start=1)
            ],
            provider=str(payload.get("provider", "")),
            model=(saved.get("model") if isinstance(saved.get("model"), str) else None),
        )
        results.append(evaluate_case(case, rag_result, config, provider=None))
    metadata = dict(payload.get("metadata") or {})
    metadata["rescored_from"] = payload.get("started_at")
    return RunResult(
        cases=results,
        config=config.to_dict(),
        config_fingerprint=config.fingerprint(),
        dataset_fingerprint=dataset_fingerprint(cases),
        provider=str(payload.get("provider", "")),
        deterministic=bool(payload.get("deterministic", False)),
        pipeline_stats=dict(payload.get("pipeline") or {}),
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        duration_seconds=time.time() - started,
        metadata=metadata,
    )
