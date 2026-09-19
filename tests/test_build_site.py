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
    out = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", "dashboard.html", "report.html", site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    _check_html(page)
    assert "No runs recorded yet" in page
    assert '<div class="l">golden cases</div>' not in page
    # no dashboard file next to the page, so no dead link: the button falls back to the repo
    assert 'href="dashboard.html"' not in page
    assert site.REPO_URL in page


def test_one_run_fills_the_stats_strip(site, tmp_path):
    history = _write_history(tmp_path, [_run(0.875)])
    out_dir = tmp_path / "site"
    out_dir.mkdir()
    (out_dir / "dashboard.html").write_text("<html></html>", encoding="utf-8")
    out = site.build(history, out_dir / "index.html", "dashboard.html", "report.html", site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    _check_html(page)
    assert "87.5%" in page and ">16<" in page and "100.0%" in page and "0.929" in page and "5 / 29" in page
    assert 'href="dashboard.html"' in page
    assert 'href="report.html"' not in page  # no report file next to the page


def test_three_runs_count_and_latest_wins(site, tmp_path):
    history = _write_history(tmp_path, [_run(0.5), _run(0.75), _run(1.0)])
    (history / "broken.json").write_text("{", encoding="utf-8")
    (history / "foreign.json").write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    out = site.build(history, tmp_path / "site" / "index.html", None, None, site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    _check_html(page)
    assert ">3<" in page and "100.0%" in page and "50.0%" not in page


def test_hostile_strings_are_escaped(site, tmp_path):
    hostile = '<script>alert("x")</script>'
    history = _write_history(tmp_path, [_run(1.0, hostile=hostile)])
    out = site.build(history, tmp_path / "site" / "index.html", None, None, site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    assert hostile not in page
    assert "&lt;script&gt;" in page
    _check_html(page)


def test_cli_entry_point(site, tmp_path, capsys, monkeypatch):
    history = _write_history(tmp_path, [_run(1.0)])
    out = tmp_path / "site" / "index.html"
    assert site.main(["--history-dir", str(history), "--out", str(out)]) == 0
    assert out.is_file()
    assert "1 run(s) in history" in capsys.readouterr().out


def test_absolute_dashboard_url_is_kept(site, tmp_path):
    history = _write_history(tmp_path, [_run(1.0)])
    out = site.build(history, tmp_path / "site" / "index.html", "https://example.invalid/dash", None, site.REPO_URL)
    assert 'href="https://example.invalid/dash"' in out.read_text(encoding="utf-8")


# ----------------------------------------------------------------- desktop


@pytest.fixture(scope="module")
def page(site, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("desktop")
    history = _write_history(tmp_path, [_run(0.875)])
    out = site.build(history, tmp_path / "site" / "index.html", None, None, site.REPO_URL)
    return out.read_text(encoding="utf-8")


def test_tabbed_panel_markup(page):
    tabs = re.findall(r'<button class="tab" role="tab" id="([^"]+)" aria-controls="([^"]+)" aria-selected="(true|false)"', page)
    assert [t[0] for t in tabs] == ["tab-gate", "tab-target", "tab-numbers"]
    assert [t[2] for t in tabs] == ["true", "false", "false"]
    for _tab_id, panel_id, _selected in tabs:
        assert 'role="tabpanel" id="' + panel_id + '"' in page
    assert page.count('role="tabpanel"') == 3
    for label in ("Run the gate", "Point it at your RAG", "See the numbers"):
        assert ">" + label + "</button>" in page
    assert "--target http://localhost:8000/ask" in page and "--target myapp.rag:answer" in page


def test_desktop_icons_in_order(page):
    icons = re.findall(r'<a class="dicon" href="#win-([a-z]+)" data-open="\1">.*?<span>([^<]+)</span></a>', page, re.S)
    keys = [k for k, _ in icons]
    labels = [label for _, label in icons]
    assert keys[:7] == ["home", "gate", "golden", "metrics", "docs", "demo", "author"]
    assert keys[7:] == ["about", "changelog", "casestudy", "examples", "hire", "trash"]
    assert "The regression gate" in labels and "Talk to the author" in labels and "Hire me" in labels
    assert ">DEMO</text>" in page  # the orange DEMO badge icon


def test_every_icon_has_a_window(site, page):
    assert '<section class="win main-win open" id="win-home"' in page
    for key in site.WINDOW_KEYS:
        if key != "home":
            assert '<section class="win sub" id="win-' + key + '"' in page
    assert page.count('<section class="win') == len(site.WINDOW_KEYS)
    # the joke and the point
    assert "Not deleted. Kept as documented failures." in page
    assert "out-of-scope refused" in page and "case-study/dashboard.html" in page
    assert "0.603" in page and "0.707" in page
    _check_html(page)


def test_windows_render_without_javascript(page):
    assert page.startswith("<!DOCTYPE html>\n<html lang=\"en\" class=\"no-js\">")
    # hidden only when the script has swapped no-js for js; static HTML shows everything stacked
    assert ".js .win:not(.open){display:none}" in page
    assert ".js .tabpanel:not(.active){display:none}" in page
    assert "replace('no-js','js')" in page
    # icons are real links to the stacked windows, not script-only buttons
    assert 'href="#win-trash" data-open="trash"' in page


def test_changelog_is_optional_and_escaped(site, tmp_path):
    history = _write_history(tmp_path, [_run(1.0)])
    out = tmp_path / "site" / "index.html"
    without = site.build(history, out, None, None, site.REPO_URL).read_text(encoding="utf-8")
    assert "No git history was available" in without
    subjects = ["Add the desktop landing page", "Fix <b>escaping</b> in the log"]
    with_log = site.build(history, out, None, None, site.REPO_URL, changelog=subjects).read_text(encoding="utf-8")
    assert "No git history was available" not in with_log
    assert "<li>Add the desktop landing page</li>" in with_log
    assert "Fix &lt;b&gt;escaping&lt;/b&gt; in the log" in with_log and "<b>escaping</b>" not in with_log
    _check_html(with_log)


def test_recent_commits_never_raises(site, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("git is not installed")
    monkeypatch.setattr(site.subprocess, "run", boom)
    assert site.recent_commits() == []


def test_wallpaper_is_an_inline_svg_tile(site, page):
    assert site.LIGHT_TILE.startswith('url("data:image/svg+xml,') and "%23" in site.LIGHT_TILE
    assert len(site.LIGHT_TILE) < 4096 and len(site.DARK_TILE) < 4096
    assert site.LIGHT_TILE == site.grass_tile(["#6E8F4F", "#7FA35B", "#5C7A40", "#8DB06A"], ".8")  # deterministic
    assert "--tile:" + site.LIGHT_TILE in page and "--tile:" + site.DARK_TILE in page
