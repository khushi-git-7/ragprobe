"""The shared chrome: nav, theme toggle and the guided page-flow bar."""

from __future__ import annotations

from ragprobe import webui

REPO = "https://github.com/khushi-git-7/ragprobe"


def test_top_nav_marks_the_active_page():
    nav = webui.top_nav("security", REPO)
    assert 'href="security.html" class="on"' in nav
    assert 'href="index.html"' in nav and "GitHub" in nav


def test_top_nav_can_drop_the_toggle():
    assert 'id="tg"' not in webui.top_nav("dashboard", REPO, toggle=False)
    assert 'id="tg"' in webui.top_nav("dashboard", REPO)


def test_page_flow_offers_the_next_step_and_a_position():
    bar = webui.page_flow("security", REPO)
    assert "Step 2 of 5" in bar
    assert 'href="lab.html"' in bar              # next: the attack lab
    assert 'href="index.html"' in bar            # prev
    assert "rpflow-next" in bar


def test_page_flow_first_step_has_no_previous():
    bar = webui.page_flow("overview", REPO)
    assert "Step 1 of 5" in bar
    assert "rpflow-prev" not in bar              # nothing before the overview


def test_page_flow_last_step_points_to_adoption():
    bar = webui.page_flow("report", REPO)
    assert "Step 5 of 5" in bar
    assert REPO in bar                           # ends on "put it in your CI"
    assert "Put it in your CI" in bar


def test_page_flow_is_empty_for_an_unknown_page():
    assert webui.page_flow("not-a-page", REPO) == ""


def test_the_tour_walks_every_page_once_in_order():
    assert [s[0] for s in webui.TOUR] == ["overview", "security", "lab", "dashboard", "report"]
    # every step has a top-nav link too, so the menu and the tour cannot disagree
    assert {s[1] for s in webui.TOUR} == {l[1] for l in webui.SITE_LINKS}


def test_the_lab_sits_between_security_and_the_dashboard():
    mid = webui.page_flow("lab", REPO)
    assert "Step 3 of 5" in mid
    assert 'href="security.html"' in mid and 'href="dashboard.html"' in mid
