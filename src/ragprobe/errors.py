"""The one base class for every failure a user can cause or hit.

A command-line tool has two kinds of failure. One is the user's world: a file that
is not there, a corpus that will not parse, an API that refuses or rate-limits.
Those deserve a single clear line and a non-zero exit code. The other is our bug,
which deserves a traceback so it gets reported and fixed.

Every expected failure in RAGProbe therefore inherits :class:`RagprobeError`, and
``ragprobe.cli.main`` catches exactly that. Anything else reaches the user as a
traceback on purpose. Each error also keeps its older base (``ValueError``,
``RuntimeError``) so existing ``except`` clauses, in this code and in anyone's
scripts, keep working.
"""

from __future__ import annotations


class RagprobeError(Exception):
    """An expected, actionable failure: print the message, not a traceback."""
