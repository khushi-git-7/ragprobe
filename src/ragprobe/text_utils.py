"""Shared, dependency-free text utilities.

Kept in one place so the embedder, the grounding checker and the stub provider all
tokenize identically. Two components that disagree about what a "word" is will
disagree about every score they produce.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Sequence, Set, Tuple

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")

#: Small, explicit stopword list. Deliberately short: aggressive stopword removal
#: throws away words like "not" and "no" that flip the meaning of a claim, which
#: would make the grounding checker score a negation as faithful to its opposite.
STOPWORDS: Set[str] = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "for",
    "from", "has", "have", "had", "in", "into", "is", "it", "its", "of", "on",
    "or", "that", "the", "their", "there", "these", "this", "those", "to",
    "was", "were", "will", "with", "which", "while",
}


def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT_RE.sub(" ", text.lower())
    return _WS_RE.sub(" ", text).strip()


def tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric tokens. Decimal numbers such as ``99.9`` stay intact."""
    return _TOKEN_RE.findall(text.lower())


def content_tokens(text: str) -> List[str]:
    """Tokens with stopwords removed, used for overlap scoring."""
    return [token for token in tokenize(text) if token not in STOPWORDS]


def bigrams(tokens: Sequence[str]) -> List[Tuple[str, str]]:
    return [(tokens[i], tokens[i + 1]) for i in range(len(tokens) - 1)]


def split_sentences(text: str) -> List[str]:
    """Split prose into sentences.

    A regex splitter, not a parser: it is good enough to turn an answer into
    claim-sized units and it has no dependencies. Known limitation, documented in
    the README: abbreviations such as "e.g." can cause an over-split, which makes
    the grounding score slightly conservative rather than optimistic. Erring
    towards flagging is the right failure direction for a hallucination check.
    """
    text = text.strip()
    if not text:
        return []
    parts = [part.strip() for part in _SENTENCE_RE.split(text)]
    return [part for part in parts if part]


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)
