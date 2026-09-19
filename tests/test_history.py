"""Tests for the run-history store behind ``ragprobe dashboard``.

A history that silently drops, duplicates or reorders runs would make every trend
on the dashboard a lie, so ordering and tolerance are pinned here.
"""

from __future__ import annotations

import json
from pathlib import Path

from ragprobe.history import (
    History,
    append_run,
    history_filename,
    load_history,
    merge_current,
    next_sequence,
)


def make_run(started_at: str, fingerprint: str = "cfg-aaa", pass_rate: float = 1.0) -> dict:
    return {
        "started_at": started_at,
        "config_fingerprint": fingerprint,
        "dataset_fingerprint": "data-aaa",
        "summary": {"total": 1, "passed": 1, "failed": 0, "pass_rate": pass_rate, "mean_score": 1.0},
        "cases": [{"id": "c1", "passed": True, "score": 1.0}],
    }


class TestFilenames:
    def test_filename_is_sequenced_timestamped_and_fingerprinted(self):
        name = history_filename(make_run("2026-09-18T17:30:23Z", "7501f486bed1"), 7)
        assert name == "run-0007-20260918T173023Z-7501f486bed1.json"

    def test_unparseable_timestamp_does_not_crash(self):
        name = history_filename({"started_at": "yesterday", "config_fingerprint": "x"}, 1)
        assert name == "run-0001-unknown-x.json"

    def test_next_sequence_is_one_past_the_highest(self, tmp_path: Path):
        assert next_sequence(tmp_path) == 1
        (tmp_path / "run-0003-20260918T173023Z-abc.json").write_text("{}")
        (tmp_path / "run-0001-20260918T173023Z-abc.json").write_text("{}")
        assert next_sequence(tmp_path) == 4


class TestAppendAndLoad:
    def test_append_creates_the_directory_and_writes_json(self, tmp_path: Path):
        run = make_run("2026-09-18T17:30:23Z")
        path = append_run(tmp_path / "history", run)
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8")) == run

    def test_runs_in_the_same_second_keep_their_order(self, tmp_path: Path):
        """``started_at`` has second resolution; the sequence number must break ties."""
        history_dir = tmp_path / "history"
        # Fingerprints chosen so alphabetical order is the reverse of execution order.
        for fingerprint in ("zzz", "mmm", "aaa"):
            append_run(history_dir, make_run("2026-09-18T17:30:23Z", fingerprint))
        history = load_history(history_dir)
        assert [e.config_fingerprint for e in history.entries] == ["zzz", "mmm", "aaa"]

    def test_load_sorts_by_started_at_first(self, tmp_path: Path):
        history_dir = tmp_path / "history"
        append_run(history_dir, make_run("2026-09-18T17:30:25Z", "later"))
        append_run(history_dir, make_run("2026-09-18T17:30:23Z", "earlier"))
        history = load_history(history_dir)
        assert [e.config_fingerprint for e in history.entries] == ["earlier", "later"]

    def test_invalid_files_are_skipped_and_reported(self, tmp_path: Path):
        history_dir = tmp_path / "history"
        append_run(history_dir, make_run("2026-09-18T17:30:23Z"))
        (history_dir / "broken.json").write_text("{not json", encoding="utf-8")
        (history_dir / "foreign.json").write_text('{"hello": "world"}', encoding="utf-8")
        history = load_history(history_dir)
        assert len(history) == 1
        assert len(history.skipped) == 2
        assert any("broken.json" in item for item in history.skipped)
        assert any("foreign.json" in item for item in history.skipped)

    def test_missing_directory_is_an_empty_history(self, tmp_path: Path):
        history = load_history(tmp_path / "nope")
        assert len(history) == 0 and history.skipped == []

    def test_limit_keeps_the_most_recent_runs(self, tmp_path: Path):
        history_dir = tmp_path / "history"
        for second in (23, 24, 25, 26):
            append_run(history_dir, make_run(f"2026-09-18T17:30:{second}Z", f"cfg{second}"))
        history = load_history(history_dir, limit=2)
        assert [e.config_fingerprint for e in history.entries] == ["cfg25", "cfg26"]


class TestMergeCurrent:
    def test_a_results_file_already_in_history_is_not_duplicated(self, tmp_path: Path):
        run = make_run("2026-09-18T17:30:23Z")
        append_run(tmp_path, run)
        history = load_history(tmp_path)
        merge_current(history, dict(run), tmp_path / "results.json")
        assert len(history) == 1

    def test_a_new_results_file_is_added_in_order(self, tmp_path: Path):
        append_run(tmp_path, make_run("2026-09-18T17:30:23Z", "old"))
        history = load_history(tmp_path)
        merge_current(history, make_run("2026-09-18T17:31:00Z", "new"), tmp_path / "results.json")
        assert [e.config_fingerprint for e in history.entries] == ["old", "new"]

    def test_invalid_current_is_ignored(self):
        history = History()
        merge_current(history, {"nothing": True})
        merge_current(history, None)
        assert len(history) == 0
