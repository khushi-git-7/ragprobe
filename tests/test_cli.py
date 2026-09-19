"""End-to-end CLI tests.

These exercise the workflow the README promises: run -> baseline -> change
something -> diff -> non-zero exit. If this file passes, the headline feature works.
Everything runs offline against the stub provider.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ragprobe.cli import EXIT_GATE_FAILED, EXIT_OK, EXIT_USAGE, main


@pytest.fixture
def workspace(tmp_path: Path, project_root: Path) -> Path:
    """An isolated copy of the project's data files, so tests never write into the repo."""
    shutil.copytree(project_root / "datasets", tmp_path / "datasets")
    shutil.copy(project_root / "ragprobe.yaml", tmp_path / "ragprobe.yaml")
    return tmp_path


def _run(workspace: Path, out: Path, *extra: str) -> int:
    return main(
        [
            "run",
            "--root", str(workspace),
            "--config", str(workspace / "ragprobe.yaml"),
            "--out", str(out),
            "--quiet",
            *extra,
        ]
    )


class TestRunCommand:
    def test_run_writes_results_and_exits_zero(self, workspace, tmp_path):
        out = tmp_path / "results.json"
        assert _run(workspace, out) == EXIT_OK
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["summary"]["total"] >= 10
        assert payload["provider"] == "stub"
        assert payload["deterministic"] is True

    def test_results_contain_per_case_detail(self, workspace, tmp_path):
        out = tmp_path / "results.json"
        _run(workspace, out)
        case = json.loads(out.read_text(encoding="utf-8"))["cases"][0]
        assert {"id", "answer", "checks", "retrieval", "retrieved", "passed"} <= set(case)

    def test_run_is_reproducible(self, workspace, tmp_path):
        """Two runs of the same commit must produce byte-identical case results.

        This is the property the whole regression gate rests on.
        """
        first, second = tmp_path / "a.json", tmp_path / "b.json"
        _run(workspace, first)
        _run(workspace, second)
        left = json.loads(first.read_text(encoding="utf-8"))
        right = json.loads(second.read_text(encoding="utf-8"))
        assert left["cases"] == right["cases"]
        assert left["config_fingerprint"] == right["config_fingerprint"]

    def test_html_report_is_written_and_self_contained(self, workspace, tmp_path):
        out, html = tmp_path / "results.json", tmp_path / "report.html"
        _run(workspace, out, "--html", str(html))
        assert html.exists()
        content = html.read_text(encoding="utf-8")
        assert content.lstrip().startswith("<!DOCTYPE html>")
        assert "<style>" in content
        # No external resource may be referenced, or the report breaks offline.
        for marker in ("http://", "https://", "cdn."):
            assert marker not in content, f"report references an external resource: {marker}"

    def test_fail_under_gate_trips(self, workspace, tmp_path):
        out = tmp_path / "results.json"
        assert _run(workspace, out, "--fail-under", "1.0") == EXIT_GATE_FAILED

    def test_fail_under_gate_passes_when_satisfied(self, workspace, tmp_path):
        out = tmp_path / "results.json"
        assert _run(workspace, out, "--fail-under", "0.5") == EXIT_OK

    def test_top_k_override_changes_the_fingerprint(self, workspace, tmp_path):
        default_out, wide_out = tmp_path / "d.json", tmp_path / "w.json"
        _run(workspace, default_out)
        _run(workspace, wide_out, "--top-k", "5")
        default = json.loads(default_out.read_text(encoding="utf-8"))
        wide = json.loads(wide_out.read_text(encoding="utf-8"))
        assert default["config_fingerprint"] != wide["config_fingerprint"]
        assert wide["config"]["retrieval"]["top_k"] == 5


class TestBaselineCommand:
    def test_baseline_is_written(self, workspace, tmp_path):
        baseline = tmp_path / "baseline.json"
        code = main(
            [
                "baseline",
                "--root", str(workspace),
                "--config", str(workspace / "ragprobe.yaml"),
                "--out", str(baseline),
                "--quiet",
            ]
        )
        assert code == EXIT_OK
        assert json.loads(baseline.read_text(encoding="utf-8"))["deterministic"] is True

    def test_baseline_can_promote_an_existing_results_file(self, workspace, tmp_path):
        results, baseline = tmp_path / "results.json", tmp_path / "baseline.json"
        _run(workspace, results)
        code = main(
            ["baseline", "--from-results", str(results), "--out", str(baseline), "--quiet"]
        )
        assert code == EXIT_OK
        assert json.loads(baseline.read_text(encoding="utf-8")) == json.loads(
            results.read_text(encoding="utf-8")
        )

    def test_refuses_a_nondeterministic_baseline(self, workspace, tmp_path):
        """Recording a baseline from a live model would produce phantom regressions."""
        results, baseline = tmp_path / "results.json", tmp_path / "baseline.json"
        _run(workspace, results)
        payload = json.loads(results.read_text(encoding="utf-8"))
        payload["deterministic"] = False
        results.write_text(json.dumps(payload), encoding="utf-8")

        code = main(
            ["baseline", "--from-results", str(results), "--out", str(baseline), "--quiet"]
        )
        assert code == EXIT_USAGE
        assert not baseline.exists()

    def test_nondeterministic_baseline_can_be_forced(self, workspace, tmp_path):
        results, baseline = tmp_path / "results.json", tmp_path / "baseline.json"
        _run(workspace, results)
        payload = json.loads(results.read_text(encoding="utf-8"))
        payload["deterministic"] = False
        results.write_text(json.dumps(payload), encoding="utf-8")

        code = main(
            [
                "baseline", "--from-results", str(results), "--out", str(baseline),
                "--allow-nondeterministic", "--quiet",
            ]
        )
        assert code == EXIT_OK


class TestDiffCommand:
    def test_identical_run_passes_the_gate(self, workspace, tmp_path):
        baseline = tmp_path / "baseline.json"
        _run(workspace, baseline)
        code = main(
            [
                "diff",
                "--root", str(workspace),
                "--config", str(workspace / "ragprobe.yaml"),
                "--baseline", str(baseline),
                "--quiet",
            ]
        )
        assert code == EXIT_OK

    def test_config_change_that_breaks_cases_fails_the_gate(self, workspace, tmp_path):
        """The headline scenario: a config change regresses cases and CI goes red.

        Dropping ``max_sentences`` to 1 removes supporting sentences from answers,
        so multi-fact cases stop satisfying their required keywords.
        """
        baseline = tmp_path / "baseline.json"
        _run(workspace, baseline)
        code = main(
            [
                "diff",
                "--root", str(workspace),
                "--config", str(workspace / "ragprobe.yaml"),
                "--baseline", str(baseline),
                "--max-sentences", "1",
                "--quiet",
            ]
        )
        assert code == EXIT_GATE_FAILED

    def test_diff_json_and_html_are_written(self, workspace, tmp_path):
        baseline = tmp_path / "baseline.json"
        diff_json, diff_html = tmp_path / "diff.json", tmp_path / "diff.html"
        _run(workspace, baseline)
        main(
            [
                "diff",
                "--root", str(workspace),
                "--config", str(workspace / "ragprobe.yaml"),
                "--baseline", str(baseline),
                "--json", str(diff_json),
                "--html", str(diff_html),
                "--max-sentences", "1",
                "--quiet",
            ]
        )
        payload = json.loads(diff_json.read_text(encoding="utf-8"))
        assert "counts" in payload and "gate" in payload
        assert payload["gate"]["ok"] is False
        assert diff_html.exists()

    def test_regression_budget_can_absorb_the_change(self, workspace, tmp_path):
        baseline = tmp_path / "baseline.json"
        _run(workspace, baseline)
        code = main(
            [
                "diff",
                "--root", str(workspace),
                "--config", str(workspace / "ragprobe.yaml"),
                "--baseline", str(baseline),
                "--max-sentences", "1",
                "--max-regressions", "99",
                "--quiet",
            ]
        )
        assert code == EXIT_OK

    def test_missing_baseline_is_a_usage_error_not_a_gate_failure(self, workspace, tmp_path):
        code = main(
            [
                "diff",
                "--root", str(workspace),
                "--config", str(workspace / "ragprobe.yaml"),
                "--baseline", str(tmp_path / "nope.json"),
                "--quiet",
            ]
        )
        assert code == EXIT_USAGE


class TestReportCommand:
    def test_renders_from_stored_json(self, workspace, tmp_path):
        results, html = tmp_path / "results.json", tmp_path / "report.html"
        _run(workspace, results)
        code = main(["report", "--results", str(results), "--out", str(html)])
        assert code == EXIT_OK
        assert "RAGProbe" in html.read_text(encoding="utf-8")

    def test_renders_a_diff_section_when_given_a_baseline(self, workspace, tmp_path):
        baseline, current, html = (
            tmp_path / "base.json",
            tmp_path / "curr.json",
            tmp_path / "report.html",
        )
        _run(workspace, baseline)
        _run(workspace, current, "--max-sentences", "1")
        main(
            [
                "report",
                "--results", str(current),
                "--baseline", str(baseline),
                "--out", str(html),
            ]
        )
        content = html.read_text(encoding="utf-8")
        assert "Regression diff" in content


class TestErrorHandling:
    def test_bad_config_is_a_usage_error(self, tmp_path):
        config = tmp_path / "bad.yaml"
        config.write_text("retrieval:\n  nonsense_key: 1\n", encoding="utf-8")
        assert main(["run", "--config", str(config), "--quiet"]) == EXIT_USAGE

    def test_missing_corpus_is_a_usage_error(self, workspace, tmp_path):
        assert (
            _run(workspace, tmp_path / "out.json", "--corpus", "does/not/exist") == EXIT_USAGE
        )

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])
        assert excinfo.value.code == 0


class TestRunHistory:
    def test_run_appends_to_history_under_root(self, workspace, tmp_path):
        """A relative --history-dir resolves against --root, so the scratch copy gets it."""
        _run(workspace, tmp_path / "a.json")
        _run(workspace, tmp_path / "b.json", "--max-sentences", "1")
        files = sorted((workspace / "reports" / "history").glob("run-*.json"))
        assert len(files) == 2
        assert files[0].name.startswith("run-0001-") and files[1].name.startswith("run-0002-")
        assert json.loads(files[1].read_text(encoding="utf-8"))["config"]["generation"]["max_sentences"] == 1

    def test_no_history_flag_skips_recording(self, workspace, tmp_path):
        _run(workspace, tmp_path / "a.json", "--no-history")
        assert not (workspace / "reports" / "history").exists()

    def test_explicit_history_dir(self, workspace, tmp_path):
        history = tmp_path / "elsewhere"
        _run(workspace, tmp_path / "a.json", "--history-dir", str(history))
        assert len(list(history.glob("run-*.json"))) == 1

    def test_results_carry_the_golden_assertions(self, workspace, tmp_path):
        out = tmp_path / "results.json"
        _run(workspace, out)
        case = json.loads(out.read_text(encoding="utf-8"))["cases"][0]
        assert {"expected_answer", "required_keywords", "forbidden_keywords", "should_refuse", "notes"} <= set(case["golden"])

    def test_diff_also_records_history_when_it_runs_the_suite(self, workspace, tmp_path):
        baseline = tmp_path / "baseline.json"
        _run(workspace, baseline, "--no-history")
        main([
            "diff", "--root", str(workspace), "--config", str(workspace / "ragprobe.yaml"),
            "--baseline", str(baseline), "--quiet",
        ])
        assert len(list((workspace / "reports" / "history").glob("run-*.json"))) == 1


class TestDashboardCommand:
    def _history(self, workspace, tmp_path):
        _run(workspace, tmp_path / "a.json")
        _run(workspace, tmp_path / "b.json", "--max-sentences", "1")
        _run(workspace, tmp_path / "c.json", "--prompt-version", "v2")
        return workspace / "reports" / "history"

    def test_renders_from_history_without_a_baseline(self, workspace, tmp_path):
        self._history(workspace, tmp_path)
        out = tmp_path / "dash.html"
        code = main(["dashboard", "--root", str(workspace), "--out", str(out)])
        assert code == EXIT_OK
        content = out.read_text(encoding="utf-8")
        assert "No baseline to compare against" in content
        assert '<section id="trends"' in content
        for marker in ("http://", "https://", "cdn."):
            assert marker not in content
        assert out.stat().st_size < 2 * 1024 * 1024

    def test_renders_the_regression_panel_with_a_baseline(self, workspace, tmp_path):
        history = self._history(workspace, tmp_path)
        out = tmp_path / "dash.html"
        code = main([
            "dashboard", "--history-dir", str(history), "--baseline", str(tmp_path / "a.json"),
            "--out", str(out), "--title", "My dash",
        ])
        assert code == EXIT_OK
        content = out.read_text(encoding="utf-8")
        assert "<title>My dash</title>" in content
        assert "Changed cases" in content
        assert "No baseline to compare against" not in content

    def test_results_flag_adds_a_run_not_in_history(self, workspace, tmp_path):
        history = self._history(workspace, tmp_path)
        extra = tmp_path / "extra.json"
        _run(workspace, extra, "--top-k", "5", "--no-history")
        out = tmp_path / "dash.html"
        main(["dashboard", "--history-dir", str(history), "--results", str(extra), "--out", str(out)])
        assert "4 stored run(s)" in out.read_text(encoding="utf-8")

    def test_limit_restricts_the_runs_used(self, workspace, tmp_path):
        history = self._history(workspace, tmp_path)
        out = tmp_path / "dash.html"
        main(["dashboard", "--history-dir", str(history), "--limit", "2", "--out", str(out)])
        assert "2 stored run(s)" in out.read_text(encoding="utf-8")

    def test_empty_history_is_a_usage_error(self, tmp_path):
        code = main(["dashboard", "--history-dir", str(tmp_path / "nothing"), "--out", str(tmp_path / "d.html")])
        assert code == EXIT_USAGE

    def test_corrupt_history_file_is_skipped_with_a_warning(self, workspace, tmp_path, capsys):
        history = self._history(workspace, tmp_path)
        (history / "run-0009-20260101T000000Z-bad.json").write_text("{", encoding="utf-8")
        out = tmp_path / "dash.html"
        assert main(["dashboard", "--history-dir", str(history), "--out", str(out)]) == EXIT_OK
        assert "Skipped run-0009" in capsys.readouterr().err
        assert "Skipped run-0009" in out.read_text(encoding="utf-8")
