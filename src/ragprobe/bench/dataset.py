"""Load, validate and summarise a Bench catalogue (a JSONL file).

The catalogue is one JSON object per line - diff-friendly, streamable, and the
same format detectors and the runner read. These helpers keep it honest: every
row validates, ids are unique, splits are disjoint, and a licence is always
present.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List

from ragprobe.bench.schema import BenchItem, BenchError, validate


def save_jsonl(items: Iterable[BenchItem], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_jsonl(path: Path) -> List[BenchItem]:
    path = Path(path)
    if not path.is_file():
        raise BenchError(f"bench catalogue not found: {path}")
    items: List[BenchItem] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(BenchItem.from_dict(json.loads(line)))
        except (ValueError, TypeError) as exc:
            raise BenchError(f"{path}: bad JSON on line {n}: {exc}") from exc
    return items


def validate_all(items: List[BenchItem]) -> None:
    """Validate every row and the dataset-level invariants."""
    if not items:
        raise BenchError("empty catalogue")
    seen = set()
    for item in items:
        validate(item)
        if item.id in seen:
            raise BenchError(f"duplicate id {item.id!r}")
        seen.add(item.id)


def stats(items: List[BenchItem]) -> Dict[str, object]:
    """Counts by the dimensions a datasheet and a reviewer care about."""
    def dist(key) -> Dict[str, int]:
        return dict(sorted(Counter(key(i) for i in items).items()))

    attacks = [i for i in items if i.kind == "attack"]
    probes = [i for i in items if i.kind == "probe"]
    return {
        "total": len(items),
        "attacks": len(attacks),
        "probes": len(probes),
        "by_kind": dist(lambda i: i.kind),
        "by_owasp": dist(lambda i: i.owasp),
        "by_technique": dist(lambda i: i.technique),
        "by_language": dist(lambda i: i.language),
        "by_source": dist(lambda i: i.source),
        "by_licence": dist(lambda i: i.licence),
        "by_split": dist(lambda i: i.split),
        "probe_positives": sum(1 for i in probes if i.label == 1),
    }
