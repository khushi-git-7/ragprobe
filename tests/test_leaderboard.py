"""The model leaderboard: plumbing, ranking and paired significance (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ragprobe.resources import bundled_path
from ragprobe.bench.leaderboard import render_markdown, run_leaderboard
from ragprobe.security.victims import Reply, Victim, get_victim

ROOT = Path(__file__).resolve().parents[1]
CAT = bundled_path("bench/v1/attacks.jsonl")


class _SafeVictim(Victim):
    """A model that refuses everything, so no attack ever succeeds."""
    name = "safe"
    deterministic = True

    def respond(self, messages, tools=None):
        return Reply(content="I'm sorry, I can't help with that request.")


def _build_factory(safe_names):
    def build(spec, api_key, max_tokens=512):
        if spec.name in safe_names:
            v = _SafeVictim()
        else:
            v = get_victim("simulated")
        v.name = spec.name
        return v
    return build


def test_missing_key_is_reported_clearly():
    with pytest.raises(ValueError):
        run_leaderboard(CAT, ["groq-qwen"], base_dir=ROOT, get_key=lambda e: None)


def test_safer_model_ranks_first():
    # the refusing model lets nothing through; the obey model is wide open
    report = run_leaderboard(
        CAT, ["groq-qwen", "groq-gptoss"], split="test", defenses=["none", "layered"],
        base_dir=ROOT, get_key=lambda e: "x",
        build=_build_factory(safe_names={"groq-gptoss"}))
    ranked = report["models"]
    assert ranked[0]["model"] == "groq-gptoss" and ranked[0]["rank"] == 1
    assert ranked[1]["model"] == "groq-qwen"
    # and the gap to the leader is tested for significance
    paired = report["paired_mcnemar"]
    assert paired and paired[0]["leader"] == "groq-gptoss"
    assert paired[0]["discordant"] > 0  # the two models disagree on many attacks


def test_identical_models_are_not_a_significant_gap():
    report = run_leaderboard(
        CAT, ["groq-qwen", "groq-gptoss"], split="test", base_dir=ROOT,
        get_key=lambda e: "x", build=_build_factory(safe_names=set()))
    paired = report["paired_mcnemar"]
    assert paired and paired[0]["discordant"] == 0 and paired[0]["p_value"] == 1.0


def test_markdown_has_a_ranked_table():
    report = run_leaderboard(
        CAT, ["groq-qwen", "groq-gptoss"], split="test", base_dir=ROOT,
        get_key=lambda e: "x", build=_build_factory(safe_names={"groq-gptoss"}))
    md = render_markdown(report)
    assert "Model security leaderboard" in md and "Rank" in md
    assert "groq-qwen" in md and "groq-gptoss" in md
