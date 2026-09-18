"""Golden dataset loading and validation.

Supports YAML (``.yaml`` / ``.yml``) and JSON Lines (``.jsonl``). Both carry the same
schema; JSONL exists because it diffs and merges cleanly when several people add
cases at once.

Validation is strict and runs at load time. A golden set is test data, and test data
that silently accepts a typo'd field name is worse than no test data: the case looks
present in the report while asserting nothing. Every unknown key is an error.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

#: Every field a case may declare. Anything else is rejected.
CASE_FIELDS = {
    "id",
    "question",
    "category",
    "expected_answer",
    "expected_chunks",
    "required_keywords",
    "forbidden_keywords",
    "should_refuse",
    "notes",
}


class DatasetError(ValueError):
    """Raised when the golden dataset is malformed."""


@dataclass
class GoldenCase:
    """One question and everything the harness asserts about its answer."""

    id: str
    question: str
    category: str = "general"
    #: Free-text reference answer. Optional - many good cases assert on keywords and
    #: grounding rather than on an exact string, because pinning exact prose makes
    #: the suite brittle against harmless rewording.
    expected_answer: Optional[str] = None
    #: Chunk IDs that genuinely contain the answer. Drives all retrieval metrics.
    expected_chunks: List[str] = field(default_factory=list)
    required_keywords: List[str] = field(default_factory=list)
    forbidden_keywords: List[str] = field(default_factory=list)
    should_refuse: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _coerce_str_list(value: Any, case_id: str, field_name: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    raise DatasetError(f"case {case_id!r}: '{field_name}' must be a string or list of strings")


def _build_case(raw: Mapping[str, Any], index: int, source: str) -> GoldenCase:
    if not isinstance(raw, Mapping):
        raise DatasetError(f"{source}: entry {index} is not a mapping")

    unknown = set(raw) - CASE_FIELDS
    if unknown:
        raise DatasetError(
            f"{source}: entry {index} has unknown field(s): {', '.join(sorted(unknown))}. "
            f"Valid fields: {', '.join(sorted(CASE_FIELDS))}"
        )

    case_id = str(raw.get("id") or "").strip()
    if not case_id:
        raise DatasetError(f"{source}: entry {index} is missing a non-empty 'id'")
    question = str(raw.get("question") or "").strip()
    if not question:
        raise DatasetError(f"{source}: case {case_id!r} is missing a non-empty 'question'")

    should_refuse = raw.get("should_refuse", False)
    if not isinstance(should_refuse, bool):
        raise DatasetError(f"case {case_id!r}: 'should_refuse' must be true or false")

    expected_chunks = _coerce_str_list(raw.get("expected_chunks"), case_id, "expected_chunks")
    if should_refuse and expected_chunks:
        raise DatasetError(
            f"case {case_id!r}: a refusal case must not declare expected_chunks - "
            "there is by definition no chunk that answers it"
        )
    if not should_refuse and not expected_chunks:
        raise DatasetError(
            f"case {case_id!r}: non-refusal cases must declare at least one expected chunk, "
            "otherwise retrieval quality is not being asserted at all"
        )

    expected_answer = raw.get("expected_answer")
    return GoldenCase(
        id=case_id,
        question=question,
        category=str(raw.get("category") or "general"),
        expected_answer=str(expected_answer) if expected_answer is not None else None,
        expected_chunks=expected_chunks,
        required_keywords=_coerce_str_list(raw.get("required_keywords"), case_id, "required_keywords"),
        forbidden_keywords=_coerce_str_list(raw.get("forbidden_keywords"), case_id, "forbidden_keywords"),
        should_refuse=should_refuse,
        notes=str(raw.get("notes") or ""),
    )


def parse_cases(entries: Iterable[Mapping[str, Any]], source: str = "<memory>") -> List[GoldenCase]:
    """Validate raw mappings into ``GoldenCase`` objects."""
    cases: List[GoldenCase] = []
    seen: Dict[str, int] = {}
    for index, raw in enumerate(entries):
        case = _build_case(raw, index, source)
        if case.id in seen:
            raise DatasetError(
                f"{source}: duplicate case id {case.id!r} (entries {seen[case.id]} and {index}). "
                "Case ids are the join key for the regression diff and must be unique."
            )
        seen[case.id] = index
        cases.append(case)
    if not cases:
        raise DatasetError(f"{source}: dataset contains no cases")
    return cases


def load_dataset(path: Path) -> List[GoldenCase]:
    """Load a golden set from YAML or JSONL."""
    path = Path(path)
    if not path.exists():
        raise DatasetError(f"dataset file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        entries: List[Mapping[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise DatasetError(f"{path}:{line_number}: invalid JSON - {exc}") from exc
    elif suffix in {".yaml", ".yml"}:
        import yaml

        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if isinstance(raw, Mapping):
            raw = raw.get("cases", [])
        if not isinstance(raw, list):
            raise DatasetError(
                f"{path}: expected a list of cases, or a mapping with a 'cases' key"
            )
        entries = raw
    else:
        raise DatasetError(f"unsupported dataset format {path.suffix!r}; use .yaml or .jsonl")

    return parse_cases(entries, source=str(path))


def dataset_fingerprint(cases: Sequence[GoldenCase]) -> str:
    """Stable hash of the dataset contents.

    Written into results files so the diff can warn when a baseline was produced
    against a different set of questions - in which case the comparison is not
    apples to apples and any "regression" it reports is meaningless.
    """
    payload = json.dumps(
        [case.to_dict() for case in cases], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
