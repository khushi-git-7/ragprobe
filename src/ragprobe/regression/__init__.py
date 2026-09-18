"""Regression tooling: baseline comparison and CI gating."""

from ragprobe.regression.diff import CaseDiff, DiffReport, GateResult, diff_runs

__all__ = ["CaseDiff", "DiffReport", "GateResult", "diff_runs"]
