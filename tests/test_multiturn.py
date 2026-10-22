"""Multi-turn attacks succeed undefended, partly evade per-turn screening."""

from __future__ import annotations

from ragprobe.security.multiturn import ATTACKS, render_markdown, run_multiturn


def test_attacks_cover_the_techniques():
    assert {a.technique for a in ATTACKS} == {"split-marker", "role-escalation", "crescendo"}


def test_all_multiturn_attacks_succeed_undefended():
    report = run_multiturn(["none"])
    assert report["by_defense"]["none"]["asr"] == 1.0


def test_detector_catches_some_turns_but_not_all():
    report = run_multiturn(["detector"])
    b = report["by_defense"]["detector"]
    assert b["any_turn_withheld"] > 0     # it flags some turns
    assert 0.0 < b["asr"] < 1.0           # but the chains are not fully stopped


def test_defences_reduce_success():
    report = run_multiturn(["none", "layered"])
    assert report["by_defense"]["layered"]["asr"] < report["by_defense"]["none"]["asr"]


def test_marker_assembly_still_slips_through_layered():
    # the honest finding: a marker-assembly chain is not a secret the output filter
    # redacts, and no single turn is flagged, so it survives the layered defence
    report = run_multiturn(["layered"])
    survivors = [d for d in report["detail"]
                 if d["defense"] == "layered" and d["goal"] == "say_marker" and d["success"]]
    assert survivors, "expected at least one marker-assembly chain to survive layered"


def test_markdown_renders():
    md = render_markdown(run_multiturn(["none", "layered"]))
    assert "Multi-turn (crescendo) attacks" in md and "Attack-success" in md
