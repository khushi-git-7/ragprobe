"""Report rendering: self-contained HTML and terminal summaries."""

from ragprobe.reporting.html import render_report, write_report
from ragprobe.reporting.terminal import render_diff_summary, render_gate, render_run_summary

__all__ = [
    "render_report",
    "write_report",
    "render_run_summary",
    "render_diff_summary",
    "render_gate",
]
