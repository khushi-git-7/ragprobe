"""``ragprobe rescore``: evaluators re-applied to saved answers, no model calls."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ragprobe.cli import EXIT_OK, main
from ragprobe.config import ProbeConfig
from ragprobe.evaluation.dataset import load_dataset
from ragprobe.evaluation.runner import rescore, run_suite


@pytest.fixture
def workspace(tmp_path: Path, project_root: Path) -> Path:
    shutil.copytree(project_root / "datasets", tmp_path / "datasets")
    shutil.copy(project_root / "ragprobe.yaml", tmp_path / "ragprobe.yaml")
    return tmp_path


def test_rescore_reproduces_a_stub_run(project_root):
    config = ProbeConfig.from_yaml(project_root / "ragprobe.yaml").apply_overrides({"evaluation.judge_enabled": False})
    cases = load_dataset(project_root / config.dataset_path)
    original = run_suite(cases, config, base_dir=project_root)
    again = rescore(original.to_dict(), cases)
    assert [c.passed for c in again.cases] == [c.passed for c in original.cases]
    assert [c.retrieval for c in again.cases] == [c.retrieval for c in original.cases]
    assert again.provider == "stub" and again.metadata["rescored_from"] == original.started_at


def test_rescore_applies_an_evaluator_change_without_the_model(project_root):
    config = ProbeConfig.from_yaml(project_root / "ragprobe.yaml").apply_overrides({"evaluation.judge_enabled": False})
    cases = load_dataset(project_root / config.dataset_path)
    payload = run_suite(cases, config, base_dir=project_root).to_dict()
    # Tighten a threshold: scoring changes, answers do not.
    stricter = config.apply_overrides({"evaluation.grounding_threshold": 0.99})
    rescored = rescore(payload, cases, stricter)
    assert rescored.passed < sum(1 for c in payload["cases"] if c["passed"])
    assert [c.answer for c in rescored.cases] == [c["answer"] for c in payload["cases"]]


def test_rescore_skips_cases_missing_from_the_dataset(project_root):
    config = ProbeConfig.from_yaml(project_root / "ragprobe.yaml").apply_overrides({"evaluation.judge_enabled": False})
    cases = load_dataset(project_root / config.dataset_path)
    payload = run_suite(cases, config, base_dir=project_root).to_dict()
    assert rescore(payload, cases[:3]).total == 3


def test_cli_rescore_writes_results_and_history(workspace, tmp_path):
    results = tmp_path / "r.json"
    assert main(["run", "--root", str(workspace), "--config", str(workspace / "ragprobe.yaml"),
                 "--out", str(results), "--no-judge", "--no-history", "--quiet"]) == EXIT_OK
    out = tmp_path / "rescored.json"
    code = main(["rescore", "--root", str(workspace), "--results", str(results), "--out", str(out),
                 "--history-dir", str(tmp_path / "hist")])
    assert code == EXIT_OK
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 16 and payload["metadata"]["rescored_from"]
    assert list((tmp_path / "hist").glob("*.json"))
