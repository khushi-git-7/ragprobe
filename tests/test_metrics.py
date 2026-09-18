"""Unit tests for the retrieval metrics.

These are tests *of the test tooling*, and they matter more than they look like they
should. Every number RAGProbe reports flows through this module. If ``recall_at_k``
is quietly wrong, the harness does not fail - it reports confident, precise, wrong
numbers, and people make decisions on them. That failure mode is strictly worse than
a crash.

So every expected value below is computed by hand and written out in the docstring
or a comment, rather than derived from the implementation.
"""

from __future__ import annotations

import pytest

from ragprobe.evaluation.metrics import (
    aggregate_metrics,
    hit_rate_at_k,
    mean,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    retrieval_metrics,
)

# A fixed ranked result list used across several tests.
#   rank 1: a  (relevant)
#   rank 2: b  (not relevant)
#   rank 3: c  (relevant)
#   rank 4: d  (not relevant)
RANKED = ["a", "b", "c", "d"]
RELEVANT = {"a", "c", "e"}  # note: "e" is relevant but never retrieved


class TestPrecisionAtK:
    def test_k1_hand_computed(self):
        # top-1 is ["a"]; 1 of 1 slots relevant -> 1/1 = 1.0
        assert precision_at_k(RANKED, RELEVANT, 1) == pytest.approx(1.0)

    def test_k2_hand_computed(self):
        # top-2 is ["a", "b"]; 1 relevant of 2 slots -> 1/2 = 0.5
        assert precision_at_k(RANKED, RELEVANT, 2) == pytest.approx(0.5)

    def test_k3_hand_computed(self):
        # top-3 is ["a", "b", "c"]; 2 relevant of 3 slots -> 2/3
        assert precision_at_k(RANKED, RELEVANT, 3) == pytest.approx(2.0 / 3.0)

    def test_k4_hand_computed(self):
        # top-4 is ["a", "b", "c", "d"]; 2 relevant of 4 slots -> 0.5
        assert precision_at_k(RANKED, RELEVANT, 4) == pytest.approx(0.5)

    def test_divides_by_k_not_by_result_count(self):
        """Returning fewer than k results must not inflate precision.

        Two results, both relevant, but k=5: 2/5 = 0.4, NOT 2/2 = 1.0.
        Dividing by the returned count would let a retriever score a perfect
        precision by returning a single lucky document.
        """
        assert precision_at_k(["a", "c"], RELEVANT, 5) == pytest.approx(0.4)

    def test_no_hits_is_zero(self):
        assert precision_at_k(["x", "y"], RELEVANT, 2) == pytest.approx(0.0)

    def test_empty_retrieved_is_zero(self):
        assert precision_at_k([], RELEVANT, 3) == pytest.approx(0.0)


class TestRecallAtK:
    def test_k1_hand_computed(self):
        # top-1 finds {"a"} of 3 relevant -> 1/3
        assert recall_at_k(RANKED, RELEVANT, 1) == pytest.approx(1.0 / 3.0)

    def test_k3_hand_computed(self):
        # top-3 finds {"a", "c"} of 3 relevant -> 2/3
        assert recall_at_k(RANKED, RELEVANT, 3) == pytest.approx(2.0 / 3.0)

    def test_unreachable_relevant_caps_recall(self):
        """"e" is never retrieved at any k, so recall can never reach 1.0."""
        assert recall_at_k(RANKED, RELEVANT, 99) == pytest.approx(2.0 / 3.0)

    def test_full_recall(self):
        assert recall_at_k(["a", "c", "e"], RELEVANT, 3) == pytest.approx(1.0)


class TestHitRate:
    def test_hit_at_rank_1(self):
        assert hit_rate_at_k(RANKED, RELEVANT, 1) == pytest.approx(1.0)

    def test_miss_when_relevant_below_k(self):
        # top-1 of ["b", "a"] is ["b"], which is not relevant -> 0.0
        assert hit_rate_at_k(["b", "a"], RELEVANT, 1) == pytest.approx(0.0)

    def test_hit_when_k_widens(self):
        assert hit_rate_at_k(["b", "a"], RELEVANT, 2) == pytest.approx(1.0)

    def test_is_binary_not_proportional(self):
        """Two relevant hits score the same as one - that is the definition."""
        assert hit_rate_at_k(["a", "c"], RELEVANT, 2) == hit_rate_at_k(["a", "x"], RELEVANT, 2)


class TestReciprocalRank:
    def test_first_position(self):
        assert reciprocal_rank(["a", "b"], RELEVANT) == pytest.approx(1.0)

    def test_second_position(self):
        assert reciprocal_rank(["b", "a"], RELEVANT) == pytest.approx(0.5)

    def test_third_position(self):
        assert reciprocal_rank(["x", "y", "a"], RELEVANT) == pytest.approx(1.0 / 3.0)

    def test_no_relevant_retrieved(self):
        assert reciprocal_rank(["x", "y"], RELEVANT) == pytest.approx(0.0)

    def test_only_first_hit_counts(self):
        """Ranks 1 and 3 both relevant -> still 1/1, not 1/1 + 1/3."""
        assert reciprocal_rank(["a", "x", "c"], RELEVANT) == pytest.approx(1.0)

    def test_k_truncates(self):
        # "a" sits at rank 3, outside k=2, so nothing relevant is in scope.
        assert reciprocal_rank(["x", "y", "a"], RELEVANT, k=2) == pytest.approx(0.0)

    def test_mrr_is_mean_of_reciprocal_ranks(self):
        """RR values 1.0, 0.5 and 0.0 -> MRR = 1.5 / 3 = 0.5."""
        retrieved = [["a", "x"], ["x", "a"], ["x", "y"]]
        relevant = [RELEVANT, RELEVANT, RELEVANT]
        assert mean_reciprocal_rank(retrieved, relevant) == pytest.approx(0.5)

    def test_mrr_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError):
            mean_reciprocal_rank([["a"]], [RELEVANT, RELEVANT])


class TestDuplicateHandling:
    """A retriever that returns the same chunk twice must not be rewarded."""

    def test_duplicates_do_not_inflate_precision(self):
        # Deduplicated top-3 is ["a", "b", "c"] -> 2 relevant of 3 = 2/3.
        # Without dedup, ["a", "a", "b"] would score 2/3 off a single document.
        assert precision_at_k(["a", "a", "b", "c"], RELEVANT, 3) == pytest.approx(2.0 / 3.0)

    def test_duplicates_do_not_inflate_recall(self):
        # Only one distinct relevant document is present, so recall is 1/3.
        assert recall_at_k(["a", "a", "a"], RELEVANT, 3) == pytest.approx(1.0 / 3.0)


class TestUndefinedCases:
    """No relevant chunks means the metric is undefined, not zero.

    A refusal case has no correct chunk by design. Reporting 0.0 would silently
    drag the corpus average down and make a correctly-refusing system look broken.
    """

    def test_precision_is_none(self):
        assert precision_at_k(RANKED, [], 3) is None

    def test_recall_is_none(self):
        assert recall_at_k(RANKED, [], 3) is None

    def test_hit_rate_is_none(self):
        assert hit_rate_at_k(RANKED, [], 3) is None

    def test_reciprocal_rank_is_none(self):
        assert reciprocal_rank(RANKED, []) is None

    def test_mean_skips_none(self):
        # (1.0 + 0.0) / 2 = 0.5; the None is skipped, not counted as a zero.
        assert mean([1.0, None, 0.0]) == pytest.approx(0.5)

    def test_mean_of_all_none_is_none(self):
        assert mean([None, None]) is None

    def test_mean_of_empty_is_none(self):
        assert mean([]) is None


class TestInvalidK:
    @pytest.mark.parametrize("bad_k", [0, -1])
    def test_rejects_non_positive_k(self, bad_k):
        with pytest.raises(ValueError):
            precision_at_k(RANKED, RELEVANT, bad_k)
        with pytest.raises(ValueError):
            recall_at_k(RANKED, RELEVANT, bad_k)
        with pytest.raises(ValueError):
            hit_rate_at_k(RANKED, RELEVANT, bad_k)


class TestRetrievalMetricsBundle:
    def test_keys_are_named_for_k(self):
        result = retrieval_metrics(RANKED, RELEVANT, 3)
        assert set(result) == {"precision@3", "recall@3", "hit_rate@3", "reciprocal_rank"}

    def test_values_match_individual_functions(self):
        result = retrieval_metrics(RANKED, RELEVANT, 3)
        assert result["precision@3"] == pytest.approx(2.0 / 3.0)
        assert result["recall@3"] == pytest.approx(2.0 / 3.0)
        assert result["hit_rate@3"] == pytest.approx(1.0)
        assert result["reciprocal_rank"] == pytest.approx(1.0)

    def test_accepts_a_generator_for_relevant(self):
        """``relevant`` is consumed more than once internally; a one-shot iterator
        must not silently produce zeros for the later metrics."""
        result = retrieval_metrics(RANKED, (item for item in RELEVANT), 3)
        assert result["recall@3"] == pytest.approx(2.0 / 3.0)
        assert result["hit_rate@3"] == pytest.approx(1.0)


class TestAggregation:
    def test_renames_reciprocal_rank_to_mrr(self):
        aggregated = aggregate_metrics([retrieval_metrics(RANKED, RELEVANT, 3)])
        assert "mrr" in aggregated
        assert "reciprocal_rank" not in aggregated

    def test_averages_across_cases(self):
        # precision@1 of 1.0 and 0.0 -> mean 0.5
        cases = [
            {"precision@1": 1.0, "reciprocal_rank": 1.0},
            {"precision@1": 0.0, "reciprocal_rank": 0.5},
        ]
        aggregated = aggregate_metrics(cases)
        assert aggregated["precision@1"] == pytest.approx(0.5)
        assert aggregated["mrr"] == pytest.approx(0.75)

    def test_undefined_case_does_not_drag_the_average(self):
        """A refusal case (all None) must not count as a zero."""
        cases = [
            {"precision@1": 1.0},
            {"precision@1": None},
        ]
        assert aggregate_metrics(cases)["precision@1"] == pytest.approx(1.0)

    def test_all_undefined_aggregates_to_none(self):
        assert aggregate_metrics([{"precision@1": None}])["precision@1"] is None
