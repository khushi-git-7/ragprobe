"""The attack lab: real results, rendered in the site's design, wired into the flow."""

from __future__ import annotations

import html.parser
import re
from pathlib import Path

import pytest

from ragprobe.security.lab import facts, run_lab
from ragprobe.security.lab_html import render

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def lab():
    return run_lab(ROOT / "datasets" / "security" / "attacks.yaml", base_dir=ROOT)


@pytest.fixture(scope="module")
def page(lab):
    return render(lab)


class _Balance(html.parser.HTMLParser):
    VOID = {"meta", "br", "hr", "img", "input", "link"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(tag)


def test_lab_collects_all_four_results(lab):
    assert set(lab) >= {"demo", "mcp", "multiturn", "obfuscation", "facts"}


def test_facts_are_the_real_headline_numbers(lab):
    f = lab["facts"]
    assert f["demo_grade_before"] == "F" and f["demo_grade_after"] == "A"
    assert f["mcp_undefended"] == 1.0 and f["mcp_policy"] == 0.0
    assert f["multiturn_layered"] < f["multiturn_undefended"]
    assert f["obfuscation_raw"] == 0.0 and f["obfuscation_normalized"] > 0.5
    assert facts(lab["demo"], lab["mcp"], lab["multiturn"], lab["obfuscation"]) == f


def test_page_has_every_section_with_a_jump_link(page):
    for anchor in ("story", "mcp", "multiturn", "obfuscation"):
        assert f"id='{anchor}'" in page and f"href='#{anchor}'" in page


def test_page_is_wellformed_and_self_contained(page):
    parser = _Balance()
    parser.feed(page)
    assert not parser.errors and not parser.stack, (parser.errors, parser.stack)
    external = [u for u in re.findall(r"(?:src|href)=[\"']([^\"']+)[\"']", page)
                if u.startswith("http") and "github.com/khushi-git-7/ragprobe" not in u]
    assert external == []


def test_page_is_honest_about_the_simulated_victim_and_the_gap(page):
    assert "Worst-case drill" in page and "simulated" in page
    # the layered multi-turn gap is reported, not hidden
    assert "An honest gap" in page and "mt-split-marker" in page


def test_page_is_part_of_the_site_flow(page):
    assert "href='lab.html' class='on'" in page or 'href="lab.html" class="on"' in page
    assert "Step 3 of 5" in page and 'href="dashboard.html"' in page


def test_cli_builds_the_lab_page_and_json(tmp_path, monkeypatch, capsys):
    from ragprobe.cli import EXIT_OK, main

    monkeypatch.chdir(ROOT)
    out, page_path = tmp_path / "lab.json", tmp_path / "lab.html"
    assert main(["security", "lab", "--out", str(out), "--html", str(page_path)]) == EXIT_OK
    assert out.is_file() and page_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "attack lab: demo grade F -> A" in capsys.readouterr().out
