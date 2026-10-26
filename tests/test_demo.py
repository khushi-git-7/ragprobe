"""`ragprobe demo` tells a real, honest scan -> defend -> rescan story."""

from __future__ import annotations

from pathlib import Path

from ragprobe.cli import EXIT_OK, main
from ragprobe.demo import STAGES, passes, render, run_demo
from ragprobe.resources import bundled_path

ROOT = Path(__file__).resolve().parents[1]


def _report():
    return run_demo(bundled_path("security/attacks.yaml"), base_dir=ROOT)


def test_stages_run_in_the_order_a_team_would_try_them():
    assert [s["defense"] for s in _report()["stages"]] == [d for d, _ in STAGES]


def test_undefended_app_fails_and_layered_passes():
    stages = _report()["stages"]
    assert stages[0]["grade"] == "F" and stages[-1]["grade"] == "A"
    assert stages[-1]["asr"] < stages[0]["asr"]
    assert passes(_report())


def test_every_stage_reports_a_false_block_rate_and_per_risk_grades():
    for stage in _report()["stages"]:
        assert 0.0 <= stage["false_block"] <= 1.0
        assert stage["risks"] and all(r["grade"] in "ABCDF" for r in stage["risks"])


def test_demo_is_honest_that_the_victim_is_simulated():
    text = render(_report())
    assert "simulated" in text.lower() and "worst-case" in text.lower()
    # and it explains why the prompt-only step does not move the number
    assert "ignores prompt-level wording" in text


def test_cli_demo_exits_ok_and_writes_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    out = tmp_path / "demo.json"
    assert main(["demo", "--out", str(out)]) == EXIT_OK
    assert out.is_file()
    assert "RAGProbe demo - Acme Helpdesk" in capsys.readouterr().out
