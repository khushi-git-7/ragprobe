"""Regression diffing - comparing a run against a saved baseline.

This is the feature the rest of the project exists to support.

A prompt edit is a code change. It ships to production, it changes user-visible
behaviour, and it can break things that are nowhere near the line you edited. Yet
the normal workflow is to tweak a prompt, eyeball three examples, and merge. The
equivalent in application code would be editing a function, running it once in a
REPL, and pushing to main.

``diff_runs`` gives that change the same treatment a code change gets: a known-good
baseline, a re-run, and an explicit list of what moved. The gate then fails the
build when too much moved in the wrong direction.

**Comparison validity.** Before reporting anything, the diff checks that the two
runs are actually comparable - same dataset, same config except for the thing you
changed, deterministic provider. When they are not, it says so loudly. A regression
report that compares a stub run against a live-model run is not a regression report,
it is noise with a percentage sign on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: Score changes smaller than this are treated as flat. Guards against float noise.
DEFAULT_EPSILON = 0.01

STATUS_REGRESSED = "regressed"  # passed -> failed. A break. Gated by default.
STATUS_DEGRADED = "degraded"  # still passing, but the score slid. A warning by default.
STATUS_IMPROVED = "improved"
STATUS_FLAT = "flat"
STATUS_NEW = "new"
STATUS_REMOVED = "removed"


@dataclass
class CaseDiff:
    """How one case changed between baseline and current."""

    id: str
    status: str
    question: str = ""
    category: str = "general"
    baseline_passed: Optional[bool] = None
    current_passed: Optional[bool] = None
    baseline_score: Optional[float] = None
    current_score: Optional[float] = None
    score_delta: Optional[float] = None
    #: Checks that went pass -> fail, and fail -> pass.
    newly_failing: List[str] = field(default_factory=list)
    newly_passing: List[str] = field(default_factory=list)
    baseline_answer: str = ""
    current_answer: str = ""
    retrieval_delta: Dict[str, Optional[float]] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "question": self.question,
            "category": self.category,
            "baseline_passed": self.baseline_passed,
            "current_passed": self.current_passed,
            "baseline_score": self.baseline_score,
            "current_score": self.current_score,
            "score_delta": (round(self.score_delta, 4) if self.score_delta is not None else None),
            "newly_failing": self.newly_failing,
            "newly_passing": self.newly_passing,
            "baseline_answer": self.baseline_answer,
            "current_answer": self.current_answer,
            "retrieval_delta": self.retrieval_delta,
            "reason": self.reason,
        }


@dataclass
class GateResult:
    ok: bool
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "reasons": self.reasons}


@dataclass
class DiffReport:
    """The full comparison between two runs."""

    cases: List[CaseDiff]
    baseline_summary: Dict[str, Any]
    current_summary: Dict[str, Any]
    #: Non-fatal problems that make the comparison less trustworthy.
    warnings: List[str] = field(default_factory=list)
    baseline_meta: Dict[str, Any] = field(default_factory=dict)
    current_meta: Dict[str, Any] = field(default_factory=dict)

    def of_status(self, status: str) -> List[CaseDiff]:
        return [case for case in self.cases if case.status == status]

    @property
    def regressed(self) -> List[CaseDiff]:
        return self.of_status(STATUS_REGRESSED)

    @property
    def degraded(self) -> List[CaseDiff]:
        return self.of_status(STATUS_DEGRADED)

    @property
    def improved(self) -> List[CaseDiff]:
        return self.of_status(STATUS_IMPROVED)

    @property
    def flat(self) -> List[CaseDiff]:
        return self.of_status(STATUS_FLAT)

    @property
    def new(self) -> List[CaseDiff]:
        return self.of_status(STATUS_NEW)

    @property
    def removed(self) -> List[CaseDiff]:
        return self.of_status(STATUS_REMOVED)

    def counts(self) -> Dict[str, int]:
        return {
            STATUS_REGRESSED: len(self.regressed),
            STATUS_DEGRADED: len(self.degraded),
            STATUS_IMPROVED: len(self.improved),
            STATUS_FLAT: len(self.flat),
            STATUS_NEW: len(self.new),
            STATUS_REMOVED: len(self.removed),
        }

    # ------------------------------------------------------------------ gate

    def gate(
        self,
        max_regressions: int = 0,
        max_degraded: Optional[int] = None,
        min_pass_rate: Optional[float] = None,
        max_mean_score_drop: Optional[float] = None,
        fail_on_removed: bool = True,
    ) -> GateResult:
        """Decide whether this diff should fail the build.

        Defaults to ``max_regressions=0``: any case that goes from passing to
        failing breaks the build. That is the right default for a gate. Teams who
        need a softer landing can raise it, but they should do so explicitly and in
        version control, not by ignoring a red build.

        Score-only slides (``degraded``) are *not* gated unless ``max_degraded`` is
        set. A prompt edit that shaves 0.03 off every score without failing anything
        is worth a warning and a look; failing the build on it by default trains
        people to raise the epsilon until the gate is meaningless.
        """
        reasons: List[str] = []

        degraded = self.degraded
        if max_degraded is not None and len(degraded) > max_degraded:
            names = ", ".join(case.id for case in degraded[:5])
            more = "" if len(degraded) <= 5 else f" (+{len(degraded) - 5} more)"
            reasons.append(
                f"{len(degraded)} degraded case(s) exceeds the limit of "
                f"{max_degraded}: {names}{more}"
            )

        regressed = self.regressed
        if len(regressed) > max_regressions:
            names = ", ".join(case.id for case in regressed[:5])
            more = "" if len(regressed) <= 5 else f" (+{len(regressed) - 5} more)"
            reasons.append(
                f"{len(regressed)} regressed case(s) exceeds the limit of "
                f"{max_regressions}: {names}{more}"
            )

        if min_pass_rate is not None:
            current_rate = float(self.current_summary.get("pass_rate") or 0.0)
            if current_rate < min_pass_rate:
                reasons.append(
                    f"pass rate {current_rate:.1%} is below the required {min_pass_rate:.1%}"
                )

        if max_mean_score_drop is not None:
            baseline_score = float(self.baseline_summary.get("mean_score") or 0.0)
            current_score = float(self.current_summary.get("mean_score") or 0.0)
            drop = baseline_score - current_score
            if drop > max_mean_score_drop:
                reasons.append(
                    f"mean score dropped {drop:.4f}, which exceeds the allowed "
                    f"{max_mean_score_drop:.4f}"
                )

        if fail_on_removed and self.removed:
            names = ", ".join(case.id for case in self.removed[:5])
            reasons.append(
                f"{len(self.removed)} case(s) present in the baseline are missing from this "
                f"run: {names}. Deleting a failing test is not a fix."
            )

        return GateResult(ok=not reasons, reasons=reasons)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "counts": self.counts(),
            "warnings": self.warnings,
            "baseline": {"summary": self.baseline_summary, "meta": self.baseline_meta},
            "current": {"summary": self.current_summary, "meta": self.current_meta},
            "cases": [case.to_dict() for case in self.cases],
        }


# ------------------------------------------------------------------ internals


def _index_cases(run: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {str(case.get("id")): case for case in run.get("cases", [])}


def _failed_check_names(case: Mapping[str, Any]) -> set:
    names = set()
    for check in case.get("checks", []) or []:
        if check.get("applicable", True) and not check.get("passed", True):
            names.add(str(check.get("name")))
    return names


def _meta(run: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "provider": run.get("provider"),
        "deterministic": run.get("deterministic"),
        "config_fingerprint": run.get("config_fingerprint"),
        "dataset_fingerprint": run.get("dataset_fingerprint"),
        "started_at": run.get("started_at"),
        "ragprobe_version": run.get("ragprobe_version"),
    }


def _validity_warnings(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> List[str]:
    warnings: List[str] = []

    if baseline.get("dataset_fingerprint") != current.get("dataset_fingerprint"):
        warnings.append(
            "Dataset fingerprints differ: the golden set changed between these runs. "
            "Per-case results are still comparable, but aggregate deltas are not."
        )
    if baseline.get("config_fingerprint") == current.get("config_fingerprint"):
        warnings.append(
            "Config fingerprints are identical. If you expected a config or prompt "
            "change to be under test, it did not take effect."
        )
    if baseline.get("provider") != current.get("provider"):
        warnings.append(
            f"Provider changed ({baseline.get('provider')} -> {current.get('provider')}). "
            "Differences are dominated by the provider swap, not by your change."
        )
    if not (baseline.get("deterministic", True) and current.get("deterministic", True)):
        warnings.append(
            "At least one run used a nondeterministic provider. Re-running the same "
            "commit can produce a different diff; do not read small deltas as signal."
        )
    if baseline.get("schema_version") != current.get("schema_version"):
        warnings.append(
            "Results schema versions differ; the baseline may predate a harness change."
        )
    return warnings


def _retrieval_delta(
    baseline: Mapping[str, Any], current: Mapping[str, Any]
) -> Dict[str, Optional[float]]:
    base_metrics = baseline.get("retrieval") or {}
    current_metrics = current.get("retrieval") or {}
    delta: Dict[str, Optional[float]] = {}
    for key in sorted(set(base_metrics) | set(current_metrics)):
        before, after = base_metrics.get(key), current_metrics.get(key)
        delta[key] = round(after - before, 4) if before is not None and after is not None else None
    return delta


def diff_runs(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    epsilon: float = DEFAULT_EPSILON,
) -> DiffReport:
    """Compare two results documents.

    Classification, in priority order:

    * ``regressed`` - the case went from passing to failing. A break.
    * ``improved``  - the case went from failing to passing, or its score rose by
      more than ``epsilon``.
    * ``degraded``  - still passing, but the score dropped by more than ``epsilon``.
      A slide: the case is on its way to breaking and nobody has noticed yet.
    * ``flat``      - none of the above.
    * ``new`` / ``removed`` - the case exists on only one side.

    Pass/fail transitions dominate score movement, because crossing the threshold is
    categorically more important than drifting within it. Keeping ``degraded``
    separate from ``regressed`` is what lets the default gate be strict about breaks
    without being noisy about drift.
    """
    baseline_cases = _index_cases(baseline)
    current_cases = _index_cases(current)

    diffs: List[CaseDiff] = []

    for case_id in current_cases:
        current_case = current_cases[case_id]
        if case_id not in baseline_cases:
            diffs.append(
                CaseDiff(
                    id=case_id,
                    status=STATUS_NEW,
                    question=str(current_case.get("question", "")),
                    category=str(current_case.get("category", "general")),
                    current_passed=bool(current_case.get("passed")),
                    current_score=current_case.get("score"),
                    current_answer=str(current_case.get("answer", "")),
                    reason="case is not present in the baseline",
                )
            )
            continue

        baseline_case = baseline_cases[case_id]
        base_passed = bool(baseline_case.get("passed"))
        curr_passed = bool(current_case.get("passed"))
        base_score = float(baseline_case.get("score") or 0.0)
        curr_score = float(current_case.get("score") or 0.0)
        delta = curr_score - base_score

        base_failed = _failed_check_names(baseline_case)
        curr_failed = _failed_check_names(current_case)

        if base_passed and not curr_passed:
            status = STATUS_REGRESSED
            reason = "case went from passing to failing"
        elif not base_passed and curr_passed:
            status = STATUS_IMPROVED
            reason = "case went from failing to passing"
        elif delta < -epsilon:
            status = STATUS_DEGRADED
            reason = f"score dropped by {abs(delta):.4f} (threshold {epsilon}) but still passing"
        elif delta > epsilon:
            status = STATUS_IMPROVED
            reason = f"score rose by {delta:.4f} (threshold {epsilon})"
        else:
            status = STATUS_FLAT
            reason = "no material change"

        diffs.append(
            CaseDiff(
                id=case_id,
                status=status,
                question=str(current_case.get("question", "")),
                category=str(current_case.get("category", "general")),
                baseline_passed=base_passed,
                current_passed=curr_passed,
                baseline_score=base_score,
                current_score=curr_score,
                score_delta=delta,
                newly_failing=sorted(curr_failed - base_failed),
                newly_passing=sorted(base_failed - curr_failed),
                baseline_answer=str(baseline_case.get("answer", "")),
                current_answer=str(current_case.get("answer", "")),
                retrieval_delta=_retrieval_delta(baseline_case, current_case),
                reason=reason,
            )
        )

    for case_id, baseline_case in baseline_cases.items():
        if case_id not in current_cases:
            diffs.append(
                CaseDiff(
                    id=case_id,
                    status=STATUS_REMOVED,
                    question=str(baseline_case.get("question", "")),
                    category=str(baseline_case.get("category", "general")),
                    baseline_passed=bool(baseline_case.get("passed")),
                    baseline_score=baseline_case.get("score"),
                    baseline_answer=str(baseline_case.get("answer", "")),
                    reason="case is in the baseline but missing from this run",
                )
            )

    # Regressions first: the report should lead with what broke.
    order = {
        STATUS_REGRESSED: 0,
        STATUS_REMOVED: 1,
        STATUS_DEGRADED: 2,
        STATUS_IMPROVED: 3,
        STATUS_NEW: 4,
        STATUS_FLAT: 5,
    }
    diffs.sort(key=lambda case: (order.get(case.status, 9), case.id))

    return DiffReport(
        cases=diffs,
        baseline_summary=dict(baseline.get("summary") or {}),
        current_summary=dict(current.get("summary") or {}),
        warnings=_validity_warnings(baseline, current),
        baseline_meta=_meta(baseline),
        current_meta=_meta(current),
    )
