"""Deterministic answer-quality evaluators.

These are the checks that need no model: exact and fuzzy match, required-keyword
presence, forbidden-keyword absence, refusal behaviour, and citation validity.

They are the backbone of the suite. Deterministic checks are the ones you can gate
a build on, because they answer yes/no the same way every time. The model-based
checks layered on top (grounding, LLM judge) are more insightful and less reliable,
so they are reported alongside rather than instead.

Each check returns a ``CheckResult`` carrying both a boolean and a continuous score.
The boolean drives pass/fail; the score drives the regression diff, which can then
see a case degrade from 0.9 to 0.6 *before* it crosses the threshold and starts
failing. Catching a slide before it becomes a break is most of the value.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from ragprobe.text_utils import normalize

#: Phrases that indicate the system declined to answer. Matched against the
#: normalised answer, so punctuation and casing do not matter.
REFUSAL_PATTERNS: Sequence[str] = (
    "do not have enough information",
    "dont have enough information",
    "not have enough information",
    "cannot answer",
    "can not answer",
    "cant answer",
    "unable to answer",
    "no information in the provided",
    "not covered by the provided",
    "is not mentioned in the provided",
)

# A citation is a bracketed chunk id: ``[doc#anchor]``, optionally with the ``~2``
# split suffix or a ``-2`` duplicate-heading suffix. It must not be followed by
# ``(``, which would make it a markdown link. Anything looser turns every markdown
# link and every ``[Note]`` in a real corpus into a "fabricated citation".
_CHUNK_ID = r"[A-Za-z0-9_.\-]+#[A-Za-z0-9_\-~.]+"
# One bracket may carry several ids - ``[doc#a, doc#b]`` is how models cite when two
# sources support one sentence - so the group captures the whole list.
_CITATION_RE = re.compile(r"\[(" + _CHUNK_ID + r"(?:\s*[,;]\s*" + _CHUNK_ID + r")*)\](?!\()")
_CITATION_SPLIT_RE = re.compile(r"\s*[,;]\s*")


@dataclass
class CheckResult:
    """Outcome of one evaluator."""

    name: str
    passed: bool
    score: float
    detail: str = ""
    #: False when the check did not apply to this case (e.g. no expected answer was
    #: supplied). Skipped checks never fail a case and are excluded from scoring.
    applicable: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["score"] = round(self.score, 4)
        return data


def _skipped(name: str, reason: str) -> CheckResult:
    return CheckResult(name=name, passed=True, score=0.0, detail=reason, applicable=False)


# --------------------------------------------------------------------- matching


def exact_match(answer: str, expected: Optional[str]) -> CheckResult:
    """Normalised string equality.

    Normalisation (casefold, strip punctuation, collapse whitespace) is applied
    because raw equality on generated text fails on a trailing full stop, which is
    noise rather than a defect.
    """
    if expected is None:
        return _skipped("exact_match", "no expected_answer in dataset")
    match = normalize(answer) == normalize(expected)
    return CheckResult(
        name="exact_match",
        passed=match,
        score=1.0 if match else 0.0,
        detail="exact match" if match else "answer differs from expected_answer",
    )


def fuzzy_match(answer: str, expected: Optional[str], threshold: float = 0.60) -> CheckResult:
    """Character-level similarity ratio against the expected answer.

    ``difflib.SequenceMatcher`` on normalised text. This is a *similarity* check,
    not a correctness check - an answer can be 0.9 similar to the expected one and
    still say the opposite, if the differing 10% is the word "not". It is reported
    as advisory for exactly that reason; keyword and grounding checks carry the
    semantic weight.
    """
    if expected is None:
        return _skipped("fuzzy_match", "no expected_answer in dataset")
    ratio = SequenceMatcher(None, normalize(answer), normalize(expected)).ratio()
    return CheckResult(
        name="fuzzy_match",
        passed=ratio >= threshold,
        score=ratio,
        detail=f"similarity {ratio:.2f} vs threshold {threshold:.2f}",
    )


# --------------------------------------------------------------------- keywords


def _contains_keyword(haystack_normalized: str, keyword: str) -> bool:
    """Whole-token containment on normalised text.

    Substring matching would let "30" match inside "300" and report a keyword hit
    for a wrong number, which is precisely the failure mode these checks exist to
    catch.
    """
    needle = normalize(keyword)
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack_normalized) is not None


def keyword_presence(answer: str, required: Optional[Iterable[str]]) -> CheckResult:
    """Every required keyword must appear in the answer."""
    required = [keyword for keyword in (required or []) if str(keyword).strip()]
    if not required:
        return _skipped("keyword_presence", "no required_keywords in dataset")
    normalized_answer = normalize(answer)
    missing = [kw for kw in required if not _contains_keyword(normalized_answer, str(kw))]
    found = len(required) - len(missing)
    return CheckResult(
        name="keyword_presence",
        passed=not missing,
        score=found / len(required),
        detail=(
            f"all {len(required)} required keyword(s) present"
            if not missing
            else f"missing: {', '.join(missing)}"
        ),
        metadata={"missing": missing, "required": [str(k) for k in required]},
    )


def forbidden_absent(answer: str, forbidden: Optional[Iterable[str]]) -> CheckResult:
    """No forbidden keyword may appear.

    Used for near-miss distractors: the golden set can assert that a question about
    the Growth tier price does not come back with the Starter tier price.
    """
    forbidden = [keyword for keyword in (forbidden or []) if str(keyword).strip()]
    if not forbidden:
        return _skipped("forbidden_absent", "no forbidden_keywords in dataset")
    normalized_answer = normalize(answer)
    present = [kw for kw in forbidden if _contains_keyword(normalized_answer, str(kw))]
    return CheckResult(
        name="forbidden_absent",
        passed=not present,
        score=1.0 - (len(present) / len(forbidden)),
        detail=(
            "no forbidden keywords present"
            if not present
            else f"forbidden keyword(s) present: {', '.join(present)}"
        ),
        metadata={"present": present},
    )


# --------------------------------------------------------------------- refusal


def detect_refusal(answer: str) -> bool:
    """True when the answer reads as a refusal to answer."""
    normalized_answer = normalize(answer)
    return any(normalize(pattern) in normalized_answer for pattern in REFUSAL_PATTERNS)


def refusal_behaviour(answer: str, should_refuse: bool) -> CheckResult:
    """Assert the system refuses when it should, and does not when it should not.

    Both directions matter. Over-refusal is the failure mode that a
    "did it hallucinate?" metric will never catch, and it is what a badly tuned
    similarity threshold produces: a system that is perfectly faithful and
    completely useless.
    """
    refused = detect_refusal(answer)
    passed = refused == should_refuse
    if should_refuse:
        detail = "correctly refused" if passed else "should have refused but answered"
    else:
        detail = "correctly answered" if passed else "refused a question it should have answered"
    return CheckResult(
        name="refusal_behaviour",
        passed=passed,
        score=1.0 if passed else 0.0,
        detail=detail,
        metadata={"refused": refused, "should_refuse": should_refuse},
    )


# -------------------------------------------------------------------- citations


def extract_citations(answer: str) -> List[str]:
    """Pull ``[chunk#anchor]`` markers out of an answer, in order, deduplicated.

    Markdown links (``[text](url)``) and prose in brackets are not citations.
    """
    seen: Set[str] = set()
    result: List[str] = []
    for match in _CITATION_RE.findall(answer or ""):
        for candidate in _CITATION_SPLIT_RE.split(match.strip()):
            if candidate and candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
    return result


def citation_present(
    answer: str,
    retrieved_ids: Sequence[str],
    required: bool = True,
    is_refusal: bool = False,
) -> CheckResult:
    """Check the answer cites its sources, and that the citations are real.

    Two distinct failures are covered. The obvious one is *no citation at all*. The
    subtler and more dangerous one is a **fabricated citation** - a chunk ID that
    was never retrieved. A fabricated citation is worse than none: it looks like
    evidence, so a human spot-checking the output trusts it and stops reading.
    """
    if is_refusal:
        return _skipped("citation_present", "refusals are not expected to cite sources")
    if not required:
        return _skipped("citation_present", "citations not required by config")

    citations = extract_citations(answer)
    retrieved = set(retrieved_ids)
    fabricated = [citation for citation in citations if citation not in retrieved]

    if not citations:
        return CheckResult(
            name="citation_present",
            passed=False,
            score=0.0,
            detail="answer contains no citation",
            metadata={"citations": [], "fabricated": []},
        )
    if fabricated:
        return CheckResult(
            name="citation_present",
            passed=False,
            score=max(0.0, 1.0 - len(fabricated) / len(citations)),
            detail=f"cites chunk(s) that were never retrieved: {', '.join(fabricated)}",
            metadata={"citations": citations, "fabricated": fabricated},
        )
    return CheckResult(
        name="citation_present",
        passed=True,
        score=1.0,
        detail=f"cites {len(citations)} retrieved chunk(s)",
        metadata={"citations": citations, "fabricated": []},
    )


def expected_citation_overlap(
    answer: str, expected_chunks: Sequence[str]
) -> CheckResult:
    """Did the answer cite the chunks the dataset says hold the answer?

    Distinct from retrieval recall: retrieval can surface the right chunk while the
    generator cites a different one. Advisory rather than gating, because citing a
    different chunk that happens to contain the same fact is not strictly wrong.
    """
    expected = [chunk for chunk in expected_chunks if chunk]
    if not expected:
        return _skipped("expected_citation_overlap", "no expected_chunks in dataset")
    citations = set(extract_citations(answer))
    # Compare on the anchor so a split section (``doc#a~2``) still matches ``doc#a``.
    anchors = {citation.split("~", 1)[0] for citation in citations}
    hits = [chunk for chunk in expected if chunk.split("~", 1)[0] in anchors]
    score = len(hits) / len(expected)
    return CheckResult(
        name="expected_citation_overlap",
        passed=bool(hits),
        score=score,
        detail=f"cited {len(hits)}/{len(expected)} expected chunk(s)",
        metadata={"expected": list(expected), "cited": sorted(citations)},
    )
