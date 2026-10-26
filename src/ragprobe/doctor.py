"""`ragprobe doctor` - a quick health check of the install, data and keys.

A new user's first question is "is this set up right, and what can I run?" This
answers it: it checks the Python and package versions, that the datasets are
present and valid, and which optional API keys are available - without ever
printing a key. Each check is OK, a warning (optional thing missing), or a
problem (something the core needs), with a one-line hint.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ragprobe.resources import is_bundled, resolve_under

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    status: str      # ok | warn | fail
    name: str
    detail: str


def _check_python() -> Check:
    v = sys.version_info
    if v >= (3, 9):
        return Check(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    return Check(FAIL, "Python", f"{v.major}.{v.minor} found; RAGProbe needs 3.9+")


def _check_version() -> Check:
    try:
        from ragprobe import __version__
        return Check(OK, "RAGProbe", __version__)
    except Exception as exc:  # pragma: no cover - import always works in practice
        return Check(FAIL, "RAGProbe", f"cannot import package: {exc}")


def _check_yaml() -> Check:
    try:
        import yaml  # noqa: F401
        return Check(OK, "PyYAML", "installed")
    except Exception:
        return Check(FAIL, "PyYAML", "missing; run `pip install -e .`")


def _where(path: Path) -> str:
    """Say which copy answered: the one shipped in the package, or the user's own."""
    return "shipped with the package" if is_bundled(path) else str(path)


def _check_file(name: str, path: Path, hint: str) -> Check:
    if path.is_file():
        return Check(OK, name, _where(path))
    return Check(FAIL, name, f"not found at {path}; {hint}")


def _check_bench(path: Path) -> Check:
    if not path.is_file():
        return Check(FAIL, "Bench v1", f"not found at {path}; it ships inside the package, "
                     "so reinstall RAGProbe or rebuild it with `ragprobe bench build`")
    try:
        from ragprobe.bench.dataset import load_jsonl, validate_all
        items = load_jsonl(path)
        validate_all(items)
        attacks = sum(1 for i in items if i.kind == "attack")
        return Check(OK, "Bench v1", f"{len(items)} items ({attacks} runnable attacks), valid "
                                     f"- {_where(path)}")
    except Exception as exc:
        return Check(FAIL, "Bench v1", f"invalid: {exc}")


def _check_key(name: str, env: str) -> Check:
    if os.environ.get(env):
        return Check(OK, name, f"{env} is set")
    return Check(WARN, name, f"{env} not set; needed only for live {name} runs")


def run_checks(root: Optional[Path] = None) -> List[Check]:
    root = Path(root) if root else Path.cwd()

    def data(relative: str) -> Path:
        """Where this run would read that file: a local copy if any, else the shipped one."""
        return resolve_under(root, "datasets/" + relative)

    hint = ("this file ships inside the package, so reinstall RAGProbe or check a local "
            "./datasets copy")
    return [
        _check_python(),
        _check_version(),
        _check_yaml(),
        _check_file("Attack corpus", data("security/attacks.yaml"), hint),
        _check_bench(data("bench/v1/attacks.jsonl")),
        _check_file("Benign corpus", data("security/benign.jsonl"), hint),
        _check_key("Groq", "GROQ_API_KEY"),
        _check_key("Gemini", "GEMINI_API_KEY"),
    ]


def render(checks: List[Check], color: bool = False) -> str:
    glyph = {OK: "[ok]", WARN: "[--]", FAIL: "[XX]"}
    lines = ["RAGProbe doctor", "-" * 48]
    for c in checks:
        lines.append(f"  {glyph[c.status]} {c.name:<16} {c.detail}")
    fails = sum(1 for c in checks if c.status == FAIL)
    warns = sum(1 for c in checks if c.status == WARN)
    lines.append("-" * 48)
    if fails:
        lines.append(f"  {fails} problem(s) to fix" + (f", {warns} optional item(s) missing" if warns else ""))
    elif warns:
        lines.append(f"  all core checks pass; {warns} optional item(s) missing (live model keys)")
    else:
        lines.append("  all checks pass - you're ready to run everything, including live models")
    return "\n".join(lines)


def has_failures(checks: List[Check]) -> bool:
    return any(c.status == FAIL for c in checks)
