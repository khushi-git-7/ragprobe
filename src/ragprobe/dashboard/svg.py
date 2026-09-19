"""Inline SVG charts, generated in Python.

No charting library, no CDN, no canvas: the dashboard has to open from disk as a
CI artifact, and the runtime dependency list is PyYAML and nothing else. SVG
produced by string building is enough for sparklines, line charts, bars and
histograms, and it has a property a JS chart library does not - the geometry is
computed once, in Python, where it can be unit-tested.

Colours are never hard-coded here. Marks carry CSS classes (``c-line``,
``c-fill``, ``c-grid`` ...) that the page's token sheet resolves in light and dark
mode, so the same SVG is correct in both themes.

Interactivity is data, not code: each chart embeds the values it plots in a
``data-chart`` attribute (line charts) or ``data-tip`` attributes (bars), and a
small vanilla-JS layer in the page reads those to draw crosshairs and tooltips.
"""

from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

Number = Optional[float]


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _f(value: float) -> str:
    """Compact float for SVG attributes: ``12.0`` -> ``12``, ``3.14159`` -> ``3.14``."""
    text = f"{value:.2f}"
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return "0" if text in ("-0", "") else text


def fmt_value(value: Number, fmt: str) -> str:
    if value is None:
        return "n/a"
    if fmt == "percent":
        return f"{value * 100:.1f}%"
    if fmt == "count":
        return f"{int(round(value))}"
    return f"{value:.3f}"


def fmt_delta(value: Number, fmt: str) -> str:
    if value is None:
        return "n/a"
    if fmt == "percent":
        return f"{value * 100:+.1f} pts"
    if fmt == "count":
        return f"{int(round(value)):+d}"
    return f"{value:+.3f}"


# ------------------------------------------------------------------ scales


def _domain(values: Sequence[Number], clamp: Optional[Tuple[float, float]] = (0.0, 1.0)) -> Tuple[float, float]:
    """A padded y-domain so a series that lives in 0.85-1.0 is not a flat line at the top."""
    defined = [float(v) for v in values if v is not None]
    if not defined:
        return (0.0, 1.0)
    lo, hi = min(defined), max(defined)
    span = hi - lo
    pad = span * 0.25 if span > 1e-9 else (abs(hi) * 0.1 if abs(hi) > 1e-9 else 0.5)
    lo, hi = lo - pad, hi + pad
    if clamp is not None:
        lo, hi = max(clamp[0], lo), min(clamp[1], hi)
        if hi - lo < 1e-9:
            lo, hi = max(clamp[0], lo - 0.05), min(clamp[1], hi + 0.05)
    return (lo, hi)


def _ticks(lo: float, hi: float, count: int = 4) -> List[float]:
    if count < 2 or hi <= lo:
        return [lo, hi]
    step = (hi - lo) / (count - 1)
    return [lo + i * step for i in range(count)]


def _tick_text(tick: float, fmt: str) -> str:
    if fmt == "percent":
        return f"{tick * 100:.0f}%"
    if fmt == "count":
        return f"{int(round(tick))}"
    return f"{tick:.2f}"


def _rounded_hbar(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    """Horizontal bar, square at the baseline (left), rounded at the data end (right)."""
    if w <= 0:
        return ""
    r = min(r, w, h / 2)
    return (
        f"M{_f(x)},{_f(y)} h{_f(w - r)} a{_f(r)},{_f(r)} 0 0 1 {_f(r)},{_f(r)} "
        f"v{_f(h - 2 * r)} a{_f(r)},{_f(r)} 0 0 1 -{_f(r)},{_f(r)} h-{_f(w - r)} z"
    )


def _rounded_vbar(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    """Vertical column, square at the baseline (bottom), rounded at the top."""
    if h <= 0:
        return ""
    r = min(r, h, w / 2)
    return (
        f"M{_f(x)},{_f(y + r)} a{_f(r)},{_f(r)} 0 0 1 {_f(r)},-{_f(r)} h{_f(w - 2 * r)} "
        f"a{_f(r)},{_f(r)} 0 0 1 {_f(r)},{_f(r)} v{_f(h - r)} h-{_f(w)} z"
    )


# ------------------------------------------------------------------ sparkline


def sparkline(
    values: Sequence[Number],
    width: int = 120,
    height: int = 32,
    sentiment: str = "neutral",
    label: str = "",
) -> str:
    """A small, axis-free trend line. The last point is marked; gaps break the line."""
    pad = 3.0
    n = len(values)
    defined = [v for v in values if v is not None]
    if n == 0 or not defined:
        return (
            f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'role="img" aria-label="{_esc(label or "no data")}"></svg>'
        )
    lo, hi = min(defined), max(defined)
    if hi - lo < 1e-9:
        lo, hi = lo - 0.05, hi + 0.05
    step = (width - 2 * pad) / (n - 1) if n > 1 else 0.0

    def xy(i: int, v: float) -> Tuple[float, float]:
        x = pad + i * step if n > 1 else width / 2
        y = pad + (height - 2 * pad) * (1 - (v - lo) / (hi - lo))
        return x, y

    segments: List[str] = []
    current: List[str] = []
    last_xy: Optional[Tuple[float, float]] = None
    for i, v in enumerate(values):
        if v is None:
            if current:
                segments.append("M" + " L".join(current))
            current = []
            continue
        x, y = xy(i, float(v))
        current.append(f"{_f(x)},{_f(y)}")
        last_xy = (x, y)
    if current:
        segments.append("M" + " L".join(current))
    path = " ".join(segments)
    dot = ""
    if last_xy is not None:
        dot = f'<circle class="spark-dot {_esc(sentiment)}" cx="{_f(last_xy[0])}" cy="{_f(last_xy[1])}" r="3"/>'
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{_esc(label)}">'
        f'<path class="spark-line" d="{path}"/>{dot}</svg>'
    )


# ------------------------------------------------------------------ line chart


def line_chart(
    values: Sequence[Number],
    labels: Sequence[str],
    fmt: str = "score",
    series: str = "",
    annotations: Optional[Sequence[Mapping[str, Any]]] = None,
    width: int = 640,
    height: int = 220,
    chart_id: str = "",
    tick_labels: Optional[Sequence[str]] = None,
) -> str:
    """One series over run index, with gridlines, end label and hover metadata.

    ``labels`` name each point in the tooltip; ``tick_labels`` (default: ``labels``)
    are the shorter strings drawn on the x-axis.

    ``annotations`` is a list of ``{"index": i, "kind": "config"|"dataset", "text": ...}``;
    each draws a vertical marker at that run so a reader can see *when* something
    changed, not just that the line moved.
    """
    n = len(values)
    ticks = list(tick_labels) if tick_labels is not None else list(labels)
    left, right, top, bottom = 52.0, 20.0, 16.0, 34.0
    plot_w, plot_h = width - left - right, height - top - bottom
    lo, hi = _domain(values, (0.0, 1.0) if fmt != "count" else None)
    if fmt == "count":
        lo = 0.0
        hi = max(hi, 1.0)

    def x_at(i: int) -> float:
        return left + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)

    def y_at(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / (hi - lo))

    parts: List[str] = []
    # Gridlines and y ticks: solid hairlines, recessive.
    for tick in _ticks(lo, hi, 4):
        y = y_at(tick)
        parts.append(f'<line class="c-grid" x1="{_f(left)}" x2="{_f(left + plot_w)}" y1="{_f(y)}" y2="{_f(y)}"/>')
        parts.append(
            f'<text class="c-axis" x="{_f(left - 8)}" y="{_f(y + 4)}" text-anchor="end">'
            f"{_esc(_tick_text(tick, fmt))}</text>"
        )
    # X labels: first, last and a few in between, never overlapping.
    max_labels = max(2, min(n, int(plot_w // 70)))
    label_every = max(1, (n - 1) // max(1, max_labels - 1)) if n > 1 else 1
    for i in range(n):
        if i % label_every == 0 or i == n - 1:
            parts.append(
                f'<text class="c-axis" x="{_f(x_at(i))}" y="{_f(height - 12)}" text-anchor="middle">'
                f"{_esc(ticks[i] if i < len(ticks) else i + 1)}</text>"
            )
    # Annotations: a vertical hairline plus a marker at the top of the plot.
    xs: List[float] = [x_at(i) for i in range(n)]
    for ann in annotations or []:
        i = int(ann.get("index", -1))
        if not 0 <= i < n:
            continue
        kind = str(ann.get("kind", "config"))
        x = xs[i]
        parts.append(f'<line class="c-annot {_esc(kind)}" x1="{_f(x)}" x2="{_f(x)}" y1="{_f(top)}" y2="{_f(top + plot_h)}"/>')
        parts.append(
            f'<path class="c-annot-mark {_esc(kind)}" d="M{_f(x)},{_f(top - 10)} l5,5 l-5,5 l-5,-5 z">'
            f"<title>{_esc(ann.get('text', ''))}</title></path>"
        )
    # Area wash and line, broken at gaps.
    segments: List[List[Tuple[float, float]]] = []
    current: List[Tuple[float, float]] = []
    for i, v in enumerate(values):
        if v is None:
            if current:
                segments.append(current)
            current = []
            continue
        current.append((xs[i], y_at(float(v))))
    if current:
        segments.append(current)
    baseline_y = top + plot_h
    for seg in segments:
        pts = " L".join(f"{_f(x)},{_f(y)}" for x, y in seg)
        if len(seg) > 1:
            if lo <= 0.0:
                # An area wash implies "magnitude from zero"; on a zoomed axis it would lie.
                parts.append(
                    f'<path class="c-area" d="M{_f(seg[0][0])},{_f(baseline_y)} L{pts} '
                    f'L{_f(seg[-1][0])},{_f(baseline_y)} z"/>'
                )
            parts.append(f'<path class="c-line" d="M{pts}"/>')
    for i, v in enumerate(values):
        if v is not None:
            parts.append(f'<circle class="c-dot" cx="{_f(xs[i])}" cy="{_f(y_at(float(v)))}" r="3.5"/>')
    # End label: the one direct label a single series gets.
    last_defined = next((i for i in range(n - 1, -1, -1) if values[i] is not None), None)
    if last_defined is not None:
        parts.append(
            f'<text class="c-end" x="{_f(xs[last_defined] - 8)}" y="{_f(y_at(float(values[last_defined])) - 10)}" '
            f'text-anchor="end">{_esc(fmt_value(values[last_defined], fmt))}</text>'
        )
    # Hover layer: crosshair, focus ring, hit area.
    parts.append(f'<line class="c-cross" x1="0" x2="0" y1="{_f(top)}" y2="{_f(baseline_y)}" style="display:none"/>')
    parts.append('<circle class="c-focus" cx="0" cy="0" r="6" style="display:none"/>')
    parts.append(f'<rect class="c-hit" x="{_f(left)}" y="{_f(top)}" width="{_f(plot_w)}" height="{_f(plot_h)}"/>')

    payload = {
        "series": series,
        "fmt": fmt,
        "xs": [round(x, 2) for x in xs],
        "ys": [round(y_at(float(v)), 2) if v is not None else None for v in values],
        "values": [v for v in values],
        "labels": list(labels),
        "notes": [""] * n,
    }
    for ann in annotations or []:
        i = int(ann.get("index", -1))
        if 0 <= i < n:
            payload["notes"][i] = (payload["notes"][i] + "\n" if payload["notes"][i] else "") + str(ann.get("text", ""))
    return (
        f'<svg class="chart line" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_esc(series)} over {n} run(s)" data-chart="{_esc(json.dumps(payload))}"'
        f'{f" id={chr(34)}{_esc(chart_id)}{chr(34)}" if chart_id else ""}>'
        + "".join(parts)
        + "</svg>"
    )


# ------------------------------------------------------------------ bars


def hbar_chart(
    rows: Sequence[Mapping[str, Any]],
    fmt: str = "percent",
    max_value: float = 1.0,
    width: int = 640,
    bar_h: int = 18,
    gap: int = 14,
    label_w: int = 130,
) -> str:
    """Horizontal bars, one hue, value at the tip; ``rows`` = ``{label, value, tip, cls?}``."""
    if not rows:
        return '<p class="muted">Nothing to plot.</p>'
    left, right = float(label_w), 70.0
    plot_w = width - left - right
    height = len(rows) * (bar_h + gap) + gap
    parts: List[str] = []
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = left + plot_w * tick
        parts.append(f'<line class="c-grid" x1="{_f(x)}" x2="{_f(x)}" y1="{_f(gap / 2)}" y2="{_f(height - gap / 2)}"/>')
    for i, row in enumerate(rows):
        y = gap + i * (bar_h + gap)
        value = row.get("value")
        w = 0.0 if value is None else plot_w * min(max(float(value), 0.0), max_value) / max_value
        cls = str(row.get("cls", ""))
        parts.append(
            f'<g class="c-bar-row" data-tip="{_esc(row.get("tip", ""))}">'
            f'<rect class="c-hit" x="0" y="{_f(y - gap / 2)}" width="{width}" height="{bar_h + gap}"/>'
            f'<text class="c-label" x="{_f(left - 10)}" y="{_f(y + bar_h / 2 + 4)}" text-anchor="end">{_esc(row.get("label"))}</text>'
            f'<rect class="c-track" x="{_f(left)}" y="{_f(y)}" width="{_f(plot_w)}" height="{bar_h}" rx="4"/>'
            f'<path class="c-fill {_esc(cls)}" d="{_rounded_hbar(left, y, w, bar_h)}"/>'
            f'<text class="c-value" x="{_f(left + w + 8)}" y="{_f(y + bar_h / 2 + 4)}">{_esc(fmt_value(value, fmt))}</text>'
            "</g>"
        )
    return (
        f'<svg class="chart hbar" viewBox="0 0 {width} {height}" role="img" aria-label="bar chart">'
        + "".join(parts)
        + "</svg>"
    )


def stacked_hbar(
    rows: Sequence[Mapping[str, Any]],
    width: int = 640,
    bar_h: int = 18,
    gap: int = 14,
    label_w: int = 190,
) -> str:
    """Stacked horizontal bars; ``rows`` = ``{label, segments: [{label, count, cls}], note?}``.

    Segments are separated by a 2px surface gap rather than a stroke.
    """
    if not rows:
        return '<p class="muted">Nothing to plot.</p>'
    left, right = float(label_w), 60.0
    plot_w = width - left - right
    height = len(rows) * (bar_h + gap) + gap
    total_max = max((sum(int(s.get("count", 0)) for s in row.get("segments", [])) for row in rows), default=1) or 1
    parts: List[str] = []
    for i, row in enumerate(rows):
        y = gap + i * (bar_h + gap)
        total = sum(int(s.get("count", 0)) for s in row.get("segments", []))
        x = left
        label = _esc(row.get("label"))
        note = f' <tspan class="c-note">{_esc(row["note"])}</tspan>' if row.get("note") else ""
        parts.append(
            f'<text class="c-label" x="{_f(left - 10)}" y="{_f(y + bar_h / 2 + 4)}" text-anchor="end">{label}{note}</text>'
        )
        for seg in row.get("segments", []):
            count = int(seg.get("count", 0))
            if count <= 0:
                continue
            w = plot_w * count / total_max
            draw_w = max(w - 2, 0.5)
            tip = f"{row.get('label')}\n{seg.get('label')}: {count} of {total}"
            parts.append(
                f'<g class="c-seg" data-tip="{_esc(tip)}">'
                f'<rect class="c-fill {_esc(seg.get("cls", ""))}" x="{_f(x)}" y="{_f(y)}" width="{_f(draw_w)}" height="{bar_h}" rx="2"/>'
                "</g>"
            )
            x += w
        parts.append(f'<text class="c-value" x="{_f(x + 6)}" y="{_f(y + bar_h / 2 + 4)}">{total}</text>')
    return (
        f'<svg class="chart stacked" viewBox="0 0 {width} {height}" role="img" aria-label="stacked bar chart">'
        + "".join(parts)
        + "</svg>"
    )


def histogram(
    bins: Sequence[Mapping[str, Any]],
    width: int = 640,
    height: int = 200,
) -> str:
    """Vertical columns; ``bins`` = ``{label, count, tip}``."""
    if not bins:
        return '<p class="muted">Nothing to plot.</p>'
    left, right, top, bottom = 36.0, 12.0, 16.0, 30.0
    plot_w, plot_h = width - left - right, height - top - bottom
    n = len(bins)
    slot = plot_w / n
    bar_w = min(24.0, slot * 0.6)
    max_count = max((int(b.get("count", 0)) for b in bins), default=1) or 1
    parts: List[str] = []
    for tick in range(0, max_count + 1, max(1, max_count // 4 or 1)):
        y = top + plot_h * (1 - tick / max_count)
        parts.append(f'<line class="c-grid" x1="{_f(left)}" x2="{_f(left + plot_w)}" y1="{_f(y)}" y2="{_f(y)}"/>')
        parts.append(f'<text class="c-axis" x="{_f(left - 8)}" y="{_f(y + 4)}" text-anchor="end">{tick}</text>')
    for i, b in enumerate(bins):
        count = int(b.get("count", 0))
        h = plot_h * count / max_count
        x = left + slot * i + (slot - bar_w) / 2
        y = top + plot_h - h
        parts.append(
            f'<g class="c-col" data-tip="{_esc(b.get("tip", ""))}">'
            f'<rect class="c-hit" x="{_f(left + slot * i)}" y="{_f(top)}" width="{_f(slot)}" height="{_f(plot_h)}"/>'
            f'<path class="c-fill {_esc(b.get("cls", ""))}" d="{_rounded_vbar(x, y, bar_w, h)}"/>'
            f'<text class="c-axis" x="{_f(left + slot * i + slot / 2)}" y="{_f(height - 10)}" text-anchor="middle">{_esc(b.get("label"))}</text>'
            + (f'<text class="c-value" x="{_f(x + bar_w / 2)}" y="{_f(y - 6)}" text-anchor="middle">{count}</text>' if count else "")
            + "</g>"
        )
    return (
        f'<svg class="chart histogram" viewBox="0 0 {width} {height}" role="img" aria-label="score distribution">'
        + "".join(parts)
        + "</svg>"
    )
