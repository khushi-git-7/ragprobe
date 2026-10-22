"""The CI workflow's own commands are valid, and run in a sensible order.

The publish job once aborted on a stray literal backslash-n that turned a shell line
continuation into an extra argument - and nothing in the test suite could see it,
because the tests exercised the commands directly rather than the text in the
workflow. This reads every ``ragprobe`` command out of the workflow file and parses
it with the real CLI, so a typo or a broken continuation fails here instead of after
the merge.
"""

from __future__ import annotations

import importlib.util
import shlex
from pathlib import Path
from typing import List

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# Spelled out with chr(): backslash escapes typed into this file have gone wrong before.
BACKSLASH, NEWLINE = chr(92), chr(10)
LITERAL_BACKSLASH_N = BACKSLASH + "n"


def _scripts(text: str) -> List[str]:
    jobs = yaml.safe_load(text)["jobs"]
    return [step["run"] for job in jobs.values() for step in job.get("steps", []) if "run" in step]


def _commands(script: str) -> List[str]:
    """Logical command lines: shell line-continuations joined, comments dropped."""
    out: List[str] = []
    joined = script.replace(BACKSLASH + NEWLINE, " ")
    for line in joined.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def check_workflow(text: str) -> List[str]:
    """Every problem found in the workflow's shell commands (empty = fine)."""
    from ragprobe.cli import build_parser

    problems: List[str] = []
    for script in _scripts(text):
        for line in _commands(script):
            if LITERAL_BACKSLASH_N in line:
                problems.append("literal backslash-n in a command (broken continuation?): " + line[:90])
                continue
            if not line.startswith("ragprobe ") or "$(" in line or "`" in line:
                continue  # not a ragprobe call, or it needs a shell to expand
            command = line.split(" || ")[0].split(" && ")[0]
            try:
                tokens = shlex.split(command)
            except ValueError as exc:
                problems.append("cannot parse " + repr(command[:70]) + ": " + str(exc))
                continue
            try:
                build_parser().parse_args(tokens[1:])
            except SystemExit:
                problems.append("the CLI rejects: " + command[:100])
    return problems


def test_every_ragprobe_command_in_the_workflow_is_valid():
    assert check_workflow(WORKFLOW.read_text(encoding="utf-8")) == []


def test_the_checker_catches_the_bug_that_broke_the_publish_job():
    first = """jobs:
  pages:
    steps:
      - run: |
          ragprobe security run --defenses none,layered --html site/security.html """
    second = """
            --out reports/security.json
"""
    broken = first + LITERAL_BACKSLASH_N + second
    problems = check_workflow(broken)
    assert problems and "backslash-n" in problems[0]


def test_a_correct_continuation_is_accepted():
    good = """jobs:
  pages:
    steps:
      - run: |
          ragprobe security run --defenses none,layered --html site/security.html """ + BACKSLASH + NEWLINE + """            --out reports/security.json
"""
    assert check_workflow(good) == []


def test_the_checker_catches_an_unknown_option():
    bad = """jobs:
  x:
    steps:
      - run: |
          ragprobe security run --no-such-flag
"""
    assert any("rejects" in p for p in check_workflow(bad))


def test_the_landing_build_command_runs(tmp_path, monkeypatch):
    # the one non-ragprobe command the publish job depends on: run it as written
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)
    monkeypatch.chdir(ROOT)
    for script in _scripts(WORKFLOW.read_text(encoding="utf-8")):
        for line in _commands(script):
            if line.startswith("python scripts/build_site.py"):
                args = shlex.split(line)[2:]
                args[args.index("--out") + 1] = str(tmp_path / "index.html")
                assert site.main(args + ["--no-changelog"]) == 0
                assert (tmp_path / "index.html").is_file()
                return
    pytest.fail("the workflow no longer builds the landing page")


def test_linked_pages_are_built_before_the_landing_page():
    ci = WORKFLOW.read_text(encoding="utf-8")
    land = ci.index("scripts/build_site.py")
    assert ci.index("ragprobe security run") < land and ci.index("ragprobe security lab") < land
