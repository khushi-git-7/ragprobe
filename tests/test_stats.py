"""The statistics helpers return correct, stable numbers (checked by hand)."""

from __future__ import annotations

import pytest

from ragprobe.stats import (
    bootstrap_ci,
    cohens_h,
    mcnemar,
    mcnemar_from_pairs,
    odds_ratio,
    risk_difference,
    wilson_interval,
)


class TestWilson:
    def test_zero_successes_starts_at_zero(self):
        lo, hi = wilson_interval(0, 10)
        assert lo == 0.0 and 0.27 < hi < 0.29  # known Wilson upper ~0.2775

    def test_half_is_symmetric_about_a_half(self):
        lo, hi = wilson_interval(5, 10)
        assert abs((lo + hi) / 2 - 0.5) < 1e-9
        assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77

    def test_all_successes_caps_at_one(self):
        lo, hi = wilson_interval(10, 10)
        assert hi == 1.0 and lo < 1.0

    def test_empty_sample_is_degenerate(self):
        assert wilson_interval(0, 0) == (0.0, 0.0)

    def test_matches_the_suite_implementation(self):
        # the security suite's private _wilson must agree with the public one
        from ragprobe.security.suite import _wilson
        for s, n in [(0, 5), (3, 12), (7, 7), (1, 100)]:
            assert tuple(_wilson(s, n)) == wilson_interval(s, n)


class TestMcNemar:
    def test_no_disagreement_is_not_significant(self):
        r = mcnemar(0, 0)
        assert r["p_value"] == 1.0 and r["discordant"] == 0

    def test_symmetric_disagreement_is_not_significant(self):
        r = mcnemar(5, 5)
        assert r["p_value"] == 1.0

    def test_exact_small_sample_matches_hand_calculation(self):
        # b=8, c=0, n=8: two-sided exact p = 2 * (0.5**8) = 0.0078125
        r = mcnemar(8, 0)
        assert r["method"] == "exact-binomial"
        assert abs(r["p_value"] - 0.0078125) < 1e-5  # reported p is rounded to 6 dp

    def test_large_sample_uses_chi_square(self):
        r = mcnemar(30, 10)  # n = 40 > 25
        assert r["method"] == "chi2-continuity"
        # stat = (|20|-1)**2 / 40 = 9.025 -> p ~ 0.00266
        assert abs(r["statistic"] - 9.025) < 1e-3
        assert r["p_value"] < 0.01

    def test_force_exact_overrides_the_threshold(self):
        assert mcnemar(30, 10, exact=True)["method"] == "exact-binomial"

    def test_from_pairs_counts_discordant_cells(self):
        wins_a = [True, True, False, True, False]
        wins_b = [False, True, False, False, True]
        # a&!b at indices 0,3 -> b=2 ; b&!a at index 4 -> c=1
        r = mcnemar_from_pairs(wins_a, wins_b)
        assert r["b"] == 2 and r["c"] == 1

    def test_from_pairs_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError):
            mcnemar_from_pairs([True], [True, False])


class TestBootstrap:
    def test_constant_statistic_has_zero_width(self):
        lo, hi = bootstrap_ci([1, 2, 3], lambda s: 42.0)
        assert lo == 42.0 and hi == 42.0

    def test_is_deterministic_for_a_seed(self):
        items = list(range(50))
        mean = lambda s: sum(s) / len(s)
        assert bootstrap_ci(items, mean, seed=7) == bootstrap_ci(items, mean, seed=7)

    def test_interval_brackets_the_point_estimate(self):
        items = [(1, 1), (1, 1), (0, 1), (1, 0), (1, 1)]  # (pred, label) pairs

        def recall(sample):
            tp = sum(1 for p, y in sample if p and y)
            pos = sum(1 for _, y in sample if y)
            return tp / pos if pos else 0.0

        point = recall(items)
        lo, hi = bootstrap_ci(items, recall, resamples=1000, seed=1)
        assert lo <= point <= hi

    def test_empty_is_degenerate(self):
        assert bootstrap_ci([], lambda s: 1.0) == (0.0, 0.0)


class TestEffectSizes:
    def test_risk_difference(self):
        assert risk_difference(5, 10, 2, 10) == 0.3

    def test_odds_ratio_handles_zero_cells(self):
        # a clean separation (10/10 vs 0/10) would divide by zero without the
        # Haldane correction; with it the ratio is large but finite
        assert odds_ratio(10, 10, 0, 10) > 100

    def test_cohens_h_matches_hand_value(self):
        # the English/German recall gap, 50% vs 26%
        assert abs(cohens_h(0.50, 0.26) - 0.4998) < 1e-3

    def test_cohens_h_zero_when_equal(self):
        assert cohens_h(0.4, 0.4) == 0.0
