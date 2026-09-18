"""Faithfulness judging: the heuristic screen plus an optional LLM judge.

RAGProbe runs *both* and reports them separately rather than blending them into one
number. Blending would hide the single most useful signal in the whole report: the
cases where the cheap deterministic check and the expensive model check **disagree**.
Those are where the interesting bugs live, and where your evaluator itself needs
work.

Read the "Known weaknesses of LLM-as-judge" section of the README before treating a
judge score as ground truth. Short version: it is a measurement instrument with its
own bias and its own variance, and it has not been calibrated against your data
until you have checked it against human labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ragprobe.evaluation.evaluators import CheckResult
from ragprobe.evaluation.grounding import GroundingResult, score_grounding
from ragprobe.providers.base import ContextChunk, JudgeRequest, JudgeVerdict, LLMProvider


@dataclass
class FaithfulnessReport:
    """Combined output of the heuristic and (optionally) the LLM judge."""

    heuristic: GroundingResult
    judge: Optional[JudgeVerdict] = None

    @property
    def disagreement(self) -> Optional[float]:
        """Absolute gap between the two scores, or ``None`` if the judge did not run.

        Surfaced in the HTML report. A large gap on a case means one of your two
        evaluators is wrong about it, and you should look at that case by hand.
        """
        if self.judge is None:
            return None
        return abs(self.heuristic.score - self.judge.score)

    def to_dict(self) -> dict:
        return {
            "heuristic": self.heuristic.to_dict(),
            "judge": self.judge.to_dict() if self.judge else None,
            "disagreement": (
                round(self.disagreement, 4) if self.disagreement is not None else None
            ),
        }


def assess_faithfulness(
    question: str,
    answer: str,
    contexts: Sequence[ContextChunk],
    provider: Optional[LLMProvider] = None,
    claim_threshold: float = 0.50,
    grounding_threshold: float = 0.55,
    run_judge: bool = True,
) -> FaithfulnessReport:
    """Run the heuristic grounding check and, if enabled, the LLM judge."""
    context_text = "\n\n".join(item.text for item in contexts)
    heuristic = score_grounding(
        answer,
        context_text,
        claim_threshold=claim_threshold,
        grounding_threshold=grounding_threshold,
    )

    verdict: Optional[JudgeVerdict] = None
    if run_judge and provider is not None:
        verdict = provider.judge_faithfulness(
            JudgeRequest(question=question, answer=answer, contexts=list(contexts))
        )
    return FaithfulnessReport(heuristic=heuristic, judge=verdict)


def grounding_check(report: FaithfulnessReport, threshold: float, is_refusal: bool) -> CheckResult:
    """Turn the heuristic grounding score into a pass/fail check.

    Skipped for refusals: a refusal is *supposed* to contain wording that appears
    nowhere in the retrieved context, so scoring its groundedness would fail every
    correctly-refusing case. The refusal check covers that behaviour instead.
    """
    if is_refusal:
        return CheckResult(
            name="grounding",
            passed=True,
            score=0.0,
            detail="skipped: refusals are not grounded in retrieved text by design",
            applicable=False,
        )

    result = report.heuristic
    unsupported: List[str] = [claim.text for claim in result.unsupported_claims]
    passed = result.score >= threshold and not unsupported
    if passed:
        detail = f"all {len(result.claims)} claim(s) grounded (score {result.score:.2f})"
    elif unsupported:
        detail = f"{len(unsupported)} unsupported claim(s): {unsupported[0][:90]}"
    else:
        detail = f"grounding score {result.score:.2f} below threshold {threshold:.2f}"

    return CheckResult(
        name="grounding",
        passed=passed,
        score=result.score,
        detail=detail,
        metadata={
            "unsupported_claims": unsupported,
            "claim_count": len(result.claims),
        },
    )


def judge_check(report: FaithfulnessReport, is_refusal: bool) -> CheckResult:
    """Report the LLM judge verdict as an **advisory** check.

    Advisory on purpose. Gating a build on a nondeterministic evaluator produces
    flaky CI, and flaky CI gets ignored or disabled, which costs you the checks that
    did work. The judge informs; the deterministic checks gate.
    """
    if report.judge is None:
        return CheckResult(
            name="llm_judge_faithfulness",
            passed=True,
            score=0.0,
            detail="skipped: judge disabled",
            applicable=False,
        )
    if is_refusal:
        return CheckResult(
            name="llm_judge_faithfulness",
            passed=True,
            score=0.0,
            detail="skipped: refusal case",
            applicable=False,
        )
    verdict = report.judge
    return CheckResult(
        name="llm_judge_faithfulness",
        passed=verdict.grounded,
        score=verdict.score,
        detail=verdict.rationale or ("grounded" if verdict.grounded else "not grounded"),
        metadata={
            "unsupported_claims": verdict.unsupported_claims,
            "provider": verdict.provider,
            "deterministic": verdict.deterministic,
            "advisory": True,
        },
    )
