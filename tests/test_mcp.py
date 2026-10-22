"""MCP / tool-poisoning: the obedient agent exfiltrates, the tool-policy stops it."""

from __future__ import annotations

from ragprobe.security.mcp import SCENARIOS, render_markdown, run_mcp


def test_scenarios_cover_the_three_techniques():
    techniques = {s.technique for s in SCENARIOS}
    assert techniques == {"description-poison", "rug-pull", "cross-tool"}


def test_undefended_agent_exfiltrates_on_every_scenario():
    report = run_mcp(["none"])
    assert report["by_defense"]["none"]["asr"] == 1.0  # worst case: all leak


def test_tool_policy_blocks_every_exfiltration():
    report = run_mcp(["tool-policy"])
    b = report["by_defense"]["tool-policy"]
    assert b["asr"] == 0.0
    assert b["blocked_by_policy"] == b["trials"]  # the capability rule caught them all


def test_detector_withholds_some_poison_but_is_not_sufficient_alone():
    report = run_mcp(["detector"])
    b = report["by_defense"]["detector"]
    assert b["withheld"] > 0           # it catches some poisoned tool text
    assert b["asr"] > 0.0              # but not all - an action defence is still needed


def test_layered_stops_everything_two_ways():
    report = run_mcp(["layered"])
    b = report["by_defense"]["layered"]
    assert b["asr"] == 0.0
    # some poison is withheld by the screen, the rest blocked by the policy
    assert b["withheld"] > 0 and b["blocked_by_policy"] > 0


def test_every_result_carries_wilson_interval_and_detail():
    report = run_mcp(["none", "tool-policy"])
    assert len(report["detail"]) == 2 * len(SCENARIOS)
    for b in report["by_defense"].values():
        assert len(b["asr_ci95"]) == 2


def test_markdown_tells_the_story():
    md = render_markdown(run_mcp(["none", "tool-policy"]))
    assert "MCP and tool-poisoning" in md and "Exfiltration rate" in md
    assert "tool-policy" in md
