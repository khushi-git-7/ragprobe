"""Offline faithfulness / hallucination heuristic.

This is the non-LLM half of the faithfulness check. It splits the answer into
claims (sentences) and asks, for each, how much of it can be found in the retrieved
context. It runs in microseconds, needs no key, and is fully deterministic - so it
can gate CI, which an LLM judge cannot.

**Scoring.** Each claim gets

    claim_score = 0.65 * bigram_coverage + 0.35 * unigram_coverage

where coverage is over *content tokens* (stopwords removed). Bigrams are weighted
higher because unigram overlap alone is easy to fake: an answer that reuses the
vocabulary of the context while scrambling its meaning ("PTO is capped at 30 days"
against a context saying "20 days" and "30 days of notice") scores well on unigrams
and badly on bigrams. Bigrams capture a little word order, which is a cheap proxy
for a little meaning.

**What it cannot do, stated plainly.** This is a lexical overlap measure, not an
entailment model. It will:

* *miss* a hallucination that is phrased in the context's own words - most
  importantly a swapped number or a flipped negation, if the surrounding phrasing
  is copied. This is the most dangerous class of RAG error and the heuristic is
  weakest exactly there. The numeric-consistency check below is a partial mitigation.
* *false-positive* on a correct answer that paraphrases heavily, which an extractive
  system will not do but a real LLM will.

It is therefore a **screen, not a verdict**: cheap, deterministic, catches the
obvious cases, and is deliberately paired with an LLM judge rather than trusted
alone. The README section "Known weaknesses" covers the trade-off in full.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set, Tuple

from ragprobe.text_utils import bigrams, content_tokens, split_sentences

#: Numbers (including decimals and percentages) pulled out for the consistency check.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

DEFAULT_CLAIM_THRESHOLD = 0.50
DEFAULT_GROUNDING_THRESHOLD = 0.55


@dataclass
class ClaimGrounding:
    """Grounding detail for one claim (sentence) of the answer."""

    text: str
    score: float
    supported: bool
    unigram_coverage: float
    bigram_coverage: float
    #: Numbers present in the claim but absent from the context - a strong
    #: hallucination signal, since RAG answers rarely need to invent a figure.
    unsupported_numbers: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "score": round(self.score, 4),
            "supported": self.supported,
            "unigram_coverage": round(self.unigram_coverage, 4),
            "bigram_coverage": round(self.bigram_coverage, 4),
            "unsupported_numbers": self.unsupported_numbers,
        }


@dataclass
class GroundingResult:
    score: float
    grounded: bool
    claims: List[ClaimGrounding]

    @property
    def unsupported_claims(self) -> List[ClaimGrounding]:
        return [claim for claim in self.claims if not claim.supported]

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "grounded": self.grounded,
            "claims": [claim.to_dict() for claim in self.claims],
            "unsupported_claims": [claim.text for claim in self.unsupported_claims],
        }


def _coverage(items: Sequence, reference: Set) -> float:
    """Fraction of ``items`` present in ``reference``. Empty input scores 1.0."""
    if not items:
        return 1.0
    return sum(1 for item in items if item in reference) / len(items)


def _strip_citations(text: str) -> str:
    """Remove ``[chunk#anchor]`` citation markers before grounding.

    Citations are metadata, not claims. Leaving them in drags the score down because
    the chunk ID never appears verbatim in the prose of the context.
    """
    return re.sub(r"\[[^\]\s]+\]", " ", text)


def score_claim(claim: str, context_tokens: Set[str], context_bigrams: Set[Tuple[str, str]],
                context_numbers: Set[str], claim_threshold: float) -> ClaimGrounding:
    tokens = content_tokens(_strip_citations(claim))
    claim_bigrams = bigrams(tokens)

    unigram_coverage = _coverage(tokens, context_tokens)
    # A one-content-word claim has no bigrams; fall back to unigram coverage rather
    # than awarding a free 1.0 from the empty-input rule.
    bigram_coverage = _coverage(claim_bigrams, context_bigrams) if claim_bigrams else unigram_coverage

    score = 0.65 * bigram_coverage + 0.35 * unigram_coverage

    numbers = _NUMBER_RE.findall(_strip_citations(claim))
    unsupported_numbers = [number for number in numbers if number not in context_numbers]
    # An invented figure is treated as disqualifying regardless of lexical overlap.
    # This is the one place the heuristic is deliberately harsh: in a grounded QA
    # system, a number that appears nowhere in the sources is almost always wrong.
    if unsupported_numbers:
        score = min(score, 0.4)

    return ClaimGrounding(
        text=claim.strip(),
        score=score,
        supported=score >= claim_threshold and not unsupported_numbers,
        unigram_coverage=unigram_coverage,
        bigram_coverage=bigram_coverage,
        unsupported_numbers=unsupported_numbers,
    )


def score_grounding(
    answer: str,
    context: str,
    claim_threshold: float = DEFAULT_CLAIM_THRESHOLD,
    grounding_threshold: float = DEFAULT_GROUNDING_THRESHOLD,
) -> GroundingResult:
    """Score how well ``answer`` is grounded in ``context``.

    The overall score is the mean claim score. The mean, not the minimum: one weakly
    worded sentence in an otherwise solid answer should dent the score, not fail it
    outright. The per-claim detail is preserved so the report can show exactly which
    sentence is unsupported.
    """
    answer = (answer or "").strip()
    context = context or ""

    if not answer:
        return GroundingResult(score=0.0, grounded=False, claims=[])

    context_tokens = set(content_tokens(context))
    context_bigrams = set(bigrams(content_tokens(context)))
    context_numbers = set(_NUMBER_RE.findall(context))

    if not context_tokens:
        # An answer with no context at all is ungrounded by definition.
        claims = [
            ClaimGrounding(
                text=sentence,
                score=0.0,
                supported=False,
                unigram_coverage=0.0,
                bigram_coverage=0.0,
                unsupported_numbers=_NUMBER_RE.findall(sentence),
            )
            for sentence in split_sentences(answer)
        ]
        return GroundingResult(score=0.0, grounded=False, claims=claims)

    claims = [
        score_claim(sentence, context_tokens, context_bigrams, context_numbers, claim_threshold)
        for sentence in split_sentences(answer)
    ]
    if not claims:
        return GroundingResult(score=0.0, grounded=False, claims=[])

    score = sum(claim.score for claim in claims) / len(claims)
    return GroundingResult(
        score=score,
        grounded=score >= grounding_threshold and all(c.supported for c in claims),
        claims=claims,
    )
