"""HTML fragments shared by the run report and the dashboard.

Both pages show the same objects - a check with its verdict, a retrieved chunk
with whether the golden set expected it - and they must show them identically.
Keeping one copy of the escaping, the number formatting and the per-case tables
means the two pages cannot drift apart, and there is exactly one place to audit
for escaping. Each page only styles what is produced here.

Every function returns a string of HTML with all user-controlled text escaped.
"""

from __future__ import annotations

import html
from typing import Any, Mapping, Optional, Sequence


def esc(value: Any) -> str:
    """Escape ``value`` for use in HTML text or a quoted attribute; ``None`` becomes ``""``."""
    return html.escape(str(value if value is not None else ""), quote=True)


def fmt_score(value: Optional[float], digits: int = 3) -> str:
    """``0.875`` -> ``0.875``; ``None`` -> ``n/a``."""
    return "n/a" if value is None else f"{value:.{digits}f}"


def fmt_pct(value: Optional[float]) -> str:
    """``0.875`` -> ``87.5%``; ``None`` -> ``n/a``."""
    return "n/a" if value is None else f"{value * 100:.1f}%"


def check_pill(check: Mapping[str, Any]) -> str:
    """``pass`` / ``fail`` / ``skip`` (not applicable) as a coloured pill."""
    if not check.get("applicable", True):
        return '<span class="pill skip">skip</span>'
    return '<span class="pill pass">pass</span>' if check.get("passed") else '<span class="pill fail">fail</span>'


def checks_table(checks: Sequence[Mapping[str, Any]]) -> str:
    """One row per check: verdict, name (advisory checks marked), score, detail."""
    if not checks:
        return '<p class="muted">No checks were recorded (the case errored before evaluation).</p>'
    rows = []
    for check in checks:
        advisory = (check.get("metadata") or {}).get("advisory")
        name = esc(check.get("name")) + (' <span class="muted">(advisory)</span>' if advisory else "")
        rows.append(
            f"<tr><td>{check_pill(check)}</td><td>{name}</td>"
            f'<td class="num">{fmt_score(check.get("score"), 2)}</td><td>{esc(check.get("detail"))}</td></tr>'
        )
    return (
        '<table><thead><tr><th></th><th>Check</th><th class="num">Score</th><th>Detail</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _anchor(chunk_id: Any) -> str:
    """The stable part of a chunk id, before the ``~`` content hash."""
    return str(chunk_id).split("~", 1)[0]


def chunk_list(retrieved: Sequence[Mapping[str, Any]], expected: Sequence[str]) -> str:
    """The retrieved chunks in rank order, marking golden-set matches and listing what was missed.

    A chunk matches when its anchor (the id before ``~``) is in ``expected``, so a
    re-chunked corpus with the same headings still matches.
    """
    if not retrieved:
        return '<p class="muted">Nothing was retrieved for this question.</p>'
    expected_anchors = {_anchor(chunk) for chunk in expected}
    blocks = []
    for chunk in retrieved:
        chunk_id = str(chunk.get("chunk_id", ""))
        is_expected = _anchor(chunk_id) in expected_anchors
        label = '<span class="pill pass">expected</span>' if is_expected else '<span class="pill skip">not in golden set</span>'
        blocks.append(
            f'<div class="chunk {"expected" if is_expected else ""}"><div class="chead">'
            f'<span class="cid">{esc(chunk_id)}</span><span class="muted">rank {esc(chunk.get("rank"))} &middot; '
            f'score {fmt_score(chunk.get("score"))}</span>{label}</div>'
            f'<div class="ctext">{esc(chunk.get("text"))}</div></div>'
        )
    retrieved_anchors = {_anchor(chunk.get("chunk_id", "")) for chunk in retrieved}
    missing = sorted(anchor for anchor in expected_anchors if anchor not in retrieved_anchors)
    if missing:
        blocks.append(
            '<p class="muted">Expected but not retrieved: '
            + ", ".join(f"<code>{esc(item)}</code>" for item in missing)
            + "</p>"
        )
    return "".join(blocks)
