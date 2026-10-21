"""`ragprobe doctor` reports the real state of the install, data and keys."""

from __future__ import annotations

from pathlib import Path

from ragprobe.doctor import FAIL, OK, WARN, has_failures, render, run_checks

ROOT = Path(__file__).resolve().parents[1]


def _by_name(checks):
    return {c.name: c for c in checks}


def test_healthy_checkout_passes_core_checks(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    checks = run_checks(ROOT)
    by = _by_name(checks)
    assert by["Python"].status == OK
    assert by["Attack corpus"].status == OK
    assert by["Bench v1"].status == OK and "runnable attacks" in by["Bench v1"].detail
    assert by["Benign corpus"].status == OK
    assert not has_failures(checks)


def test_missing_data_is_a_failure(tmp_path):
    checks = run_checks(tmp_path)  # an empty dir: datasets are absent
    by = _by_name(checks)
    assert by["Attack corpus"].status == FAIL
    assert by["Benign corpus"].status == FAIL
    assert by["Bench v1"].status == WARN  # bench is a warn (you can build it)
    assert has_failures(checks)


def test_absent_keys_are_warnings_not_failures(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    by = _by_name(run_checks(ROOT))
    assert by["Groq"].status == WARN and by["Gemini"].status == WARN


def test_render_shows_a_line_per_check_and_a_verdict():
    text = render(run_checks(ROOT))
    assert "RAGProbe doctor" in text
    assert "Python" in text and "Bench v1" in text


def test_cli_doctor_exits_ok_on_a_healthy_checkout(monkeypatch, capsys):
    from ragprobe.cli import EXIT_OK, main
    monkeypatch.chdir(ROOT)
    assert main(["doctor"]) == EXIT_OK
    assert "doctor" in capsys.readouterr().out.lower()
