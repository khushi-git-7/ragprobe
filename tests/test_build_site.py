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
                   "the layered defence holds", "Three apps, one attacker"):
        assert marker in page
    # it is animated and interactive
    assert "@keyframes fly" in page and "data-count=" in page and "class=\"reveal\"" in page
    assert "prefers-reduced-motion" in page


def test_benchmark_section_is_data_driven_from_the_catalogue(site, tmp_path):
    out = site.build(tmp_path / "missing", tmp_path / "site" / "index.html",
                     None, None, site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    bs = site.bench_best()
    assert bs is not None, "the committed benchmark catalogue should be readable"
    assert 'id="benchmark"' in page
    assert "Measured on a benchmark you can cite" in page
    # the real catalogue totals appear as count-up targets
    assert f'data-count="{bs["total"]}"' in page and f'data-count="{bs["attacks"]}"' in page
    # the datasheet link stays inside the repo (no external fetch)
    assert "src/ragprobe/datasets/bench/v2/datasheet.md" in page


def test_hero_cta_leads_into_the_product_not_the_repo(site, tmp_path):
    out_dir = tmp_path / "site"
    out_dir.mkdir()
    (out_dir / "security.html").write_text("<html></html>", encoding="utf-8")
    out = site.build(tmp_path / "missing", out_dir / "index.html", None, None,
                     site.REPO_URL, security="security.html")
    page = out.read_text(encoding="utf-8")
    # the primary action is what a visitor came to do; the sample report is secondary
    cta = page.split('<div class="cta">')[1].split("</div>")[0]
    assert 'class="btn" href="#start">Scan your app' in cta
    assert 'href="security.html"' in cta and "sample report" in cta
    assert "Explore the project" not in page
    hero = page.split('class="term"')[0]  # everything up to the terminal in the hero
    assert f'class="btn" href="{site.REPO_URL}"' not in hero  # repo is not the hero CTA


def test_hero_without_any_published_page_falls_back_in_page(site, tmp_path):
    out = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                     site.REPO_URL)
    page = out.read_text(encoding="utf-8")
    assert "See how it works" in page  # scrolls down, still not off to the repo


def test_security_link_shown_when_file_present(site, tmp_path):
    out_dir = tmp_path / "site"
    out_dir.mkdir()
    (out_dir / "security.html").write_text("<html></html>", encoding="utf-8")
    out = site.build(tmp_path / "missing", out_dir / "index.html", None, None,
                     site.REPO_URL, security="security.html")
    assert 'href="security.html"' in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------- the site's flow

def _site_with(tmp_path, *names):
    out_dir = tmp_path / "site"
    out_dir.mkdir()
    for name in names:
        (out_dir / name).write_text("<html></html>", encoding="utf-8")
    return out_dir


def test_hero_label_says_what_the_button_really_opens(site, tmp_path):
    # the live-site bug: the button promised a security scan but opened the dashboard
    out_dir = _site_with(tmp_path, "dashboard.html")
    page = site.build(tmp_path / "missing", out_dir / "index.html", "dashboard.html", None,
                      site.REPO_URL).read_text(encoding="utf-8")
    cta = page.split('<div class="cta">')[1].split("</div>")[0]
    assert 'href="dashboard.html"' in cta and "quality dashboard" in cta
    assert "security report" not in cta


def test_hero_label_follows_the_first_page_that_exists(site, tmp_path):
    out_dir = _site_with(tmp_path, "security.html", "lab.html", "dashboard.html")
    page = site.build(tmp_path / "missing", out_dir / "index.html", "dashboard.html", None,
                      site.REPO_URL).read_text(encoding="utf-8")
    cta = page.split('<div class="cta">')[1].split("</div>")[0]
    assert 'href="security.html"' in cta and "See a sample report" in cta


def test_nav_links_into_the_product_pages_that_exist(site, tmp_path):
    out_dir = _site_with(tmp_path, "security.html", "lab.html", "dashboard.html")
    page = site.build(tmp_path / "missing", out_dir / "index.html", "dashboard.html", None,
                      site.REPO_URL).read_text(encoding="utf-8")
    menu = page.split('<span class="links">')[1].split("</span>")[0]
    for href in ("security.html", "lab.html", "dashboard.html"):
        assert f'href="{href}"' in menu


def test_nav_has_no_dead_links_when_pages_are_missing(site, tmp_path):
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    menu = page.split('<span class="links">')[1].split("</span>")[0]
    for href in ("security.html", "lab.html", "dashboard.html"):
        assert href not in menu


def test_phone_keeps_a_way_into_the_product(site, tmp_path):
    # the live-site bug: below 860px the whole menu was hidden
    css = site.CSS
    assert "nav .links{display:none}" not in css
    assert "nav .links a.a{display:none}" in css      # only the in-page anchors go


def test_lab_section_quotes_the_real_run(site, tmp_path):
    import json

    lab_json = tmp_path / "lab.json"
    lab_json.write_text(json.dumps({"facts": {
        "mcp_undefended": 1.0, "mcp_policy": 0.0,
        "multiturn_undefended": 1.0, "multiturn_layered": 0.5,
        "obfuscation_raw": 0.0, "obfuscation_normalized": 0.83}}), encoding="utf-8")
    out_dir = _site_with(tmp_path, "lab.html")
    page = site.build(tmp_path / "missing", out_dir / "index.html", None, None, site.REPO_URL,
                      lab_json=lab_json).read_text(encoding="utf-8")
    assert 'id="lab"' in page and "Attacks that don&rsquo;t look like attacks" in page
    assert "100% &rarr; 0%" in page and "100% &rarr; 50%" in page and "0% &rarr; 83%" in page
    assert 'href="lab.html"' in page and "Open the attack lab" in page


def test_lab_section_without_a_run_shows_no_invented_numbers(site, tmp_path):
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    assert 'id="lab"' in page and "&rarr; 0%" not in page.split('id="lab"')[1].split("</section>")[0]


LIVE = {"bench": "Bench v1, all 82 runnable attacks", "settings": "temperature 0, one trial",
        "models": [{"name": "Model A", "none": [4, 82, 0.02, 0.12],
                    "layered": [2, 82, 0.01, 0.09], "utility": [20, 26, 0.58, 0.88]}]}


def test_real_model_section_quotes_the_results_with_intervals(site, tmp_path):
    live = tmp_path / "live.json"
    live.write_text(json.dumps(LIVE), encoding="utf-8")
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL, live_json=live).read_text(encoding="utf-8")
    section = page.split('id="models"')[1].split("</section>")[0]
    assert "Model A" in section and "5%" in section and "2%" in section and "77%" in section
    assert "4 of 82" in section and "95% CI 2&ndash;12%" in section
    assert "limitations.md" in section and "may be noise" in section


def test_real_model_section_shows_leaks_and_the_extended_set(site, tmp_path):
    data = json.loads(json.dumps(LIVE))
    data["models"][0]["leak_secret"] = [0, 33]
    data["models"][0]["extended"] = {"none": [14, 138, 0.06, 0.16], "layered": [10, 138, 0.04, 0.13]}
    live = tmp_path / "live.json"
    live.write_text(json.dumps(data), encoding="utf-8")
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL, live_json=live).read_text(encoding="utf-8")
    section = page.split('id="models"')[1].split("</section>")[0]
    assert "<b>0 of 33</b>" in section and "Extended set of 138" in section
    assert "<b>10%</b> &rarr; <b>7%</b>" in section


def test_real_model_section_is_absent_without_results(site, tmp_path):
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL, live_json=tmp_path / "nope.json").read_text(encoding="utf-8")
    assert 'id="models"' not in page


def test_real_model_section_ignores_a_broken_file(site, tmp_path):
    bad = tmp_path / "live.json"
    bad.write_text("{not json", encoding="utf-8")
    assert site.live_models(bad) is None


def test_scorecard_says_it_is_a_simulated_victim(site, tmp_path):
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    assert "simulated worst-case victim" in page.split('id="scorecard"')[1].split("</section>")[0]


def test_ci_builds_the_linked_pages_before_the_landing_page():
    # the root cause of the live-site bug: the landing page was built first, so the
    # pages it should link to did not exist yet
    ci = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    land = ci.index("scripts/build_site.py")
    assert ci.index("ragprobe security run") < land
    assert ci.index("ragprobe security lab") < land


def test_the_quickstart_shows_the_commands_not_just_the_install(site, tmp_path):
    """A visitor who copies one line must end up with something that runs."""
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    start = page.split('id="start"')[1].split("</section>")[0]
    assert "pip install" in start
    assert "ragprobe demo" in start
    assert "ragprobe security scan --url" in start
    assert start.count('class="copy"') == 3  # each command is copyable
    assert "cannot see" in start and "not that the app is safe" in start


def test_the_hero_promises_only_what_the_tool_does(site, tmp_path):
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    hero = page.split('class="term"')[0]
    assert "prompt-injection attacks" in hero and "planted marker" in hero


def test_the_simulated_claim_is_labelled_where_it_is_made(site, tmp_path):
    """The 92% to 0% headline must carry its caveat, not contradict the real numbers."""
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    defence = page.split('id="defence"')[1].split("</section>")[0]
    assert "simulated" in defence and "Lab drill" in defence
    assert 'href="#models"' in defence  # points at the real-model numbers
    scorecard = page.split('id="scorecard"')[1].split("</section>")[0]
    assert "12 hand-written scenarios" in scorecard and "82 attacks in v1, 138 in v2" in scorecard


def test_the_counters_show_their_number_without_javascript(site, tmp_path):
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    assert '<span data-count="138">138</span>' in page
    # every counter already reads its real value; the animation only replays it
    pairs = re.findall(r'<span data-count="([^"]+)"(?: data-suffix="([^"]*)")?>([^<]*)</span>', page)
    assert pairs
    for number, suffix, shown in pairs:
        assert shown == number + (suffix or ""), (number, shown)


def test_the_quality_half_says_it_is_not_security(site, tmp_path):
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    gate = page.split('id="gate"')[1].split("</section>")[0]
    assert "not security" in gate


def test_the_footer_says_who_it_is_for_and_where_to_complain(site, tmp_path):
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    footer = page.split("<footer")[1]
    assert "Python 3.9+" in footer and "/issues" in footer and "can this be hacked" in footer


def test_the_hero_number_comes_from_the_catalogue_not_a_literal(site):
    """A hardcoded attack count would drift from the data the tool actually sends."""
    best = site.bench_best()
    assert best and int(best["attacks"]) >= 82
    assert best["version"] == "v2"  # the largest committed catalogue


def test_get_started_comes_before_the_evidence(site, tmp_path):
    """The hero's button scrolls to it, so it must not be at the bottom of the page."""
    page = site.build(tmp_path / "missing", tmp_path / "site" / "index.html", None, None,
                      site.REPO_URL).read_text(encoding="utf-8")
    assert page.index('id="start"') < page.index('id="benchmark"') < page.index('id="gate"')
