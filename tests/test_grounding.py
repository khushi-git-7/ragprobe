"""Unit tests for the offline faithfulness heuristic.

The negative controls matter most here. An evaluator that says "grounded" for every
input passes every positive test and detects nothing. Several tests below feed the
checker deliberately unfaithful answers and assert that it catches them - and one
test documents a case it is *known to miss*, so the limitation is pinned rather than
forgotten.
"""

from __future__ import annotations

import pytest

from ragprobe.evaluation.grounding import score_grounding

CONTEXT = (
    "Telemetry data is retained for 13 months and then permanently deleted. "
    "Application logs are retained for 90 days. "
    "Customer account records are retained for the duration of the contract plus 7 years."
)


class TestGroundedAnswers:
    def test_verbatim_answer_scores_high(self):
        result = score_grounding("Telemetry data is retained for 13 months.", CONTEXT)
        assert result.grounded
        assert result.score > 0.8

    def test_citation_markers_do_not_reduce_the_score(self):
        """Citations are metadata, not claims; they must be stripped before scoring."""
        without = score_grounding("Telemetry data is retained for 13 months.", CONTEXT)
        with_citation = score_grounding(
            "Telemetry data is retained for 13 months. [security_policy#data-retention]", CONTEXT
        )
        assert with_citation.score == pytest.approx(without.score, abs=0.05)
        assert with_citation.grounded

    def test_multi_sentence_grounded_answer(self):
        answer = (
            "Telemetry data is retained for 13 months. Application logs are retained for 90 days."
        )
        assert score_grounding(answer, CONTEXT).grounded


class TestUngroundedAnswers:
    def test_wholly_unrelated_answer_is_flagged(self):
        result = score_grounding("The capital of France is Paris.", CONTEXT)
        assert not result.grounded
        assert result.score < 0.55

    def test_invented_number_is_flagged(self):
        """The most dangerous RAG error: right topic, wrong figure.

        "24 months" never appears in the context, so the numeric check fires even
        though the surrounding wording is copied from the source.
        """
        result = score_grounding("Telemetry data is retained for 24 months.", CONTEXT)
        assert not result.grounded
        assert "24" in result.claims[0].unsupported_numbers

    def test_unsupported_claim_is_reported_individually(self):
        answer = (
            "Telemetry data is retained for 13 months. "
            "Northwind Robotics was founded by a team of marine biologists."
        )
        result = score_grounding(answer, CONTEXT)
        assert not result.grounded
        assert len(result.unsupported_claims) == 1
        assert "marine biologists" in result.unsupported_claims[0].text

    def test_empty_context_grounds_nothing(self):
        result = score_grounding("Telemetry is retained for 13 months.", "")
        assert not result.grounded
        assert result.score == pytest.approx(0.0)

    def test_empty_answer_scores_zero(self):
        result = score_grounding("", CONTEXT)
        assert not result.grounded
        assert result.score == pytest.approx(0.0)
        assert result.claims == []


class TestScoringMechanics:
    def test_bigram_weighting_punishes_scrambled_vocabulary(self):
        """An answer reusing the context's words in a meaningless order must score
        below a faithful answer, even though unigram overlap is similar."""
        faithful = score_grounding("Application logs are retained for 90 days.", CONTEXT)
        scrambled = score_grounding("Retained logs application for days 90 deleted.", CONTEXT)
        assert faithful.score > scrambled.score

    def test_per_claim_detail_is_exposed(self):
        answer = "Telemetry data is retained for 13 months. Logs are retained for 90 days."
        result = score_grounding(answer, CONTEXT)
        assert len(result.claims) == 2
        for claim in result.claims:
            assert 0.0 <= claim.score <= 1.0
            assert 0.0 <= claim.unigram_coverage <= 1.0
            assert 0.0 <= claim.bigram_coverage <= 1.0

    def test_overall_score_is_the_mean_of_claim_scores(self):
        answer = "Telemetry data is retained for 13 months. The moon is made of cheese."
        result = score_grounding(answer, CONTEXT)
        expected = sum(claim.score for claim in result.claims) / len(result.claims)
        assert result.score == pytest.approx(expected)

    def test_threshold_is_respected(self):
        """The same answer flips verdict either side of its own score.

        Pinned relative to the measured score rather than to a magic constant, so
        the test stays meaningful if the scoring weights are ever re-tuned.
        """
        answer = "Application logs are kept for 90 days under the retention rules."
        # claim_threshold=0.0 keeps every claim "supported" so that the overall
        # grounding_threshold is the only thing deciding the verdict.
        score = score_grounding(answer, CONTEXT, claim_threshold=0.0).score
        assert 0.0 < score < 1.0, "this fixture must score strictly between the bounds"
        above = score_grounding(
            answer, CONTEXT, claim_threshold=0.0, grounding_threshold=score + 0.01
        )
        below = score_grounding(
            answer, CONTEXT, claim_threshold=0.0, grounding_threshold=score - 0.01
        )
        assert above.grounded is False
        assert below.grounded is True

    def test_claim_threshold_can_fail_an_otherwise_high_scoring_answer(self):
        """Both gates must hold: a single unsupported claim fails the whole answer,
        even when the mean score clears the overall threshold."""
        answer = "Telemetry data is retained for 13 months. Robots dream of electric sheep."
        result = score_grounding(answer, CONTEXT, grounding_threshold=0.0)
        assert result.score >= 0.0
        assert result.grounded is False
        assert len(result.unsupported_claims) == 1

    def test_serialisation_round_trips(self):
        data = score_grounding("Telemetry data is retained for 13 months.", CONTEXT).to_dict()
        assert set(data) == {"score", "grounded", "claims", "unsupported_claims"}
        assert isinstance(data["claims"], list)


class TestKnownLimitations:
    """Pinned limitations. These document what the heuristic cannot do.

    They are written as passing tests asserting the *current, known-imperfect*
    behaviour so that the weakness is visible in the suite instead of being
    rediscovered in production. If a future change makes the checker smarter, these
    tests will fail loudly and should be updated - a deliberate tripwire.
    """

    def test_misses_a_swapped_number_that_exists_elsewhere_in_context(self):
        """The heuristic's blind spot.

        "Telemetry data is retained for 90 days" is FALSE - telemetry is 13 months;
        90 days is the log retention period. But "90" does appear in the context, so
        the numeric check does not fire, and the phrasing is lexically faithful.
        A lexical overlap measure cannot catch this. An entailment model or an LLM
        judge can, which is exactly why RAGProbe ships both and reports them apart.
        """
        result = score_grounding("Telemetry data is retained for 90 days.", CONTEXT)
        assert result.grounded, (
            "If this now fails, the heuristic has genuinely improved - update this test."
        )

    def test_flags_heavy_paraphrase_even_when_correct(self):
        """The opposite failure: a correct answer in different words scores low.

        Harmless for the extractive stub provider, which copies text verbatim, but
        it means the heuristic is too strict for a real generative model and must
        not be the only faithfulness signal in live mode.
        """
        result = score_grounding(
            "We keep usage measurements for just over a year before erasing them.", CONTEXT
        )
        assert not result.grounded
