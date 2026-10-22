"""Text stays readable: every text colour meets WCAG AA (4.5:1) on its backgrounds.

Reads the real design tokens out of all four pages' CSS, in both themes, so a later
colour tweak cannot quietly bring back grey-on-grey text.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AA = 4.5

# token-name aliases: each page names the same role differently
TEXT_ROLES = {
    "ink": ("ink", "text"),
    "muted": ("muted", "text-2", "text-dim"),
    "faint": ("faint", "text-3"),
    "accent-text": ("accent-text",),
}
BG_ROLES = {"bg": ("bg",), "panel": ("panel", "surface"), "panel-2": ("panel-2", "surface-2")}


def _landing_css() -> str:
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CSS


def _pages():
    from ragprobe.dashboard import html as dash
    from ragprobe.reporting import html as rep
    from ragprobe.security import report_html as sec
    return {"landing": _landing_css(), "security": sec._CSS,
            "dashboard": dash._CSS, "report": rep._CSS}


def _tokens(css: str, light: bool) -> dict:
    pattern = r':root\[data-theme="light"\]\s*\{([^}]*)\}' if light else r':root\s*\{([^}]*)\}'
    match = re.search(pattern, css)
    assert match, "theme block not found"
    return {k: v.strip() for k, v in re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\b", match.group(1))}


def _lum(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _pick(tokens: dict, names) -> str | None:
    return next((tokens[n] for n in names if n in tokens), None)


@pytest.mark.parametrize("light", [False, True], ids=["dark", "light"])
@pytest.mark.parametrize("page", ["landing", "security", "dashboard", "report"])
def test_text_colours_meet_aa_on_every_background(page, light):
    tokens = _tokens(_pages()[page], light)
    backgrounds = {n: _pick(tokens, names) for n, names in BG_ROLES.items()}
    backgrounds = {n: c for n, c in backgrounds.items() if c}
    assert backgrounds, f"{page}: no background tokens found"
    failures = []
    for role, names in TEXT_ROLES.items():
        colour = _pick(tokens, names)
        if colour is None:
            continue  # this page has no such role (e.g. the report has no 'faint')
        for bg_name, bg in backgrounds.items():
            ratio = _ratio(colour, bg)
            if ratio < AA:
                failures.append(f"{role} {colour} on {bg_name} {bg} = {ratio:.2f}:1")
    assert not failures, f"{page} ({'light' if light else 'dark'}): " + "; ".join(failures)


def test_every_page_defines_an_accent_text_colour():
    for page, css in _pages().items():
        assert "--accent-text" in css, f"{page} must define --accent-text for readable orange text"
