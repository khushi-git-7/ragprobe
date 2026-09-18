"""Unit tests for the deterministic answer-quality evaluators."""

from __future__ import annotations

import pytest

from ragprobe.evaluation.evaluators import (
    citation_present,
    detect_refusal,
    exact_match,
    expected_citation_overlap,
    extract_citations,
    forbidden_absent,
    fuzzy_match,
    keyword_presence,
    refusal_behaviour,
)


class TestExactMatch:
    def test_identical(self):
        assert exact_match("The limit is 20 days.", "The limit is 20 days.").passed

    def test_ignores_case_and_trailing_punctuation(self):
        """Normalisation exists so that cosmetic differences are not defects."""
        assert exact_match("the limit is 20 days", "The limit is 20 days.").passed

    def test_ignores_whitespace_differences(self):
        assert exact_match("the  limit\nis 20 days", "the limit is 20 days").passed

    def test_different_content_fails(self):
        assert not exact_match("The limit is 30 days.", "The limit is 20 days.").passed

    def test_skipped_when_no_expected_answer(self):
        result = exact_match("anything", None)
        assert result.applicable is False
        assert result.passed is True, "a skipped check must never fail a case"


class TestFuzzyMatch:
    def test_close_text_passes(self):
        result = fuzzy_match(
            "Full-time employees get 20 days of PTO per year.",
            "Full-time employees get 20 days of paid time off per year.",
            threshold=0.6,
        )
        assert result.passed
        assert 0.6 <= result.score <= 1.0

    def test_unrelated_text_fails(self):
        result = fuzzy_match("The sky is blue.", "Encryption keys rotate every 90 days.", 0.6)
        assert not result.passed

    def test_score_is_symmetric_enough_to_be_stable(self):
        a, b = "alpha beta gamma", "alpha beta delta"
        assert fuzzy_match(a, b).score == pytest.approx(fuzzy_match(b, a).score, abs=0.05)

    def test_skipped_when_no_expected_answer(self):
        assert fuzzy_match("anything", None).applicable is False


class TestKeywordPresence:
    def test_all_present(self):
        result = keyword_presence("The trial lasts 14 days on the Growth tier.", ["14", "Growth"])
        assert result.passed
        assert result.score == pytest.approx(1.0)

    def test_partial_score(self):
        result = keyword_presence("The trial lasts 14 days.", ["14", "Growth"])
        assert not result.passed
        assert result.score == pytest.approx(0.5)
        assert result.metadata["missing"] == ["Growth"]

    def test_case_insensitive(self):
        assert keyword_presence("growth tier", ["Growth"]).passed

    def test_multi_word_keyword(self):
        assert keyword_presence("costs 499 USD per month", ["499 USD"]).passed

    def test_does_not_match_inside_a_longer_number(self):
        """The reason whole-token matching exists.

        "99" must not be found inside "499", or a check asserting the Starter price
        would pass on an answer that only mentions the Growth price.
        """
        assert not keyword_presence("The Growth tier costs 499 USD.", ["99"]).passed

    def test_does_not_match_inside_a_longer_word(self):
        assert not keyword_presence("The catalogue is large.", ["cat"]).passed

    def test_skipped_when_no_keywords(self):
        assert keyword_presence("anything", []).applicable is False
        assert keyword_presence("anything", None).applicable is False


class TestForbiddenAbsent:
    def test_passes_when_absent(self):
        result = forbidden_absent("Telemetry is retained for 13 months.", ["90 days"])
        assert result.passed
        assert result.score == pytest.approx(1.0)

    def test_fails_when_present(self):
        result = forbidden_absent(
            "Telemetry is retained for 13 months and logs for 90 days.", ["90 days"]
        )
        assert not result.passed
        assert result.metadata["present"] == ["90 days"]

    def test_partial_score(self):
        result = forbidden_absent("contains alpha only", ["alpha", "beta"])
        assert result.score == pytest.approx(0.5)

    def test_skipped_when_none_declared(self):
        assert forbidden_absent("anything", []).applicable is False


class TestRefusalDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "I do not have enough information in the provided documents to answer that.",
            "I cannot answer that from the provided sources.",
            "Unable to answer based on the documents.",
        ],
    )
    def test_detects_refusals(self, text):
        assert detect_refusal(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Full-time employees accrue 20 days of paid time off.",
            "The Growth tier costs 499 USD per month.",
            "Customers are notified within 72 hours.",
        ],
    )
    def test_does_not_flag_real_answers(self, text):
        assert not detect_refusal(text)

    def test_correct_refusal_passes(self):
        result = refusal_behaviour("I cannot answer that.", should_refuse=True)
        assert result.passed

    def test_missing_refusal_fails(self):
        result = refusal_behaviour("The capital is Paris.", should_refuse=True)
        assert not result.passed
        assert "should have refused" in result.detail

    def test_over_refusal_fails(self):
        """Refusing an answerable question is a defect too.

        A system tuned to never hallucinate by never answering scores perfectly on
        faithfulness and is useless. This check is what catches that.
        """
        result = refusal_behaviour("I cannot answer that.", should_refuse=False)
        assert not result.passed
        assert "refused a question it should have answered" in result.detail

    def test_correct_answer_passes(self):
        assert refusal_behaviour("The limit is 20 days.", should_refuse=False).passed


class TestCitations:
    def test_extracts_in_order_without_duplicates(self):
        answer = "One [doc#a] two [doc#b] three [doc#a]"
        assert extract_citations(answer) == ["doc#a", "doc#b"]

    def test_extracts_nothing_from_plain_text(self):
        assert extract_citations("no citations here") == []

    def test_passes_when_citation_is_real(self):
        result = citation_present("Answer. [doc#a]", ["doc#a", "doc#b"])
        assert result.passed
        assert result.score == pytest.approx(1.0)

    def test_fails_when_no_citation(self):
        result = citation_present("Answer with no source.", ["doc#a"])
        assert not result.passed
        assert result.score == pytest.approx(0.0)

    def test_fails_on_fabricated_citation(self):
        """A citation to a chunk that was never retrieved is worse than none.

        It looks like evidence, so a reviewer spot-checking the output trusts it.
        """
        result = citation_present("Answer. [doc#never-retrieved]", ["doc#a"])
        assert not result.passed
        assert result.metadata["fabricated"] == ["doc#never-retrieved"]

    def test_partial_score_when_some_citations_are_fabricated(self):
        result = citation_present("A [doc#a] and B [doc#fake]", ["doc#a"])
        assert result.score == pytest.approx(0.5)

    def test_skipped_for_refusals(self):
        result = citation_present("I cannot answer.", ["doc#a"], is_refusal=True)
        assert result.applicable is False
        assert result.passed is True

    def test_skipped_when_citations_not_required(self):
        assert citation_present("Answer.", ["doc#a"], required=False).applicable is False


class TestExpectedCitationOverlap:
    def test_full_overlap(self):
        result = expected_citation_overlap("Answer. [doc#a]", ["doc#a"])
        assert result.passed
        assert result.score == pytest.approx(1.0)

    def test_partial_overlap(self):
        result = expected_citation_overlap("Answer. [doc#a]", ["doc#a", "doc#b"])
        assert result.score == pytest.approx(0.5)

    def test_split_chunk_matches_its_anchor(self):
        """Citing ``doc#a~2`` must satisfy an expectation of ``doc#a``."""
        result = expected_citation_overlap("Answer. [doc#a~2]", ["doc#a"])
        assert result.passed

    def test_no_overlap(self):
        result = expected_citation_overlap("Answer. [doc#z]", ["doc#a"])
        assert not result.passed
        assert result.score == pytest.approx(0.0)

    def test_skipped_when_no_expected_chunks(self):
        assert expected_citation_overlap("Answer.", []).applicable is False
