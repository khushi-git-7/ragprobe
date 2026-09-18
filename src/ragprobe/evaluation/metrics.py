"""Retrieval metrics.

Every function here is a pure function of (ranked retrieved IDs, relevant ID set, k),
which is what makes them testable against hand-computed values. The test suite pins
each one to numbers worked out by hand - including the awkward edge cases - because
a metrics module that is itself untested is a confident-looking source of wrong
numbers, and wrong numbers are worse than no numbers.

Two conventions are worth stating explicitly, since implementations differ:

* **precision@k divides by k**, not by the number of documents actually returned.
  If you ask for 5 and the system returns 2, both relevant, this reports 0.4 rather
  than 1.0. Dividing by the returned count would let a system game precision by
  returning fewer results.
* **Undefined is ``None``, not 0.0.** When a case has no relevant chunks at all - a
  refusal case, where the correct behaviour is to retrieve nothing useful - recall
  and precision are not "zero", they are meaningless. Returning 0.0 would silently
  drag down the corpus-level average and make a correctly-refusing system look
  broken. ``None`` is skipped by the aggregator. JSON-safe as ``null``.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Set


def _dedupe(items: Sequence[str]) -> List[str]:
    """Drop duplicate IDs, preserving rank order.

    A retriever that returns the same chunk twice would otherwise be able to score
    2/2 precision on a single relevant chunk. Seen in the wild after a bad
    de-duplication change; cheap to defend against.
    """
    seen: Set[str] = set()
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _prepare(retrieved: Sequence[str], relevant: Iterable[str], k: int):
    if k <= 0:
        raise ValueError("k must be a positive integer")
    relevant_set = set(relevant)
    top_k = _dedupe(retrieved)[:k]
    return top_k, relevant_set


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> Optional[float]:
    """Fraction of the top-k slots filled by a relevant chunk.

    ``P@k = |top_k ∩ relevant| / k``
    """
    top_k, relevant_set = _prepare(retrieved, relevant, k)
    if not relevant_set:
        return None
    hits = sum(1 for chunk_id in top_k if chunk_id in relevant_set)
    return hits / k


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> Optional[float]:
    """Fraction of all relevant chunks that appear in the top k.

    ``R@k = |top_k ∩ relevant| / |relevant|``
    """
    top_k, relevant_set = _prepare(retrieved, relevant, k)
    if not relevant_set:
        return None
    hits = sum(1 for chunk_id in top_k if chunk_id in relevant_set)
    return hits / len(relevant_set)


def hit_rate_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> Optional[float]:
    """1.0 if at least one relevant chunk is in the top k, else 0.0.

    The most forgiving retrieval metric, and the one that best predicts whether the
    generator *can* answer at all: one good chunk is often enough.
    """
    top_k, relevant_set = _prepare(retrieved, relevant, k)
    if not relevant_set:
        return None
    return 1.0 if any(chunk_id in relevant_set for chunk_id in top_k) else 0.0


def reciprocal_rank(
    retrieved: Sequence[str], relevant: Iterable[str], k: Optional[int] = None
) -> Optional[float]:
    """``1 / rank`` of the first relevant chunk (rank is 1-based); 0.0 if none.

    Pass ``k`` to only consider the top k. MRR is the mean of this across cases.
    """
    relevant_set = set(relevant)
    if not relevant_set:
        return None
    ranked = _dedupe(retrieved)
    if k is not None:
        if k <= 0:
            raise ValueError("k must be a positive integer")
        ranked = ranked[:k]
    for index, chunk_id in enumerate(ranked, start=1):
        if chunk_id in relevant_set:
            return 1.0 / index
    return 0.0


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    """Mean of the defined values. ``None`` entries are skipped.

    Returns ``None`` when nothing is defined, so an all-refusal suite reports
    "no retrieval metrics" rather than a misleading 0.0.
    """
    defined = [value for value in values if value is not None]
    if not defined:
        return None
    return sum(defined) / len(defined)


def mean_reciprocal_rank(
    per_case_retrieved: Sequence[Sequence[str]],
    per_case_relevant: Sequence[Iterable[str]],
    k: Optional[int] = None,
) -> Optional[float]:
    """MRR across a set of cases."""
    if len(per_case_retrieved) != len(per_case_relevant):
        raise ValueError("retrieved and relevant must have the same number of cases")
    return mean(
        reciprocal_rank(retrieved, relevant, k)
        for retrieved, relevant in zip(per_case_retrieved, per_case_relevant)
    )


def retrieval_metrics(
    retrieved: Sequence[str], relevant: Iterable[str], k: int
) -> Dict[str, Optional[float]]:
    """All per-case retrieval metrics in one dict."""
    relevant = list(relevant)
    return {
        f"precision@{k}": precision_at_k(retrieved, relevant, k),
        f"recall@{k}": recall_at_k(retrieved, relevant, k),
        f"hit_rate@{k}": hit_rate_at_k(retrieved, relevant, k),
        "reciprocal_rank": reciprocal_rank(retrieved, relevant, k),
    }


def aggregate_metrics(
    per_case: Sequence[Dict[str, Optional[float]]]
) -> Dict[str, Optional[float]]:
    """Average each metric across cases, skipping undefined values.

    ``reciprocal_rank`` is renamed to ``mrr`` on aggregation, because the mean of
    per-case reciprocal ranks is exactly what MRR means.
    """
    keys: List[str] = []
    for case in per_case:
        for key in case:
            if key not in keys:
                keys.append(key)
    result: Dict[str, Optional[float]] = {}
    for key in keys:
        name = "mrr" if key == "reciprocal_rank" else key
        result[name] = mean(case.get(key) for case in per_case)
    return result
