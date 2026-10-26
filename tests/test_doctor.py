"""`ragprobe doctor` reports the real state of the install, data and keys."""

from __future__ import annotations

from pathlib import Path

from ragprobe.doctor import FAIL, OK, WARN, has_failures, render, run_checks
from ragprobe.resources import bundled_path

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


def test_an_empty_directory_is_healthy_because_the_data_ships_with_the_package(tmp_path):
    """The install is what matters, not where you stand: a pip user has no checkout."""
    checks = run_checks(tmp_path)
    by = _by_name(checks)
    assert by["Attack corpus"].status == OK
    assert by["Benign corpus"].status == OK
    assert by["Bench v1"].status == OK
    assert not has_failures(checks)
    assert by["Attack corpus"].detail == "shipped with the package"


def test_a_local_copy_is_used_and_named(tmp_path):
    """Your own ./datasets copy wins, and the report says so instead of claiming ours."""
    local = tmp_path / "datasets" / "security"
    local.mkdir(parents=True)
    (local / "attacks.yaml").write_text(
        bundled_path("security/attacks.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    by = _by_name(run_checks(tmp_path))
    assert by["Attack corpus"].status == OK
    assert by["Attack corpus"].detail.endswith("attacks.yaml")
    assert "shipped" not in by["Attack corpus"].detail


def test_a_damaged_install_is_a_failure(tmp_path, monkeypatch):
    """If the shipped data really is gone, say so with a fix, and fail."""
    import ragprobe.resources as resources

    monkeypatch.setattr(resources, "BUNDLED", tmp_path / "gone")
    checks = run_checks(tmp_path)
    by = _by_name(checks)
    assert by["Attack corpus"].status == FAIL
    assert "reinstall" in by["Attack corpus"].detail
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
