"""The install must carry its own data, and nothing may fall out of the wheel quietly.

`pip install ragprobe` has to be enough to run a scan from any directory. That only
holds while every shipped data file is matched by a `package-data` glob in
pyproject.toml, so this walks the data directory and checks exactly that, instead of
waiting for a user to hit "attack file not found" after a clean install.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

from ragprobe.resources import BUNDLED, bundled_path, is_bundled, resolve_data, resolve_under

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

#: The files a user must be able to reach with no checkout.
REQUIRED = [
    "golden_set.yaml",
    "security/attacks.yaml",
    "security/benign.jsonl",
    "security/deepset/train.jsonl",
    "security/deepset/test.jsonl",
    "bench/v1/attacks.jsonl",
    "bench/v2/attacks.jsonl",
    "docs/employee_handbook.md",
]


def _globs() -> list:
    """The package-data patterns declared for ragprobe.datasets."""
    text = PYPROJECT.read_text(encoding="utf-8")
    block = re.search(r'\[tool\.setuptools\.package-data\].*?"ragprobe\.datasets"\s*=\s*\[(.*?)\]',
                      text, flags=re.S)
    assert block, "pyproject.toml must declare package-data for ragprobe.datasets"
    return re.findall(r'"([^"]+)"', block.group(1))


def _data_files() -> list:
    return sorted(p.relative_to(BUNDLED).as_posix()
                  for p in BUNDLED.rglob("*")
                  if p.is_file() and p.name != "__init__.py" and "__pycache__" not in p.parts)


def test_the_data_directory_is_inside_the_package():
    assert BUNDLED.is_dir()
    assert BUNDLED.parent.name == "ragprobe"
    assert (BUNDLED / "__init__.py").is_file(), "it must be a package to be installed"


@pytest.mark.parametrize("relative", REQUIRED)
def test_every_file_a_user_needs_is_present(relative):
    assert bundled_path(relative).is_file(), relative


def test_every_shipped_data_file_is_covered_by_a_package_data_glob():
    globs = _globs()
    uncovered = [f for f in _data_files()
                 if not any(fnmatch.fnmatch(f, g) for g in globs)]
    assert not uncovered, (
        "these data files would be missing from an installed package; add a glob to "
        "[tool.setuptools.package-data] in pyproject.toml: " + ", ".join(uncovered))


def test_no_glob_is_dead():
    """A pattern matching nothing is either a typo or a leftover."""
    files = _data_files()
    dead = [g for g in _globs() if not any(fnmatch.fnmatch(f, g) for f in files)]
    assert not dead, "these package-data globs match no file: " + ", ".join(dead)


def test_the_repository_root_no_longer_hides_a_second_copy():
    """Two copies drift. The package copy is the only one."""
    assert not (ROOT / "datasets").exists()


class TestResolution:
    def test_a_relative_repository_path_finds_the_shipped_copy(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        found = resolve_data("datasets/security/attacks.yaml")
        assert found.is_file() and is_bundled(found)

    def test_a_package_relative_path_works_too(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_data("security/attacks.yaml").is_file()

    def test_your_own_copy_wins(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mine = tmp_path / "datasets" / "security"
        mine.mkdir(parents=True)
        (mine / "attacks.yaml").write_text("attacks: []\n", encoding="utf-8")
        found = resolve_data("datasets/security/attacks.yaml")
        assert not is_bundled(found)
        assert found.read_text(encoding="utf-8") == "attacks: []\n"

    def test_a_path_that_is_ours_nowhere_comes_back_unchanged(self, tmp_path, monkeypatch):
        """So the error message names the file the user asked for."""
        monkeypatch.chdir(tmp_path)
        assert resolve_data("datasets/security/nope.yaml") == Path("datasets/security/nope.yaml")

    def test_an_absolute_path_is_never_swapped_for_ours(self, tmp_path):
        """Silently reading our data when someone named a full path would be a trap."""
        asked = tmp_path / "datasets" / "security" / "attacks.yaml"
        assert resolve_data(asked) == asked
        assert resolve_under(None, asked) == asked

    def test_resolve_under_prefers_the_project_then_the_package(self, tmp_path):
        local = tmp_path / "datasets" / "docs"
        assert is_bundled(resolve_under(tmp_path, "datasets/docs"))
        local.mkdir(parents=True)
        assert resolve_under(tmp_path, "datasets/docs") == local


def test_the_demo_runs_from_any_directory(tmp_path, monkeypatch, capsys):
    """The new user's first command, with no checkout in reach."""
    from ragprobe.cli import EXIT_OK, main

    monkeypatch.chdir(tmp_path)
    assert main(["demo"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "grade F" in out and "attacks that work" in out


def test_a_security_scan_runs_from_any_directory(tmp_path, monkeypatch, capsys):
    from ragprobe.cli import EXIT_OK, main

    monkeypatch.chdir(tmp_path)
    assert main(["security", "run", "--out", "out.json"]) == EXIT_OK
    assert (tmp_path / "out.json").is_file()
