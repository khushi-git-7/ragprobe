"""Run history: an append-only directory of timestamped results files.

A single ``results.json`` answers "how did the last run go?". A directory of them
answers the questions a QA engineer actually asks over a project's life: is the
pass rate drifting, which cases flip between runs, and did the prompt change last
Tuesday move anything. ``ragprobe run`` appends every run here; ``ragprobe
dashboard`` reads the directory back and renders the trend view.

Files are named ``run-<sequence>-<UTC timestamp>-<config fingerprint>.json`` so
that a plain directory listing is already a chronological log that shows when the
configuration changed. The sequence number is what keeps two runs in the same
second in the order they happened; ``started_at`` only has second resolution and
a fast suite can finish several runs inside one. A history store that loses or
reorders runs is worse than none.

Loading is tolerant: an unreadable or foreign JSON file is reported and skipped,
because one corrupt artifact must not take the whole dashboard down.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

DEFAULT_HISTORY_DIR = "reports/history"

_FILENAME_RE = re.compile(r"^run-(\d+)-(\d{8}T\d{6}Z)-([0-9a-zA-Z]+)\.json$")


@dataclass
class HistoryEntry:
    """One stored run: where it came from, and the parsed results document."""

    path: Path
    run: Dict[str, Any]

    @property
    def started_at(self) -> str:
        return str(self.run.get("started_at") or "")

    @property
    def config_fingerprint(self) -> str:
        return str(self.run.get("config_fingerprint") or "")


@dataclass
class History:
    """The usable runs in a history directory, oldest first, plus what was skipped."""

    entries: List[HistoryEntry] = field(default_factory=list)
    #: Files that were present but could not be used, with the reason.
    skipped: List[str] = field(default_factory=list)

    @property
    def runs(self) -> List[Dict[str, Any]]:
        return [entry.run for entry in self.entries]

    def __len__(self) -> int:
        return len(self.entries)


def _timestamp_token(started_at: Optional[str]) -> str:
    """``2026-09-18T17:30:23Z`` -> ``20260918T173023Z``; anything else -> ``unknown``."""
    if not started_at:
        return "unknown"
    token = re.sub(r"[^0-9TZ]", "", str(started_at))
    return token if re.fullmatch(r"\d{8}T\d{6}Z", token) else "unknown"


def history_filename(run: Mapping[str, Any], sequence: int) -> str:
    """``run-0007-20260918T173023Z-7501f486bed1.json`` for sequence 7.

    The fingerprint is reduced to ``[0-9A-Za-z]`` so the name is valid on every
    filesystem and matches ``_FILENAME_RE`` when read back.
    """
    fingerprint = re.sub(r"[^0-9a-zA-Z]", "", str(run.get("config_fingerprint") or "")) or "nofingerprint"
    return f"run-{sequence:04d}-{_timestamp_token(run.get('started_at'))}-{fingerprint}.json"


def _sequence_of(path: Path) -> Optional[int]:
    match = _FILENAME_RE.match(path.name)
    return int(match.group(1)) if match else None


def next_sequence(history_dir: Path) -> int:
    """One more than the highest sequence number already in the directory."""
    highest = 0
    if history_dir.is_dir():
        for path in history_dir.glob("run-*.json"):
            seq = _sequence_of(path)
            if seq is not None and seq > highest:
                highest = seq
    return highest + 1


def is_valid_run(run: Any) -> bool:
    """The minimum shape the dashboard needs: a summary and a list of cases."""
    return (
        isinstance(run, dict)
        and isinstance(run.get("summary"), dict)
        and isinstance(run.get("cases"), list)
    )


def append_run(history_dir: Path, run: Mapping[str, Any]) -> Path:
    """Write ``run`` into ``history_dir`` under a unique, chronological filename."""
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    sequence = next_sequence(history_dir)
    candidate = history_dir / history_filename(run, sequence)
    while candidate.exists():  # cannot happen unless the directory is being raced
        sequence += 1
        candidate = history_dir / history_filename(run, sequence)
    candidate.write_text(
        json.dumps(run, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return candidate


def _find_duplicate(history: History, candidate: HistoryEntry) -> Optional[HistoryEntry]:
    """The already-loaded entry whose document equals ``candidate``'s, if any.

    Two distinct runs can share a timestamp and a config fingerprint (a fast suite
    run twice in one second), so only a document that is equal in full counts.
    """
    for entry in history.entries:
        if (
            entry.started_at == candidate.started_at
            and entry.config_fingerprint == candidate.config_fingerprint
            and entry.run == candidate.run
        ):
            return entry
    return None


def _sort_key(entry: HistoryEntry) -> tuple:
    """Chronological: by ``started_at``, then by sequence number within a second.

    A file without a sequence number (a merged ``results.json``) sorts after the
    sequenced runs from the same second.
    """
    seq = _sequence_of(entry.path)
    return (entry.started_at, seq if seq is not None else 10**9, entry.path.name)


def load_history(history_dir: Path, limit: Optional[int] = None) -> History:
    """Read every results file in ``history_dir``, oldest first.

    ``limit`` keeps only the most recent N runs. Files that are not valid results
    documents are listed in ``History.skipped`` instead of raising, and so is a
    file whose document is identical to one already loaded (a copied
    ``results.json``): the same run twice would draw a flat step on every trend
    line and count as an extra run in every insight.
    """
    history_dir = Path(history_dir)
    history = History()
    if not history_dir.is_dir():
        return history

    # Sequenced files first, so a duplicate is reported against the file whose
    # name carries the sequence number, and that one is the copy that is kept.
    paths = sorted(history_dir.glob("*.json"), key=lambda p: (_sequence_of(p) is None, p.name))
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            history.skipped.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        if not is_valid_run(payload):
            history.skipped.append(f"{path.name}: not a RAGProbe results document")
            continue
        entry = HistoryEntry(path=path, run=payload)
        duplicate_of = _find_duplicate(history, entry)
        if duplicate_of is not None:
            history.skipped.append(f"{path.name}: identical to {duplicate_of.path.name}")
            continue
        history.entries.append(entry)

    history.entries.sort(key=_sort_key)
    if limit is not None and limit > 0:
        history.entries = history.entries[-limit:]
    return history


def merge_current(history: History, current: Optional[Mapping[str, Any]], path: Optional[Path] = None) -> History:
    """Add a standalone results file to the history unless it is already there.

    Identity is (started_at, config_fingerprint): the same run written to both
    ``results.json`` and the history directory must not appear twice on a trend
    line, or every "current" run would look like a duplicate flat step.
    """
    if not current or not is_valid_run(current):
        return history
    key = (str(current.get("started_at") or ""), str(current.get("config_fingerprint") or ""))
    for entry in history.entries:
        if (entry.started_at, entry.config_fingerprint) == key:
            return history
    history.entries.append(HistoryEntry(path=Path(path) if path else Path("results.json"), run=dict(current)))
    history.entries.sort(key=_sort_key)
    return history
