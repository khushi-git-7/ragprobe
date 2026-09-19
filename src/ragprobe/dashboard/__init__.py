"""The RAGProbe dashboard: run history rendered as a self-contained analytics page.

Three layers, kept apart on purpose:

* :mod:`ragprobe.dashboard.analytics` turns a list of results documents into a
  plain data model - KPIs, trends, breakdowns, per-case history. No HTML.
* :mod:`ragprobe.dashboard.insights` derives plain-English findings from that
  model, each with the rule that produced it. No HTML.
* :mod:`ragprobe.dashboard.svg` and :mod:`ragprobe.dashboard.html` render. No
  arithmetic beyond pixel placement.

That split is what makes the findings testable: every number on the page comes
from a function that can be pinned to a hand-computed value.
"""

from ragprobe.dashboard.analytics import DashboardModel, build_model
from ragprobe.dashboard.html import render_dashboard, write_dashboard
from ragprobe.dashboard.insights import Insight, generate_insights

__all__ = [
    "DashboardModel",
    "Insight",
    "build_model",
    "generate_insights",
    "render_dashboard",
    "write_dashboard",
]
