"""Tests for the dashboard: the data model, the insight rules, the SVG charts and
the rendered page.

The model and the insights are pinned to hand-computed values from small synthetic
runs, because a dashboard that confidently shows the wrong number is worse than no
dashboard. The page tests check the properties that make the file usable as a CI
artifact: well-formed, self-contained, and safe against hostile strings.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import pytest

from ragprobe.dashboard import analytics, insights as insights_mod, svg
from ragprobe.dashboard.analytics import (
    ATTRIBUTION_ERROR,
    ATTRIBUTION_GENERATION,
    ATTRIBUTION_MIXED,
    ATTRIBUTION_REFUSAL,
    ATTRIBUTION_RETRIEVAL,
    ATTRIBUTION_UNKNOWN,
    attribute_failure,
    build_model,
    case_histories,
    category_breakdown,
    check_outcomes,
    config_changes,
    flatten,
    kpi_tiles,
    normalise_retrieval,
    score_histogram,
)
from ragprobe.dashboard.html import render_dashboard
from ragprobe.dashboard.insights import generate_insights
from ragprobe.regression.diff import STATUS_FLAT, STATUS_IMPROVED, STATUS_REGRESSED

# ------------------------------------------------------------------ fixtures


def make_check(name: str, passed: bool, applicable: bool = True, advisory: bool = False) -> Dict[str, Any]:
    return {
        "name": name, "passed": passed, "applicable": applicable, "score": 1.0 if passed else 0.0,
        "detail": "", "metadata": {"advisory": True} if advisory else {},
    }


def make_case(
    case_id: str,
    passed: bool = True,
    score: float = 1.0,
    category: str = "general",
    failed_checks: Optional[List[str]] = None,
    recall: Optional[float] = 1.0,
    hit: Optional[float] = 1.0,
    expected_chunks: Optional[List[str]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    failed = failed_checks or []
    checks = [
        make_check("keyword_presence", "keyword_presence" not in failed),
        make_check("forbidden_absent", "forbidden_absent" not in failed),
        make_check("fuzzy_match", "fuzzy_match" not in failed, advisory=True),
        make_check("citation_present", True, applicable=False),
    ]
    return {
        "id": case_id, "question": f"question for {case_id}", "category": category,
        "answer": f"answer for {case_id}", "passed": passed, "score": score, "checks": checks,
        "failed_checks": failed,
        "retrieval": {"precision@3": 0.333, "recall@3": recall, "hit_rate@3": hit, "reciprocal_rank": 1.0},
        "retrieved": [{"chunk_id": "doc#a", "rank": 1, "score": 0.5, "text": "text"}],
        "expected_chunks": ["doc#a"] if expected_chunks is None else expected_chunks,
        "faithfulness": {}, "error": error,
        "golden": {"expected_answer": None, "required_keywords": ["x"], "forbidden_keywords": [], "should_refuse": False, "notes": ""},
    }


def make_run(
    cases: List[Dict[str, Any]],
    started_at: str = "2026-01-01T00:00:00Z",
    fingerprint: str = "cfg-a",
    config: Optional[Dict[str, Any]] = None,
    dataset_fingerprint: str = "data-a",
    deterministic: bool = True,
    top_k: int = 3,
) -> Dict[str, Any]:
    passed = sum(1 for c in cases if c["passed"])
    by_category: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        bucket = by_category.setdefault(case["category"], {"total": 0, "passed": 0, "scores": []})
        bucket["total"] += 1
        bucket["passed"] += int(case["passed"])
        bucket["scores"].append(case["score"])
    for bucket in by_category.values():
        bucket["pass_rate"] = bucket["passed"] / bucket["total"]
        bucket["mean_score"] = sum(bucket["scores"]) / len(bucket["scores"])
        del bucket["scores"]
    recalls = [c["retrieval"]["recall@3"] for c in cases if c["retrieval"]["recall@3"] is not None]
    return {
        "schema_version": 1, "ragprobe_version": "0.1.0", "started_at": started_at,
        "provider": "stub", "deterministic": deterministic,
        "config_fingerprint": fingerprint, "dataset_fingerprint": dataset_fingerprint,
        "config": config or {"generation": {"max_sentences": 2, "prompt_version": "v1"}, "retrieval": {"top_k": top_k},
                             "evaluation": {"required_checks": ["keyword_presence", "forbidden_absent", "citation_present"]}},
        "pipeline": {"documents": 5, "chunks": 29},
        "summary": {
            "total": len(cases), "passed": passed, "failed": len(cases) - passed,
            "pass_rate": passed / len(cases) if cases else 0.0,
            "mean_score": sum(c["score"] for c in cases) / len(cases) if cases else 0.0,
            "retrieval": {f"precision@{top_k}": 0.333, f"recall@{top_k}": sum(recalls) / len(recalls) if recalls else None,
                          f"hit_rate@{top_k}": 1.0, "mrr": 0.9},
            "by_category": dict(sorted(by_category.items())),
        },
        "cases": cases,
        "metadata": {},
    }


# ------------------------------------------------------------------ analytics


class TestUtilities:
    def test_flatten_uses_dotted_keys(self):
        assert flatten({"a": {"b": 1, "c": {"d": 2}}, "e": [1, 2]}) == {"a.b": 1, "a.c.d": 2, "e": [1, 2]}

    def test_config_changes_lists_only_differences(self):
        before = {"generation": {"max_sentences": 2, "prompt_version": "v1"}}
        after = {"generation": {"max_sentences": 1, "prompt_version": "v1"}, "retrieval": {"top_k": 5}}
        assert config_changes(before, after) == [
            "generation.max_sentences: 2 -> 1",
            "retrieval.top_k: - -> 5",
        ]

    def test_normalise_retrieval_maps_k_suffixed_keys_to_families(self):
        out = normalise_retrieval({"precision@5": 0.2, "recall@5": 1.0, "hit_rate@5": 1.0, "mrr": 0.9})
        assert out["precision"] == ("precision@5", 0.2)
        assert out["mrr"] == ("mrr", 0.9)
        assert normalise_retrieval({}) == {}


class TestRunPointsAndKpis:
    def test_config_change_is_detected_with_details(self):
        runs = [
            make_run([make_case("a")], "2026-01-01T00:00:00Z", "cfg-a"),
            make_run([make_case("a")], "2026-01-01T00:01:00Z", "cfg-b",
                     config={"generation": {"max_sentences": 1, "prompt_version": "v1"}, "retrieval": {"top_k": 3}}),
        ]
        points = analytics.build_run_points(runs)
        assert points[0].config_changed is False
        assert points[1].config_changed is True
        assert points[1].changes == ["evaluation.required_checks: ['keyword_presence', 'forbidden_absent', 'citation_present'] -> -",
                                     "generation.max_sentences: 2 -> 1"]

    def test_dataset_change_is_detected(self):
        runs = [make_run([make_case("a")], dataset_fingerprint="d1"), make_run([make_case("a")], dataset_fingerprint="d2")]
        assert analytics.build_run_points(runs)[1].dataset_changed is True

    def test_kpi_delta_and_sentiment(self):
        runs = [
            make_run([make_case("a"), make_case("b", passed=False, score=0.5)]),
            make_run([make_case("a"), make_case("b")]),
        ]
        tiles = {k.key: k for k in kpi_tiles(analytics.build_run_points(runs))}
        assert tiles["pass_rate"].value == 1.0
        assert tiles["pass_rate"].previous == 0.5
        assert tiles["pass_rate"].delta == pytest.approx(0.5)
        assert tiles["pass_rate"].sentiment == "good"
        assert tiles["pass_rate"].direction == "up"
        assert tiles["pass_rate"].series == [0.5, 1.0]
        assert tiles["cases"].sentiment == "neutral"  # a count is not a verdict

    def test_kpi_with_single_run_has_no_delta(self):
        tiles = kpi_tiles(analytics.build_run_points([make_run([make_case("a")])]))
        assert all(t.delta is None and t.direction == "none" for t in tiles)

    def test_falling_metric_is_bad(self):
        runs = [make_run([make_case("a")]), make_run([make_case("a", passed=False, score=0.2)])]
        tiles = {k.key: k for k in kpi_tiles(analytics.build_run_points(runs))}
        assert tiles["mean_score"].sentiment == "bad"

    def test_retrieval_kpi_label_follows_latest_k_and_notes_the_change(self):
        runs = [make_run([make_case("a")], top_k=3), make_run([make_case("a")], top_k=5, fingerprint="cfg-b")]
        tiles = {k.key: k for k in kpi_tiles(analytics.build_run_points(runs))}
        assert tiles["precision"].label == "Precision@5"
        assert "k changed" in tiles["precision"].note
        assert tiles["mrr"].label == "MRR"


class TestBreakdowns:
    def test_categories_sorted_worst_first(self):
        run = make_run([
            make_case("a", category="good"), make_case("b", category="bad", passed=False, score=0.1),
            make_case("c", category="mid"), make_case("d", category="mid", passed=False, score=0.4),
        ])
        stats = category_breakdown(run)
        assert [s.name for s in stats] == ["bad", "mid", "good"]
        assert stats[0].failed == 1 and stats[0].pass_rate == 0.0

    def test_previous_pass_rate_is_attached(self):
        previous = make_run([make_case("a", category="x", passed=False, score=0.1)])
        current = make_run([make_case("a", category="x")])
        assert category_breakdown(current, previous)[0].previous_pass_rate == 0.0

    def test_check_outcomes_count_pass_fail_skip_and_rank_by_failures(self):
        run = make_run([
            make_case("a", passed=False, failed_checks=["keyword_presence"]),
            make_case("b", passed=False, failed_checks=["keyword_presence", "fuzzy_match"]),
            make_case("c"),
        ])
        outcomes = {o.name: o for o in check_outcomes(run)}
        assert outcomes["keyword_presence"].failed == 2 and outcomes["keyword_presence"].passed == 1
        assert outcomes["citation_present"].skipped == 3
        assert outcomes["citation_present"].fail_rate is None
        assert outcomes["fuzzy_match"].advisory is True
        assert outcomes["keyword_presence"].advisory is False
        assert check_outcomes(run)[0].name == "keyword_presence"

    def test_histogram_bins_and_top_edge(self):
        run = make_run([make_case("a", score=1.0), make_case("b", score=0.95), make_case("c", score=0.0), make_case("d", score=0.55)])
        bins = score_histogram(run, bins=10)
        assert len(bins) == 10
        assert bins[9].count == 2 and set(bins[9].cases) == {"a", "b"}
        assert bins[0].count == 1
        assert bins[5].count == 1
        assert sum(b.count for b in bins) == 4

    def test_histogram_rejects_bad_bin_count(self):
        with pytest.raises(ValueError):
            score_histogram(make_run([]), bins=0)


class TestCaseHistories:
    def test_flips_are_split_by_whether_config_changed(self):
        runs = [
            make_run([make_case("a")], "2026-01-01T00:00:00Z", "cfg-a"),
            make_run([make_case("a", passed=False, score=0.2)], "2026-01-01T00:01:00Z", "cfg-a"),  # flaky flip
            make_run([make_case("a")], "2026-01-01T00:02:00Z", "cfg-b"),  # flip across config change
            make_run([make_case("a")], "2026-01-01T00:03:00Z", "cfg-b"),
        ]
        points = analytics.build_run_points(runs)
        history = case_histories(runs, points)["a"]
        assert history.flips_same_config == 1
        assert history.flips_config_change == 1
        assert history.flips == 2
        assert history.scores == [1.0, 0.2, 1.0, 1.0]

    def test_absent_runs_are_gaps_not_flips(self):
        runs = [
            make_run([make_case("a")]),
            make_run([make_case("b")]),
            make_run([make_case("a")]),
        ]
        history = case_histories(runs, analytics.build_run_points(runs))["a"]
        assert history.scores == [1.0, None, 1.0]
        assert history.flips == 0
        assert history.runs_present == 2


class TestAttribution:
    def test_generation_when_retrieval_is_perfect(self):
        case = make_case("a", passed=False, failed_checks=["forbidden_absent"], recall=1.0)
        result = attribute_failure(case)
        assert result.kind == ATTRIBUTION_GENERATION
        assert "forbidden_absent" in result.reason

    def test_retrieval_when_nothing_expected_was_retrieved(self):
        case = make_case("a", passed=False, failed_checks=["keyword_presence"], recall=0.0, hit=0.0)
        assert attribute_failure(case).kind == ATTRIBUTION_RETRIEVAL

    def test_refusal_when_case_has_no_expected_chunks(self):
        case = make_case("a", passed=False, failed_checks=["refusal_behaviour"], recall=None, hit=None, expected_chunks=[])
        assert attribute_failure(case).kind == ATTRIBUTION_REFUSAL

    def test_mixed_when_retrieval_is_partial(self):
        case = make_case("a", passed=False, failed_checks=["keyword_presence"], recall=0.5, hit=1.0)
        assert attribute_failure(case).kind == ATTRIBUTION_MIXED

    def test_error_wins_over_everything(self):
        case = make_case("a", passed=False, error="RuntimeError: boom")
        assert attribute_failure(case).kind == ATTRIBUTION_ERROR

    def test_missing_retrieval_metrics_are_not_called_partial(self):
        """A results file with no retrieval block must not be reported as "retrieval was partial"."""
        case = make_case("a", passed=False, failed_checks=["keyword_presence"])
        case["retrieval"] = {}
        result = attribute_failure(case)
        assert result.kind == ATTRIBUTION_UNKNOWN
        assert "partial" not in result.reason


class TestBuildModel:
    def test_requires_at_least_one_run(self):
        with pytest.raises(ValueError):
            build_model([])

    def test_change_status_uses_baseline_when_given(self):
        baseline = make_run([make_case("a"), make_case("b", passed=False, score=0.3)])
        current = make_run([make_case("a", passed=False, score=0.3), make_case("b")], fingerprint="cfg-b")
        model = build_model([current], baseline=baseline)
        rows = {r.id: r for r in model.rows}
        assert rows["a"].change_status == STATUS_REGRESSED
        assert rows["b"].change_status == STATUS_IMPROVED
        assert model.comparison_label == "baseline"
        assert model.diff is not None and model.gate is not None and model.gate.ok is False

    def test_change_status_falls_back_to_previous_run(self):
        runs = [make_run([make_case("a")]), make_run([make_case("a", passed=False, score=0.1)])]
        model = build_model(runs)
        assert model.rows[0].change_status == STATUS_REGRESSED
        assert model.comparison_label == "previous run"
        assert model.rows[0].score_delta_prev == pytest.approx(-0.9)

    def test_single_run_has_no_comparison(self):
        model = build_model([make_run([make_case("a")])])
        assert model.rows[0].change_status is None
        assert model.comparison_label == ""
        assert model.rows[0].attribution is None


# ------------------------------------------------------------------ insights


def _model(runs, baseline=None):
    return build_model(runs, baseline=baseline)


class TestInsights:
    def test_worst_category_names_the_failing_cases(self):
        model = _model([make_run([make_case("a", category="x"), make_case("b", category="y", passed=False, score=0.2)])])
        insight = insights_mod.worst_category(model)
        assert insight.title == "Weakest category: y"
        assert insight.cases == ["b"]
        assert insight.severity == "bad"  # 0% pass rate
        assert "Rule:" in insight.rule

    def test_all_passing_is_a_good_finding(self):
        insight = insights_mod.worst_category(_model([make_run([make_case("a")])]))
        assert insight.severity == "good"

    def test_a_run_with_no_cases_is_not_reported_as_all_passing(self):
        model = _model([make_run([])])
        assert model.categories == [] and model.rows == []
        insight = insights_mod.worst_category(model)
        assert insight.severity == "info" and "no cases" in insight.title
        assert insights_mod.attribution(model) is None
        assert not any("every case" in i.body.lower() for i in generate_insights(model))

    def test_missing_category_summary_yields_no_category_finding(self):
        run = make_run([make_case("a")])
        del run["summary"]["by_category"]
        assert insights_mod.worst_category(_model([run])) is None

    def test_most_common_failing_check_prefers_required_checks(self):
        model = _model([make_run([
            make_case("a", passed=False, failed_checks=["keyword_presence", "fuzzy_match"]),
            make_case("b", passed=True, failed_checks=["fuzzy_match"]),
        ])])
        insight = insights_mod.most_common_failing_check(model)
        assert "keyword_presence" in insight.title
        assert insight.cases == ["a"]

    def test_only_advisory_failures_are_informational(self):
        model = _model([make_run([make_case("a", passed=True, failed_checks=["fuzzy_match"])])])
        insight = insights_mod.most_common_failing_check(model)
        assert insight.severity == "info" and "advisory" in insight.title

    def test_flakiness_needs_three_runs(self):
        model = _model([make_run([make_case("a")]), make_run([make_case("a", passed=False, score=0.1)])])
        assert "Not enough history" in insights_mod.flaky_cases(model).title

    def test_flaky_case_under_identical_config_is_bad(self):
        runs = [
            make_run([make_case("a")], "2026-01-01T00:00:00Z"),
            make_run([make_case("a", passed=False, score=0.1)], "2026-01-01T00:01:00Z"),
            make_run([make_case("a")], "2026-01-01T00:02:00Z"),
        ]
        insight = insights_mod.flaky_cases(_model(runs))
        assert insight.severity == "bad" and insight.cases == ["a"]

    def test_config_sensitive_case_is_not_called_flaky(self):
        runs = [
            make_run([make_case("a")], "2026-01-01T00:00:00Z", "cfg-a"),
            make_run([make_case("a", passed=False, score=0.1)], "2026-01-01T00:01:00Z", "cfg-b"),
            make_run([make_case("a")], "2026-01-01T00:02:00Z", "cfg-c"),
        ]
        insight = insights_mod.flaky_cases(_model(runs))
        assert insight.severity == "info" and "config-sensitive" in insight.title

    def test_largest_drops_needs_a_baseline(self):
        assert insights_mod.largest_drops(_model([make_run([make_case("a")])])) is None

    def test_largest_drops_ranks_and_flags_regressions(self):
        baseline = make_run([make_case("a"), make_case("b"), make_case("c")])
        current = make_run([make_case("a", passed=False, score=0.2), make_case("b", score=0.9), make_case("c")], fingerprint="cfg-b")
        insight = insights_mod.largest_drops(_model([current], baseline))
        assert insight.cases == ["a", "b"]
        assert insight.severity == "bad"
        assert "1 of them crossed" in insight.body

    def test_attribution_summary_counts_each_kind(self):
        run = make_run([
            make_case("gen", passed=False, failed_checks=["forbidden_absent"], recall=1.0),
            make_case("gen2", passed=False, failed_checks=["forbidden_absent"], recall=1.0),
            make_case("ret", passed=False, failed_checks=["keyword_presence"], recall=0.0, hit=0.0),
        ])
        insight = insights_mod.attribution(_model([run]))
        assert insight.title == "Most failures point at generation"
        assert "2 a generation problem" in insight.body
        assert "1 a retrieval problem" in insight.body

    def test_attribution_headline_is_absolute_only_when_every_failure_agrees(self):
        run = make_run([make_case("gen", passed=False, failed_checks=["forbidden_absent"], recall=1.0)])
        assert insights_mod.attribution(_model([run])).title == "Failures point at generation, not retrieval"
        run = make_run([make_case("ret", passed=False, failed_checks=["keyword_presence"], recall=0.0, hit=0.0)])
        assert insights_mod.attribution(_model([run])).title == "Failures point at retrieval, not generation"

    def test_attribution_tie_is_reported_as_a_split(self):
        run = make_run([
            make_case("gen", passed=False, failed_checks=["forbidden_absent"], recall=1.0),
            make_case("ret", passed=False, failed_checks=["keyword_presence"], recall=0.0, hit=0.0),
        ])
        insight = insights_mod.attribution(_model([run]))
        assert insight.title == "Failures split evenly between generation and retrieval"

    def test_pass_rate_trend_counts_the_streak(self):
        runs = [
            make_run([make_case("a"), make_case("b"), make_case("c")], "2026-01-01T00:00:00Z"),
            make_run([make_case("a"), make_case("b"), make_case("c", passed=False, score=0.1)], "2026-01-01T00:01:00Z"),
            make_run([make_case("a"), make_case("b", passed=False, score=0.1), make_case("c", passed=False, score=0.1)], "2026-01-01T00:02:00Z"),
        ]
        insight = insights_mod.pass_rate_trend(_model(runs))
        assert "fallen for 2 consecutive" in insight.title
        assert insight.severity == "bad"

    def test_config_change_insight_reports_the_settings_that_moved(self):
        runs = [
            make_run([make_case("a")], "2026-01-01T00:00:00Z", "cfg-a"),
            make_run([make_case("a", passed=False, score=0.1)], "2026-01-01T00:01:00Z", "cfg-b",
                     config={"generation": {"max_sentences": 1, "prompt_version": "v1"}, "retrieval": {"top_k": 3},
                             "evaluation": {"required_checks": ["keyword_presence", "forbidden_absent", "citation_present"]}}),
        ]
        insight = insights_mod.latest_config_change(_model(runs))
        assert "generation.max_sentences: 2 -> 1" in insight.body
        assert "fell" in insight.body and insight.severity == "warn"

    def test_advisory_disagreement_lists_passing_cases_with_advisory_failures(self):
        model = _model([make_run([make_case("a", passed=True, failed_checks=["fuzzy_match"]), make_case("b")])])
        insight = insights_mod.advisory_disagreement(model)
        assert insight.cases == ["a"]

    def test_nondeterminism_warning(self):
        assert insights_mod.nondeterminism_warning(_model([make_run([make_case("a")])])) is None
        insight = insights_mod.nondeterminism_warning(_model([make_run([make_case("a")], deterministic=False)]))
        assert insight.severity == "warn"

    def test_generate_insights_sorts_worst_first(self):
        baseline = make_run([make_case("a"), make_case("b")])
        current = make_run([make_case("a", passed=False, score=0.1), make_case("b")], fingerprint="cfg-b")
        findings = generate_insights(_model([current], baseline))
        order = {"bad": 0, "warn": 1, "info": 2, "good": 3}
        severities = [order[i.severity] for i in findings]
        assert severities == sorted(severities)
        assert all(i.rule.startswith("Rule:") for i in findings)


# ------------------------------------------------------------------ svg


class TestSvg:
    def test_sparkline_breaks_at_gaps_and_marks_the_last_point(self):
        out = svg.sparkline([0.5, None, 0.9, 1.0])
        assert out.count("M") == 2  # two segments
        assert '<circle class="spark-dot' in out
        assert svg.sparkline([]).count("path") == 0
        assert svg.sparkline([None, None]).count("path") == 0

    def test_line_chart_embeds_data_and_annotations(self):
        out = svg.line_chart([0.8, 0.9, 0.85], ["r1", "r2", "r3"], fmt="percent", series="Pass rate",
                             annotations=[{"index": 1, "kind": "config", "text": "max_sentences 2 -> 1"}])
        assert 'data-chart="' in out
        assert "c-annot-mark config" in out
        assert "max_sentences 2 -&gt; 1" in out
        assert out.count('class="c-dot"') == 3
        assert "85.0%" in out  # the one direct label: the last point

    def test_line_chart_handles_missing_and_single_values(self):
        assert '<path class="c-line"' not in svg.line_chart([None, 0.5], ["a", "b"])
        single = svg.line_chart([0.5], ["a"])
        assert '<circle class="c-dot"' in single

    def test_line_chart_drops_area_wash_on_zoomed_axis(self):
        zoomed = svg.line_chart([0.85, 0.9], ["a", "b"], fmt="percent")
        assert "c-area" not in zoomed
        from_zero = svg.line_chart([0.0, 0.9], ["a", "b"], fmt="percent")
        assert "c-area" in from_zero

    def test_rounded_bar_paths(self):
        assert svg._rounded_hbar(0, 0, 0, 10) == ""
        assert svg._rounded_hbar(0, 0, 50, 10).startswith("M0,0 h46 a4,4")
        assert svg._rounded_vbar(0, 0, 20, 0) == ""

    def test_hbar_chart_clamps_values_and_escapes_tips(self):
        out = svg.hbar_chart([{"label": "a<b", "value": 1.5, "tip": "x\"y"}, {"label": "c", "value": None, "tip": ""}])
        assert "a&lt;b" in out and "x&quot;y" in out
        assert "n/a" in out

    def test_stacked_hbar_and_histogram_render(self):
        stacked = svg.stacked_hbar([{"label": "chk", "segments": [{"label": "fail", "count": 1, "cls": "fail"}, {"label": "pass", "count": 3, "cls": "pass"}]}])
        assert stacked.count('class="c-seg"') == 2
        hist = svg.histogram([{"label": "0.0", "count": 0, "tip": ""}, {"label": "0.9", "count": 5, "tip": "five"}])
        assert hist.count('class="c-col"') == 2 and ">5<" in hist
        assert "Nothing to plot" in svg.histogram([])

    def test_formatters(self):
        assert svg.fmt_value(0.875, "percent") == "87.5%"
        assert svg.fmt_delta(-0.0125, "percent") == "-1.2 pts"
        assert svg.fmt_value(None, "score") == "n/a"
        assert svg.fmt_delta(3, "count") == "+3"


# ------------------------------------------------------------------ html


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
         "path", "circle", "line", "rect"}


class _Balance(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: List[str] = []
        self.errors: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unbalanced </{tag}> at {self.getpos()}")
        else:
            self.stack.pop()


def assert_well_formed(page: str) -> None:
    parser = _Balance()
    parser.feed(page)
    assert not parser.errors, parser.errors[:5]
    assert not parser.stack, parser.stack[:5]


class TestRenderDashboard:
    def test_page_has_every_section_and_is_self_contained(self):
        baseline = make_run([make_case("a"), make_case("b")])
        runs = [
            make_run([make_case("a"), make_case("b")], "2026-01-01T00:00:00Z", "cfg-a"),
            make_run([make_case("a"), make_case("b", passed=False, score=0.2, failed_checks=["forbidden_absent"])],
                     "2026-01-01T00:01:00Z", "cfg-b"),
        ]
        page = render_dashboard(build_model(runs, baseline=baseline), title="Test dash")
        assert page.lstrip().startswith("<!DOCTYPE html>")
        for section in ("overview", "trends", "breakdown", "cases", "regression", "insights"):
            assert f'<section id="{section}"' in page
        for marker in ("http://", "https://", "cdn.", "<link "):
            assert marker not in page
        assert page.count("<svg") > 10
        assert "prefers-color-scheme: dark" in page and 'data-theme="dark"' in page
        assert_well_formed(page)

    def test_page_without_baseline_shows_empty_regression_state(self):
        page = render_dashboard(build_model([make_run([make_case("a")])]))
        assert "No baseline to compare against" in page
        assert_well_formed(page)

    def test_hostile_strings_are_escaped_everywhere(self):
        evil = '<script>alert("x")</script>'
        case = make_case("a", passed=False, score=0.1, failed_checks=["keyword_presence"], category=evil)
        case["question"] = evil
        case["answer"] = evil
        case["retrieved"][0]["text"] = evil
        case["golden"]["notes"] = evil
        run = make_run([case], fingerprint=evil)
        run["config"]["generation"]["prompt_version"] = evil
        previous = make_run([make_case("a")], "2025-12-31T00:00:00Z", "cfg-0")
        page = render_dashboard(build_model([previous, run]))
        assert evil not in page
        assert "&lt;script&gt;" in page
        assert_well_formed(page)

    def test_case_rows_carry_filter_and_sort_data(self):
        baseline = make_run([make_case("a"), make_case("b", passed=False, score=0.2)])
        current = make_run([make_case("a", passed=False, score=0.2, category="sec"), make_case("b")], fingerprint="cfg-b")
        page = render_dashboard(build_model([current], baseline=baseline))
        assert 'data-id="a" data-status="fail regressed"' in page
        assert 'data-id="b" data-status="pass improved"' in page
        assert 'data-category="sec"' in page
        assert 'data-filter="regressed"' in page

    def test_navigation_only_routes_to_section_ids(self):
        """Charts and widgets have ids too (``trend-pass_rate``, ``tooltip``). A URL hash naming
        one of those used to satisfy the "does this id exist" check and hide every panel."""
        page = render_dashboard(build_model([make_run([make_case("a")])]))
        assert "hasOwnProperty.call(titles, section)" in page
        assert "document.getElementById(section)" not in page
        assert 'id="trend-pass_rate"' in page  # the collision that motivated the guard

    def test_insight_rules_are_rendered_as_tooltips(self):
        page = render_dashboard(build_model([make_run([make_case("a")])]))
        assert 'class="rule-btn"' in page and 'title="Rule:' in page

    def test_a_run_with_no_cases_renders(self):
        page = render_dashboard(build_model([make_run([]), make_run([], "2026-01-02T00:00:00Z")]))
        assert "0 cases, bins of 0.1" in page
        assert "Nothing to plot" in page
        assert_well_formed(page)

    def test_minimal_foreign_document_renders(self):
        """Only ``summary`` and ``cases`` are required; everything else is optional."""
        run = {"started_at": "2026-01-02T00:00:00Z", "summary": {"total": 1, "passed": 1, "failed": 0},
               "cases": [{"id": "x", "passed": True}]}
        page = render_dashboard(build_model([run, dict(run)], baseline=run))
        assert 'data-id="x"' in page
        assert_well_formed(page)

    def test_older_results_without_golden_block_still_render(self):
        case = make_case("a")
        del case["golden"]
        del case["failed_checks"]
        page = render_dashboard(build_model([make_run([case])]))
        assert "were not recorded" in page
        assert_well_formed(page)
