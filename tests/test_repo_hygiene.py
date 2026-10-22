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
