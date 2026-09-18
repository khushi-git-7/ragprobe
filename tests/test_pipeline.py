"""Tests for the RAG pipeline: embedder, vector store, retrieval and the stub provider."""

from __future__ import annotations

import math

import pytest

from ragprobe.config import GenerationConfig, ProbeConfig, RetrievalConfig
from ragprobe.pipeline.chunking import Chunk
from ragprobe.pipeline.embeddings import HashingTfidfEmbedder, get_embedder
from ragprobe.pipeline.store import InMemoryVectorStore, cosine
from ragprobe.providers.base import AnswerRequest, ContextChunk, JudgeRequest
from ragprobe.providers.stub import StubProvider

CORPUS = [
    "Telemetry data is retained for 13 months and then permanently deleted.",
    "The Growth tier costs 499 USD per month and supports up to 100 robots.",
    "Employees accrue 20 days of paid time off per calendar year.",
]


class TestHashingTfidfEmbedder:
    def test_vectors_are_l2_normalised(self):
        embedder = HashingTfidfEmbedder(dim=128).fit(CORPUS)
        vector = embedder.embed(CORPUS[0])
        assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0)

    def test_dimension_is_respected(self):
        embedder = HashingTfidfEmbedder(dim=64).fit(CORPUS)
        assert len(embedder.embed("anything")) == 64

    def test_identical_text_gives_identical_vectors(self):
        embedder = HashingTfidfEmbedder(dim=128).fit(CORPUS)
        assert embedder.embed(CORPUS[0]) == embedder.embed(CORPUS[0])

    def test_deterministic_across_separate_instances(self):
        """The reason crc32 is used instead of the built-in ``hash()``.

        Python randomises string hashing per interpreter process, so a naive
        hashing embedder would produce different vectors on every run and the
        regression gate would report pure noise.
        """
        first = HashingTfidfEmbedder(dim=128).fit(CORPUS).embed("data retention policy")
        second = HashingTfidfEmbedder(dim=128).fit(CORPUS).embed("data retention policy")
        assert first == second

    def test_related_text_scores_higher_than_unrelated(self):
        embedder = HashingTfidfEmbedder(dim=512).fit(CORPUS)
        query = embedder.embed("How long is telemetry retained?")
        related = cosine(query, embedder.embed(CORPUS[0]))
        unrelated = cosine(query, embedder.embed(CORPUS[1]))
        assert related > unrelated

    def test_empty_text_yields_a_zero_vector(self):
        embedder = HashingTfidfEmbedder(dim=32).fit(CORPUS)
        assert all(value == 0.0 for value in embedder.embed(""))

    def test_rejects_tiny_dimension(self):
        with pytest.raises(ValueError):
            HashingTfidfEmbedder(dim=4)

    def test_factory_returns_tfidf_by_default(self):
        assert isinstance(get_embedder(RetrievalConfig()), HashingTfidfEmbedder)

    def test_factory_rejects_unknown_embedder(self):
        with pytest.raises(ValueError):
            get_embedder(RetrievalConfig(embedder="magic"))


class TestVectorStore:
    @staticmethod
    def _chunk(index: int) -> Chunk:
        return Chunk(f"doc#c{index}", "doc", "Doc", f"H{index}", CORPUS[index], index)

    def _store(self):
        embedder = HashingTfidfEmbedder(dim=256).fit(CORPUS)
        store = InMemoryVectorStore()
        for index in range(len(CORPUS)):
            store.add(self._chunk(index), embedder.embed(CORPUS[index]))
        return store, embedder

    def test_len_and_lookup(self):
        store, _ = self._store()
        assert len(store) == 3
        assert store.get("doc#c0") is not None
        assert store.get("missing") is None

    def test_rejects_duplicate_chunk_id(self):
        store, embedder = self._store()
        with pytest.raises(ValueError):
            store.add(self._chunk(0), embedder.embed(CORPUS[0]))

    def test_search_returns_k_results_ranked(self):
        store, embedder = self._store()
        hits = store.search(embedder.embed("telemetry retention"), k=2)
        assert len(hits) == 2
        assert hits[0].score >= hits[1].score

    def test_search_finds_the_right_chunk(self):
        store, embedder = self._store()
        hits = store.search(embedder.embed("How many days of paid time off?"), k=1)
        assert hits[0].chunk.chunk_id == "doc#c2"

    def test_min_score_filters(self):
        store, embedder = self._store()
        assert store.search(embedder.embed("telemetry"), k=3, min_score=1.1) == []

    def test_rejects_non_positive_k(self):
        store, embedder = self._store()
        with pytest.raises(ValueError):
            store.search(embedder.embed("x"), k=0)

    def test_dimension_mismatch_is_an_error(self):
        with pytest.raises(ValueError):
            cosine([1.0, 0.0], [1.0, 0.0, 0.0])

    def test_ties_break_deterministically_by_chunk_order(self):
        """Identical scores must not swap between runs, or the diff shows phantom
        retrieval regressions."""
        store = InMemoryVectorStore()
        vector = [1.0, 0.0]
        for index in range(3):
            store.add(Chunk(f"doc#c{index}", "doc", "D", "H", "t", index), list(vector))
        ids = [hit.chunk.chunk_id for hit in store.search(vector, k=3)]
        assert ids == ["doc#c0", "doc#c1", "doc#c2"]


class TestStubProvider:
    CONTEXTS = [
        ContextChunk(
            chunk_id="doc#retention",
            heading="Data Retention",
            text="Telemetry data is retained for 13 months. Logs are retained for 90 days.",
            score=0.8,
        )
    ]

    def _answer(self, question: str, contexts=None, **cfg_kwargs):
        provider = StubProvider()
        config = GenerationConfig(**cfg_kwargs)
        return provider.answer(
            AnswerRequest(
                question=question,
                contexts=self.CONTEXTS if contexts is None else contexts,
                config=config,
            )
        )

    def test_is_marked_deterministic(self):
        assert StubProvider().deterministic is True

    def test_repeated_calls_return_identical_text(self):
        first = self._answer("How long is telemetry retained?")
        second = self._answer("How long is telemetry retained?")
        assert first.text == second.text

    def test_selects_the_relevant_sentence(self):
        result = self._answer("How long is telemetry data retained?", max_sentences=1)
        assert "13 months" in result.text
        assert not result.refused

    def test_includes_a_citation(self):
        result = self._answer("How long is telemetry retained?")
        assert "[doc#retention]" in result.text

    def test_citations_can_be_disabled(self):
        result = self._answer("How long is telemetry retained?", include_citations=False)
        assert "[doc#retention]" not in result.text

    def test_max_sentences_limits_output(self):
        one = self._answer("How long are telemetry and logs retained?", max_sentences=1)
        two = self._answer("How long are telemetry and logs retained?", max_sentences=2)
        assert len(one.text) < len(two.text)

    def test_prompt_version_changes_the_output_shape(self):
        """The knob that makes the regression demo real rather than staged."""
        v1 = self._answer("How long is telemetry retained?", prompt_version="v1")
        v2 = self._answer("How long is telemetry retained?", prompt_version="v2")
        assert v1.text != v2.text
        assert v2.text.startswith("Based on the retrieved documentation")
        assert "Sources:" in v2.text

    def test_refuses_with_no_context(self):
        result = self._answer("anything", contexts=[])
        assert result.refused
        assert result.metadata["reason"] == "no_context"

    def test_refuses_below_the_similarity_threshold(self):
        weak = [ContextChunk("doc#x", "H", "Some unrelated text about robots.", 0.01)]
        result = self._answer("How long is telemetry retained?", contexts=weak)
        assert result.refused
        assert result.metadata["reason"] == "below_refusal_threshold"

    def test_answers_are_extracted_verbatim_from_context(self):
        """Extractive by construction - the stub cannot hallucinate."""
        result = self._answer("How long is telemetry data retained?", max_sentences=1)
        sentence = result.text.split(" [")[0]
        assert sentence in self.CONTEXTS[0].text

    def test_stub_judge_is_deterministic_and_flags_ungrounded_text(self):
        provider = StubProvider()
        grounded = provider.judge_faithfulness(
            JudgeRequest("q", "Telemetry data is retained for 13 months.", self.CONTEXTS)
        )
        invented = provider.judge_faithfulness(
            JudgeRequest("q", "Telemetry data is retained for 42 years.", self.CONTEXTS)
        )
        assert grounded.deterministic and grounded.grounded
        assert not invented.grounded
        assert invented.unsupported_claims


class TestPipelineIntegration:
    def test_ingests_the_shipped_corpus(self, pipeline):
        stats = pipeline.stats()
        assert stats["documents"] == 5
        assert stats["chunks"] > 20
        assert stats["deterministic_provider"] is True

    def test_chunk_ids_are_unique(self, pipeline):
        ids = list(pipeline.chunk_ids())
        assert len(ids) == len(set(ids))

    def test_retrieval_respects_top_k(self, pipeline):
        assert len(pipeline.retrieve("paid time off", top_k=2)) == 2

    def test_ranks_are_one_based_and_ordered(self, pipeline):
        hits = pipeline.retrieve("paid time off", top_k=3)
        assert [hit.rank for hit in hits] == [1, 2, 3]
        assert hits[0].score >= hits[1].score >= hits[2].score

    def test_retrieves_the_expected_chunk_for_a_known_question(self, pipeline):
        hits = pipeline.retrieve("How many days of paid time off per year?", top_k=1)
        assert hits[0].chunk_id == "employee_handbook#paid-time-off"

    def test_answering_is_reproducible(self, pipeline):
        question = "How long is telemetry data retained?"
        assert pipeline.answer(question).answer == pipeline.answer(question).answer

    def test_out_of_domain_question_is_refused(self, pipeline):
        assert pipeline.answer("What is the capital of France?").refused

    def test_result_serialises(self, pipeline):
        data = pipeline.answer("How long is telemetry data retained?").to_dict()
        assert set(data) >= {"question", "answer", "refused", "retrieved", "provider"}


class TestConfigFingerprint:
    def test_identical_configs_share_a_fingerprint(self):
        assert ProbeConfig().fingerprint() == ProbeConfig().fingerprint()

    def test_prompt_version_change_changes_the_fingerprint(self):
        """Without this, a prompt edit would be invisible to the diff tool."""
        base = ProbeConfig()
        changed = ProbeConfig(generation=GenerationConfig(prompt_version="v2"))
        assert base.fingerprint() != changed.fingerprint()

    def test_top_k_change_changes_the_fingerprint(self):
        base = ProbeConfig()
        changed = ProbeConfig(retrieval=RetrievalConfig(top_k=5))
        assert base.fingerprint() != changed.fingerprint()

    def test_round_trip_through_dict_preserves_the_fingerprint(self):
        base = ProbeConfig()
        assert ProbeConfig.from_dict(base.to_dict()).fingerprint() == base.fingerprint()

    def test_overrides_apply(self):
        updated = ProbeConfig().apply_overrides({"retrieval.top_k": 7})
        assert updated.retrieval.top_k == 7

    def test_unknown_override_is_rejected(self):
        from ragprobe.config import ConfigError

        with pytest.raises(ConfigError):
            ProbeConfig().apply_overrides({"retrieval.nope": 1})
