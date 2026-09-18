"""Terminal output.

Deliberately ASCII-only. Box-drawing characters look better but raise
``UnicodeEncodeError`` on a Windows console running a legacy code page, and a
reporting layer that crashes the run it is reporting on is a bad trade for prettier
borders. Colour is opt-out via ``NO_COLOR`` and is disabled automatically when stdout
is not a TTY, so piping to a file or a CI log produces clean text.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from ragprobe.regression.diff import (
    STATUS_DEGRADED,
    STATUS_FLAT,
    STATUS_IMPROVED,
    STATUS_NEW,
    STATUS_REGRESSED,
    STATUS_REMOVED,
    DiffReport,
)


def _use_color(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


class _Palette:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)


def _truncate(text: str, width: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def _rule(width: int = 78) -> str:
    return "-" * width


def _fmt_metric(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_run_summary(run_dict: Dict[str, Any], color: Optional[bool] = None) -> str:
    """Render the per-case table and aggregate summary for a completed run."""
    palette = _Palette(_use_color() if color is None else color)
    summary = run_dict.get("summary", {})
    cases: Sequence[Dict[str, Any]] = run_dict.get("cases", [])

    lines: List[str] = []
    lines.append("")
    lines.append(palette.bold("RAGProbe run summary"))
    lines.append(_rule())

    pipeline = run_dict.get("pipeline", {})
    provider = run_dict.get("provider", "?")
    determinism = "deterministic" if run_dict.get("deterministic") else "NONDETERMINISTIC"
    lines.append(
        f"  provider   : {provider} ({determinism})    "
        f"corpus: {pipeline.get('documents', '?')} docs / {pipeline.get('chunks', '?')} chunks"
    )
    lines.append(
        f"  config     : {run_dict.get('config_fingerprint', '?')}    "
        f"dataset: {run_dict.get('dataset_fingerprint', '?')}"
    )
    lines.append("")

    # Per-case table
    header = f"  {'STATUS':<7} {'CASE':<26} {'SCORE':>6}  {'CATEGORY':<14} NOTES"
    lines.append(palette.dim(header))
    for case in cases:
        passed = case.get("passed")
        status = palette.green("PASS   ") if passed else palette.red("FAIL   ")
        failed = case.get("failed_checks") or []
        if case.get("error"):
            note = f"error: {_truncate(str(case['error']), 40)}"
        elif failed:
            note = "failed: " + ", ".join(failed)
        else:
            note = ""
        lines.append(
            f"  {status} {_truncate(str(case.get('id', '')), 26):<26} "
            f"{case.get('score', 0.0):>6.3f}  {_truncate(str(case.get('category', '')), 14):<14} "
            f"{_truncate(note, 40)}"
        )

    lines.append(_rule())

    total = summary.get("total", 0)
    passed_count = summary.get("passed", 0)
    failed_count = summary.get("failed", 0)
    pass_rate = summary.get("pass_rate", 0.0) or 0.0
    verdict = palette.green(f"{passed_count} passed") if passed_count else f"{passed_count} passed"
    if failed_count:
        verdict += ", " + palette.red(f"{failed_count} failed")
    else:
        verdict += f", {failed_count} failed"
    lines.append(
        f"  {verdict} of {total}   pass rate {pass_rate:.1%}   "
        f"mean score {summary.get('mean_score', 0.0):.3f}"
    )

    retrieval = summary.get("retrieval", {}) or {}
    if retrieval:
        parts = [f"{name} {_fmt_metric(value)}" for name, value in sorted(retrieval.items())]
        lines.append("  retrieval: " + "   ".join(parts))

    by_category = summary.get("by_category", {}) or {}
    if len(by_category) > 1:
        lines.append(palette.dim("  by category:"))
        for name, stats in by_category.items():
            lines.append(
                f"    {_truncate(name, 20):<20} "
                f"{stats.get('passed', 0)}/{stats.get('total', 0)} passed   "
                f"mean score {stats.get('mean_score', 0.0):.3f}"
            )
    lines.append("")
    return "\n".join(lines)


def render_diff_summary(report: DiffReport, color: Optional[bool] = None) -> str:
    """Render the regression diff for the terminal."""
    palette = _Palette(_use_color() if color is None else color)
    counts = report.counts()

    lines: List[str] = []
    lines.append("")
    lines.append(palette.bold("RAGProbe regression diff"))
    lines.append(_rule())

    base_meta = report.baseline_meta
    curr_meta = report.current_meta
    lines.append(
        f"  baseline: config {base_meta.get('config_fingerprint', '?')} "
        f"provider {base_meta.get('provider', '?')} at {base_meta.get('started_at', '?')}"
    )
    lines.append(
        f"  current : config {curr_meta.get('config_fingerprint', '?')} "
        f"provider {curr_meta.get('provider', '?')} at {curr_meta.get('started_at', '?')}"
    )

    if report.warnings:
        lines.append("")
        for warning in report.warnings:
            lines.append(palette.yellow(f"  ! {warning}"))

    lines.append("")
    lines.append(
        "  " + "   ".join(
            [
                palette.red(f"regressed {counts[STATUS_REGRESSED]}"),
                palette.yellow(f"degraded {counts[STATUS_DEGRADED]}"),
                palette.green(f"improved {counts[STATUS_IMPROVED]}"),
                palette.dim(f"flat {counts[STATUS_FLAT]}"),
                f"new {counts[STATUS_NEW]}",
                palette.yellow(f"removed {counts[STATUS_REMOVED]}"),
            ]
        )
    )

    interesting = [
        case
        for case in report.cases
        if case.status
        in {STATUS_REGRESSED, STATUS_DEGRADED, STATUS_IMPROVED, STATUS_NEW, STATUS_REMOVED}
    ]
    if interesting:
        lines.append("")
        lines.append(palette.dim(f"  {'CHANGE':<11} {'CASE':<26} {'DELTA':>7}  DETAIL"))
        for case in interesting:
            if case.status == STATUS_REGRESSED:
                label = palette.red(f"{'REGRESSED':<11}")
            elif case.status == STATUS_DEGRADED:
                label = palette.yellow(f"{'DEGRADED':<11}")
            elif case.status == STATUS_IMPROVED:
                label = palette.green(f"{'IMPROVED':<11}")
            elif case.status == STATUS_REMOVED:
                label = palette.yellow(f"{'REMOVED':<11}")
            else:
                label = palette.cyan(f"{'NEW':<11}")
            delta = "" if case.score_delta is None else f"{case.score_delta:+.3f}"
            detail = case.reason
            if case.newly_failing:
                detail += " | now failing: " + ", ".join(case.newly_failing)
            elif case.newly_passing:
                detail += " | now passing: " + ", ".join(case.newly_passing)
            lines.append(
                f"  {label} {_truncate(case.id, 26):<26} {delta:>7}  {_truncate(detail, 90)}"
            )

    lines.append("")
    return "\n".join(lines)


def render_gate(gate, color: Optional[bool] = None) -> str:
    """Render the pass/fail verdict of the CI gate."""
    palette = _Palette(_use_color() if color is None else color)
    if gate.ok:
        return palette.green("  GATE PASSED: no blocking regressions.\n")
    lines = [palette.red("  GATE FAILED:")]
    for reason in gate.reasons:
        lines.append(palette.red(f"    - {reason}"))
    return "\n".join(lines) + "\n"
