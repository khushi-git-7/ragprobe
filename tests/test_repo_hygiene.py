"""The project ships the governance files a real open-source project has."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md",
                                  "ROADMAP.md", "LICENSE", "README.md"])
def test_governance_file_present_and_non_trivial(name):
    path = ROOT / name
    assert path.is_file(), f"{name} is missing"
    assert len(path.read_text(encoding="utf-8").strip()) > 200


def test_security_policy_states_defensive_use():
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
    assert "authoris" in text or "authoriz" in text
    assert "defensive" in text


def test_changelog_mentions_the_benchmark():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Bench v1" in text and "leaderboard" in text.lower()


def test_quickstart_exists_and_only_uses_real_commands():
    text = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    for command in ("ragprobe doctor", "ragprobe demo", "ragprobe security run"):
        assert command in text
    # PyPI is not published yet, so the quickstart must not promise it
    assert "pip install ragprobe" not in text


def test_the_lint_job_runs_the_same_check_a_contributor_runs():
    """CI and a local `ruff check` must not disagree about what passes."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ruff check src tests scripts" in workflow
    assert "ruff==" in workflow, "pin the linter, or a new release can fail an unrelated PR"
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.ruff.lint]" in pyproject and 'select = ["F", "I", "W", "E7", "E9"]' in pyproject
    assert "ruff" in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")


def test_the_roadmap_does_not_promise_work_that_is_already_done():
    """A stale roadmap makes a finished project look half-built."""
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    shipped = roadmap.split("## Next")[0]
    for claim in ("Bench v1", "bench run", "Benign set", "leaderboard", "MCP", "Multi-turn",
                  "Obfuscated injections", "security scan"):
        assert claim.lower() in shipped.lower(), f"{claim} is shipped but not listed as shipped"
    assert "Decided against" in roadmap  # choices are recorded, not silently dropped


def test_the_readme_leads_with_what_the_tool_does_now():
    """Someone arriving from a link reads the first screen, and nothing else."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    top = readme[:1400]
    assert "docs/img/banner.png" in top
    assert (ROOT / "docs" / "img" / "banner.png").is_file()
    assert "OWASP" in top and "security scan --url" in top
    assert "pip install" in top
