"""Unit tests for the regression diff and the CI gate.

The diff decides whether a build goes red. If it under-reports, broken prompts ship.
If it over-reports, the gate gets disabled and then nothing is protected. Both
directions are tested.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from ragprobe.regression.diff import (
    STATUS_DEGRADED,
    STATUS_FLAT,
    STATUS_IMPROVED,
    STATUS_NEW,
    STATUS_REGRESSED,
    STATUS_REMOVED,
    diff_runs,
)


def make_case(
    case_id: str,
    passed: bool,
    score: float,
    failed_checks: Optional[List[str]] = None,
    answer: str = "",
    retrieval: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    checks = [{"name": "keyword_presence", "passed": True, "applicable": True, "score": 1.0}]
    for name in failed_checks or []:
        checks.append({"name": name, "passed": False, "applicable": True, "score": 0.0})
    return {
        "id": case_id,
        "question": f"question for {case_id}",
        "category": "general",
        "passed": passed,
        "score": score,
        "answer": answer,
        "checks": checks,
        "retrieval": retrieval or {"precision@3": 0.333, "recall@3": 1.0},
    }


def make_run(cases: List[Dict[str, Any]], **overrides: Any) -> Dict[str, Any]:
    passed = sum(1 for case in cases if case["passed"])
    run = {
        "schema_version": 1,
        "provider": "stub",
        "deterministic": True,
        "config_fingerprint": "cfg-aaa",
        "dataset_fingerprint": "data-aaa",
        "started_at": "2026-01-01T00:00:00Z",
        "summary": {
            "total": len(cases),
            "passed": passed,
            "failed": len(cases) - passed,
            "pass_rate": passed / len(cases) if cases else 0.0,
            "mean_score": sum(c["score"] for c in cases) / len(cases) if cases else 0.0,
        },
        "cases": cases,
    }
    run.update(overrides)
    return run


class TestStatusClassification:
    def test_pass_to_fail_is_a_regression(self):
        baseline = make_run([make_case("a", True, 1.0)])
        current = make_run([make_case("a", False, 0.4, failed_checks=["grounding"])])
        report = diff_runs(baseline, current)
        assert report.counts()[STATUS_REGRESSED] == 1
        assert report.regressed[0].newly_failing == ["grounding"]

    def test_fail_to_pass_is_an_improvement(self):
        baseline = make_run([make_case("a", False, 0.4, failed_checks=["grounding"])])
        current = make_run([make_case("a", True, 1.0)])
        report = diff_runs(baseline, current)
        assert report.counts()[STATUS_IMPROVED] == 1
        assert report.improved[0].newly_passing == ["grounding"]

    def test_identical_runs_are_flat(self):
        baseline = make_run([make_case("a", True, 1.0)])
        current = make_run([make_case("a", True, 1.0)])
        report = diff_runs(baseline, current)
        assert report.counts()[STATUS_FLAT] == 1
        assert report.counts()[STATUS_REGRESSED] == 0

    def test_score_drop_beyond_epsilon_is_degraded_not_regressed(self):
        """A slide is reported distinctly from a break.

        Catching the slide before it becomes a break is the point of score deltas;
        keeping it out of the ``regressed`` bucket is what keeps the default gate
        strict without being noisy.
        """
        baseline = make_run([make_case("a", True, 0.95)])
        current = make_run([make_case("a", True, 0.60)])
        report = diff_runs(baseline, current, epsilon=0.01)
        assert report.counts()[STATUS_DEGRADED] == 1
        assert report.counts()[STATUS_REGRESSED] == 0
        assert report.degraded[0].score_delta == pytest.approx(-0.35)

    def test_score_noise_within_epsilon_is_flat(self):
        baseline = make_run([make_case("a", True, 0.900)])
        current = make_run([make_case("a", True, 0.895)])
        assert diff_runs(baseline, current, epsilon=0.01).counts()[STATUS_FLAT] == 1

    def test_score_rise_beyond_epsilon_improves(self):
        baseline = make_run([make_case("a", True, 0.60)])
        current = make_run([make_case("a", True, 0.95)])
        assert diff_runs(baseline, current).counts()[STATUS_IMPROVED] == 1

    def test_pass_fail_flip_beats_score_movement(self):
        """A case that fails must be a regression even if its score went up."""
        baseline = make_run([make_case("a", True, 0.10)])
        current = make_run([make_case("a", False, 0.90)])
        report = diff_runs(baseline, current)
        assert report.counts()[STATUS_REGRESSED] == 1

    def test_new_case(self):
        baseline = make_run([make_case("a", True, 1.0)])
        current = make_run([make_case("a", True, 1.0), make_case("b", True, 1.0)])
        report = diff_runs(baseline, current)
        assert report.counts()[STATUS_NEW] == 1
        assert report.new[0].id == "b"

    def test_removed_case(self):
        baseline = make_run([make_case("a", True, 1.0), make_case("b", True, 1.0)])
        current = make_run([make_case("a", True, 1.0)])
        report = diff_runs(baseline, current)
        assert report.counts()[STATUS_REMOVED] == 1
        assert report.removed[0].id == "b"

    def test_regressions_are_listed_first(self):
        baseline = make_run(
            [make_case("z-flat", True, 1.0), make_case("a-broken", True, 1.0)]
        )
        current = make_run(
            [make_case("z-flat", True, 1.0), make_case("a-broken", False, 0.2)]
        )
        report = diff_runs(baseline, current)
        assert report.cases[0].status == STATUS_REGRESSED


class TestRetrievalDelta:
    def test_reports_per_metric_delta(self):
        baseline = make_run([make_case("a", True, 1.0, retrieval={"recall@3": 1.0})])
        current = make_run([make_case("a", True, 1.0, retrieval={"recall@3": 0.5})])
        delta = diff_runs(baseline, current).cases[0].retrieval_delta
        assert delta["recall@3"] == pytest.approx(-0.5)

    def test_undefined_metric_yields_none_delta(self):
        baseline = make_run([make_case("a", True, 1.0, retrieval={"recall@3": None})])
        current = make_run([make_case("a", True, 1.0, retrieval={"recall@3": 1.0})])
        assert diff_runs(baseline, current).cases[0].retrieval_delta["recall@3"] is None


class TestGate:
    def test_default_gate_fails_on_any_regression(self):
        baseline = make_run([make_case("a", True, 1.0)])
        current = make_run([make_case("a", False, 0.2)])
        gate = diff_runs(baseline, current).gate()
        assert not gate.ok
        assert "regressed" in gate.reasons[0]

    def test_gate_passes_when_nothing_regressed(self):
        baseline = make_run([make_case("a", True, 1.0)])
        current = make_run([make_case("a", True, 1.0)])
        assert diff_runs(baseline, current).gate().ok

    def test_tolerance_allows_a_budgeted_regression(self):
        baseline = make_run([make_case("a", True, 1.0)])
        current = make_run([make_case("a", False, 0.2)])
        assert diff_runs(baseline, current).gate(max_regressions=1).ok

    def test_tolerance_is_exclusive_above_the_budget(self):
        baseline = make_run([make_case("a", True, 1.0), make_case("b", True, 1.0)])
        current = make_run([make_case("a", False, 0.2), make_case("b", False, 0.2)])
        assert not diff_runs(baseline, current).gate(max_regressions=1).ok

    def test_min_pass_rate_gate(self):
        baseline = make_run([make_case("a", True, 1.0), make_case("b", True, 1.0)])
        current = make_run([make_case("a", True, 1.0), make_case("b", False, 0.2)])
        gate = diff_runs(baseline, current).gate(max_regressions=99, min_pass_rate=0.9)
        assert not gate.ok
        assert "pass rate" in gate.reasons[0]

    def test_max_score_drop_gate(self):
        baseline = make_run([make_case("a", True, 1.0)])
        current = make_run([make_case("a", True, 0.5)])
        gate = diff_runs(baseline, current).gate(max_regressions=99, max_mean_score_drop=0.1)
        assert not gate.ok
        assert "mean score" in gate.reasons[0]

    def test_degraded_cases_do_not_fail_the_default_gate(self):
        baseline = make_run([make_case("a", True, 0.95)])
        current = make_run([make_case("a", True, 0.60)])
        assert diff_runs(baseline, current).gate().ok

    def test_degraded_cases_can_be_gated_explicitly(self):
        baseline = make_run([make_case("a", True, 0.95)])
        current = make_run([make_case("a", True, 0.60)])
        gate = diff_runs(baseline, current).gate(max_degraded=0)
        assert not gate.ok
        assert "degraded" in gate.reasons[0]

    def test_degraded_is_listed_before_improved(self):
        baseline = make_run([make_case("up", True, 0.5), make_case("down", True, 0.9)])
        current = make_run([make_case("up", True, 0.9), make_case("down", True, 0.5)])
        statuses = [case.status for case in diff_runs(baseline, current).cases]
        assert statuses == [STATUS_DEGRADED, STATUS_IMPROVED]

    def test_deleting_a_case_fails_the_gate(self):
        """Deleting a failing test is not a fix, and the gate should say so."""
        baseline = make_run([make_case("a", True, 1.0), make_case("b", True, 1.0)])
        current = make_run([make_case("a", True, 1.0)])
        gate = diff_runs(baseline, current).gate()
        assert not gate.ok
        assert any("missing from this run" in reason for reason in gate.reasons)

    def test_removal_can_be_explicitly_allowed(self):
        baseline = make_run([make_case("a", True, 1.0), make_case("b", True, 1.0)])
        current = make_run([make_case("a", True, 1.0)])
        assert diff_runs(baseline, current).gate(fail_on_removed=False).ok

    def test_gate_collects_every_reason(self):
        baseline = make_run([make_case("a", True, 1.0), make_case("b", True, 1.0)])
        current = make_run([make_case("a", False, 0.1)])
        gate = diff_runs(baseline, current).gate(min_pass_rate=0.99)
        assert len(gate.reasons) >= 2


class TestComparisonValidityWarnings:
    def test_warns_when_dataset_changed(self):
        baseline = make_run([make_case("a", True, 1.0)], dataset_fingerprint="data-aaa")
        current = make_run([make_case("a", True, 1.0)], dataset_fingerprint="data-bbb")
        report = diff_runs(baseline, current)
        assert any("Dataset fingerprints differ" in warning for warning in report.warnings)

    def test_warns_when_config_did_not_change(self):
        """If you meant to test a prompt change and the fingerprint is identical,
        the change did not take effect - that is worth shouting about."""
        baseline = make_run([make_case("a", True, 1.0)], config_fingerprint="same")
        current = make_run([make_case("a", True, 1.0)], config_fingerprint="same")
        report = diff_runs(baseline, current)
        assert any("Config fingerprints are identical" in w for w in report.warnings)

    def test_no_config_warning_when_config_changed(self):
        baseline = make_run([make_case("a", True, 1.0)], config_fingerprint="cfg-a")
        current = make_run([make_case("a", True, 1.0)], config_fingerprint="cfg-b")
        report = diff_runs(baseline, current)
        assert not any("Config fingerprints are identical" in w for w in report.warnings)

    def test_warns_when_provider_changed(self):
        baseline = make_run([make_case("a", True, 1.0)], provider="stub")
        current = make_run([make_case("a", True, 1.0)], provider="anthropic")
        report = diff_runs(baseline, current)
        assert any("Provider changed" in warning for warning in report.warnings)

    def test_warns_on_nondeterministic_run(self):
        baseline = make_run([make_case("a", True, 1.0)])
        current = make_run([make_case("a", True, 1.0)], deterministic=False)
        report = diff_runs(baseline, current)
        assert any("nondeterministic" in warning for warning in report.warnings)


class TestSerialisation:
    def test_report_is_json_serialisable(self):
        import json

        baseline = make_run([make_case("a", True, 1.0)])
        current = make_run([make_case("a", False, 0.2)])
        report = diff_runs(baseline, current)
        payload = {**report.to_dict(), "gate": report.gate().to_dict()}
        assert json.loads(json.dumps(payload))["counts"][STATUS_REGRESSED] == 1
