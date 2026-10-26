"""A missing or unusable file must end in one clear line, never a traceback.

A tool that prints a stack trace at a user has told them "this is broken" when it
meant "that file is not there". These tests run the real CLI the way a user does,
from an empty directory, and assert the contract: exit code 2, a line starting
``error:``, and no traceback.
"""

from __future__ import annotations

import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

import ragprobe
from ragprobe.cli import EXIT_USAGE, main
from ragprobe.errors import RagprobeError

ROOT = Path(__file__).resolve().parents[1]

#: Every command that reads a dataset, corpus or results file, with the arguments
#: that point it at something that does not exist.
MISSING_FILE_COMMANDS = [
    ("bench build", ["bench", "build", "--attacks", "nope.yaml"]),
    ("bench stats", ["bench", "stats", "--catalogue", "nope.jsonl"]),
    ("bench run", ["bench", "run", "--catalogue", "nope.jsonl"]),
    ("bench leaderboard", ["bench", "leaderboard", "--catalogue", "nope.jsonl",
                           "--models", "groq-qwen"]),
    ("security run", ["security", "run", "--attacks", "nope.yaml"]),
    ("security lab", ["security", "lab", "--attacks", "nope.yaml"]),
    ("security benign", ["security", "benign", "--benign", "nope.jsonl"]),
    ("security compare", ["security", "compare", "--attacks", "nope.yaml"]),
    ("demo", ["demo", "--attacks", "nope.yaml"]),
    ("run", ["run", "--dataset", "nope.yaml"]),
    ("report", ["report", "--results", "nope.json"]),
    ("diff", ["diff", "--current", "nope.json", "--baseline", "nope.json"]),
    ("baseline", ["baseline", "--dataset", "nope.yaml"]),
    ("rescore", ["rescore", "--results", "nope.json"]),
]


@pytest.mark.parametrize("label,argv", MISSING_FILE_COMMANDS, ids=[c[0] for c in MISSING_FILE_COMMANDS])
def test_a_missing_file_is_one_clear_line(label, argv, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # nothing of ours is in reach
    code = main(argv)
    err = capsys.readouterr().err
    assert code == EXIT_USAGE, f"{label} exited {code}"
    assert err.startswith("error: "), f"{label} said: {err[:200]!r}"
    assert "Traceback" not in err


def test_the_same_holds_in_a_real_process(tmp_path):
    """Belt and braces: the installed entry point, not just main() in-process."""
    out = subprocess.run([sys.executable, "-m", "ragprobe", "bench", "stats",
                          "--catalogue", "nope.jsonl"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == EXIT_USAGE
    assert "Traceback" not in out.stderr and out.stderr.startswith("error: ")


def test_every_error_class_in_the_package_is_a_ragprobe_error():
    """A new domain error that forgets the base class would print a traceback."""
    missed = []
    for info in pkgutil.walk_packages(ragprobe.__path__, prefix="ragprobe."):
        try:
            module = __import__(info.name, fromlist=["_"])
        except Exception:  # an optional dependency is not installed; not our business
            continue
        for name, obj in vars(module).items():
            if (isinstance(obj, type) and issubclass(obj, Exception)
                    and obj.__module__ == info.name and not issubclass(obj, RagprobeError)):
                missed.append(f"{info.name}.{name}")
    assert not missed, "these should inherit RagprobeError: " + ", ".join(sorted(missed))


def test_an_unexpected_error_still_raises():
    """We must not swallow our own bugs: only RagprobeError is caught."""
    def boom(_args):
        raise ZeroDivisionError("a real bug")

    class Args:
        func = staticmethod(boom)

    import ragprobe.cli as cli

    original = cli.build_parser
    cli.build_parser = lambda: type("P", (), {"parse_args": staticmethod(lambda argv: Args())})()
    try:
        with pytest.raises(ZeroDivisionError):
            cli.main([])
    finally:
        cli.build_parser = original
