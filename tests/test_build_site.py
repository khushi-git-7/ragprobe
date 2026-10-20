"""The landing page generator (scripts/build_site.py) renders a valid, self-contained page."""

from __future__ import annotations

import html.parser
import importlib.util
import json
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_site.py"
VOID = {"meta", "link", "br", "img", "input", "hr", "path", "rect", "circle", "line"}


@pytest.fixture(scope="module")
def site():
    spec = importlib.util.spec_from_file_location("build_site", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Balance(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(tag)


def _check_html(page: str) -> None:
    parser = _Balance()
    parser.feed(page)
    assert not parser.errors and not parser.stack, (parser.errors, parser.stack)
    # Nothing is fetched from the network: no external CSS/JS/img, only the repo link.
    external = [
        url for url in re.findall(r'(?:src|href)="([^"]+)"', page)
        if url.startswith("http") and "github.com/khushi-git-7/ragprobe" not in url
    ]
    assert external == []


def _run(pass_rate: float, total: int = 16, hostile: str = "") -> dict:
    return {
        "started_at": "2026-09-19T12:00:00Z" + hostile,
        "provider": "stub" + hostile,
        "pipeline": {"documents": 5, "chunks": 29},
        "summary": {
            "total": total,
            "pass_rate": pass_rate,
            "retrieval": {"hit_rate@3": 1.0, "mrr": 0.9286},
            "by_category": {"a": {}, "b": {}},
        },
        "cases": [{"id": "x"}] * total,
    }


def _write_history(tmp_path: Path, runs) -> Path:
    history = tmp_path / "history"
    history.mkdir()
    for index, run in enumerate(runs):
        (history / "run-{:04d}.json".format(index + 1)).write_text(json.dumps(run), encoding="utf-8")
    return history


def test_zero_runs_renders_an_honest_empty_state(site, tmp_path):
    out = site.build(tmp_path / "missing", tmp_path / "site" / "index.html",
                     "dashboard.html", "report.html", site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    _check_html(page)
    assert "No runs recorded yet" in page
    assert '<div class="l">golden cases</div>' not in page
    # no dashboard file next to the page, so no dead link
    assert 'href="dashboard.html"' not in page
    assert site.REPO_URL in page


def test_one_run_fills_the_quality_section(site, tmp_path):
    history = _write_history(tmp_path, [_run(0.875)])
    out_dir = tmp_path / "site"
    out_dir.mkdir()
    (out_dir / "dashboard.html").write_text("<html></html>", encoding="utf-8")
    out = site.build(history, out_dir / "index.html", "dashboard.html", "report.html", site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    _check_html(page)
    assert "87.5%" in page and ">16<" in page and "100.0%" in page and "0.929" in page
    assert 'href="dashboard.html"' in page
    assert 'href="report.html"' not in page  # no report file next to the page


def test_three_runs_latest_wins(site, tmp_path):
    history = _write_history(tmp_path, [_run(0.5), _run(0.75), _run(1.0)])
    (history / "broken.json").write_text("{", encoding="utf-8")
    (history / "foreign.json").write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    out = site.build(history, tmp_path / "site" / "index.html", None, None, site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    _check_html(page)
    assert 'data-count="3"' in page          # three CI runs in the hero
    assert "100.0%" in page and "50.0%" not in page


def test_hostile_strings_are_escaped(site, tmp_path):
    hostile = '<script>alert("x")</script>'
    history = _write_history(tmp_path, [_run(1.0, hostile=hostile)])
    out = site.build(history, tmp_path / "site" / "index.html", None, None, site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    assert hostile not in page
    _check_html(page)


def test_cli_entry_point(site, tmp_path, capsys):
    history = _write_history(tmp_path, [_run(1.0)])
    out = tmp_path / "site" / "index.html"
    assert site.main(["--history-dir", str(history), "--out", str(out)]) == 0
    assert out.is_file()
    assert "1 run(s) in history" in capsys.readouterr().out


def test_absolute_dashboard_url_is_kept(site, tmp_path):
    history = _write_history(tmp_path, [_run(1.0)])
    out = site.build(history, tmp_path / "site" / "index.html",
                     "https://example.invalid/dash", None, site.REPO_URL)
    assert 'href="https://example.invalid/dash"' in out.read_text(encoding="utf-8")


def test_has_the_security_story_and_animation(site, tmp_path):
    out = site.build(tmp_path / "missing", tmp_path / "site" / "index.html",
                     None, None, site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    # the designed sections are present as real on-page content
    for marker in ("AI safety filters are far weaker in German", "OWASP Top 10 scorecard",
                   "Layered defence takes attacks to zero", "Three apps, one attacker"):
        assert marker in page
    # it is animated and interactive
    assert "@keyframes fly" in page and "data-count=" in page and "class=\"reveal\"" in page
    assert "prefers-reduced-motion" in page


def test_security_link_shown_when_file_present(site, tmp_path):
    out_dir = tmp_path / "site"
    out_dir.mkdir()
    (out_dir / "security.html").write_text("<html></html>", encoding="utf-8")
    out = site.build(tmp_path / "missing", out_dir / "index.html", None, None,
                     site.REPO_URL, security="security.html")
    assert 'href="security.html"' in out.read_text(encoding="utf-8")
