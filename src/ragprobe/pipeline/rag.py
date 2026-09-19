"""The assembled RAG pipeline - the system under test.

This is intentionally a *small, honest* RAG implementation rather than a wrapper
around a framework. The harness needs a system under test whose every behaviour is
attributable: when a metric moves, you must be able to say which stage moved it.
A framework would hide chunking and ranking behind defaults that change between
versions, which is a bad property for the thing your regression baseline is
measuring.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ragprobe.config import ProbeConfig
from ragprobe.pipeline.chunking import Chunk, chunk_document
from ragprobe.pipeline.embeddings import Embedder, get_embedder
from ragprobe.pipeline.loader import load_corpus
from ragprobe.pipeline.store import InMemoryVectorStore
from ragprobe.providers import get_provider
from ragprobe.providers.base import AnswerRequest, ContextChunk, LLMProvider


@dataclass
class RetrievedChunk:
    """A chunk returned by retrieval, with its score and 1-based rank."""

    chunk_id: str
    doc_id: str
    heading: str
    text: str
    score: float
    rank: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "heading": self.heading,
            "text": self.text,
            "score": round(self.score, 6),
            "rank": self.rank,
        }

    def as_context(self) -> ContextChunk:
        return ContextChunk(
            chunk_id=self.chunk_id, heading=self.heading, text=self.text, score=self.score
        )


@dataclass
class RagResult:
    """Everything one question produced. The harness evaluates this object."""

    question: str
    answer: str
    refused: bool
    retrieved: List[RetrievedChunk] = field(default_factory=list)
    provider: str = "stub"
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def retrieved_ids(self) -> List[str]:
        return [chunk.chunk_id for chunk in self.retrieved]

    @property
    def context_text(self) -> str:
        return "\n\n".join(chunk.text for chunk in self.retrieved)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "refused": self.refused,
            "retrieved": [chunk.to_dict() for chunk in self.retrieved],
            "provider": self.provider,
            "model": self.model,
            "metadata": self.metadata,
        }


class RagPipeline:
    """ingest -> chunk -> embed -> retrieve -> answer.

    This is the ``builtin`` target. It satisfies the ``ragprobe.targets.Target``
    surface (``ingest``, ``answer``, ``stats``, ``provider``, ``provider_name``,
    ``deterministic``) without inheriting from it, which keeps the import graph acyclic.
    """

    kind = "builtin"

    def __init__(
        self,
        config: ProbeConfig,
        provider: Optional[LLMProvider] = None,
        base_dir: Optional[Path] = None,
    ) -> None:
        self.config = config
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.provider: LLMProvider = provider or get_provider(config.generation)
        self.store = InMemoryVectorStore()
        self.embedder: Optional[Embedder] = None
        self.chunks: List[Chunk] = []
        self.embedding_cache_hit: Optional[bool] = None
        self._ingested = False

    # ---------------------------------------------------------------- ingest

    def ingest(self) -> "RagPipeline":
        """Load, chunk, fit the embedder and build the index."""
        corpus_dir = self.base_dir / self.config.corpus_dir
        documents = load_corpus(corpus_dir)

        chunks: List[Chunk] = []
        for doc_id in sorted(documents):
            chunks.extend(chunk_document(doc_id, documents[doc_id], self.config.chunk))
        if not chunks:
            raise RuntimeError(
                f"chunking produced no chunks from {corpus_dir}. "
                f"Check chunk.min_words ({self.config.chunk.min_words})."
            )
        self.chunks = chunks

        # IDF is fitted on the chunk texts, not the raw documents, because chunks are
        # the retrieval unit; fitting on documents would give a different, and
        # subtly wrong, notion of "how rare is this term in the search corpus".
        self.embedder = get_embedder(self.config.retrieval)
        self.embedder.fit([chunk.text for chunk in chunks])

        self.store = InMemoryVectorStore()
        for chunk, vector in zip(chunks, self._passage_vectors([c.text for c in chunks])):
            self.store.add(chunk, vector)
        self._ingested = True
        return self

    def _passage_vectors(self, texts: List[str]) -> List[List[float]]:
        """Embed passages, through the on-disk cache when the backend allows it.

        Neural embedding of a few thousand chunks is the slowest step of a run and
        its output is a pure function of (model, text), so an A/B of two prompt
        versions or two chunk sizes should not pay for it twice. The cache is keyed
        on the backend identity and the exact texts, so any change that alters a
        chunk misses cleanly.
        """
        assert self.embedder is not None
        cache_dir = self.config.retrieval.cache_dir
        if not (self.embedder.cacheable and cache_dir):
            # Batched: neural backends are an order of magnitude faster this way, and
            # the default implementation is the same per-chunk loop as before.
            return self.embedder.embed_many(texts)
        digest = hashlib.sha256()
        digest.update(self.embedder.cache_key().encode("utf-8"))
        for text in texts:
            digest.update(b"\x00")
            digest.update(text.encode("utf-8"))
        path = self.base_dir / cache_dir / (digest.hexdigest()[:24] + ".json")
        if path.is_file():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(cached, list) and len(cached) == len(texts):
                    self.embedding_cache_hit = True
                    return cached
            except (OSError, ValueError):
                pass  # a corrupt cache file is simply recomputed
        vectors = self.embedder.embed_many(texts)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps([[round(v, 7) for v in vec] for vec in vectors]), encoding="utf-8")
        except OSError:
            pass  # a read-only checkout must still run
        self.embedding_cache_hit = False
        return vectors

    def _ensure_ingested(self) -> None:
        if not self._ingested:
            self.ingest()

    # -------------------------------------------------------------- retrieve

    def retrieve(self, question: str, top_k: Optional[int] = None) -> List[RetrievedChunk]:
        self._ensure_ingested()
        assert self.embedder is not None
        k = top_k if top_k is not None else self.config.retrieval.top_k
        query_vector = self.embedder.embed_query(question)
        hits = self.store.search(query_vector, k=k, min_score=self.config.retrieval.min_score)
        return [
            RetrievedChunk(
                chunk_id=hit.chunk.chunk_id,
                doc_id=hit.chunk.doc_id,
                heading=hit.chunk.heading,
                text=hit.chunk.text,
                score=hit.score,
                rank=index,
            )
            for index, hit in enumerate(hits, start=1)
        ]

    # ----------------------------------------------------------------- answer

    def answer(self, question: str) -> RagResult:
        """Run the full pipeline for one question."""
        retrieved = self.retrieve(question)
        response = self.provider.answer(
            AnswerRequest(
                question=question,
                contexts=[chunk.as_context() for chunk in retrieved],
                config=self.config.generation,
            )
        )
        return RagResult(
            question=question,
            answer=response.text,
            refused=response.refused,
            retrieved=retrieved,
            provider=response.provider,
            model=response.model,
            metadata=response.metadata,
        )

    # ------------------------------------------------------------------ info

    @property
    def provider_name(self) -> str:
        return self.provider.name

    @property
    def deterministic(self) -> bool:
        return self.provider.deterministic

    def stats(self) -> Dict[str, Any]:
        self._ensure_ingested()
        return {
            "documents": len({chunk.doc_id for chunk in self.chunks}),
            "chunks": len(self.chunks),
            "embedder": self.config.retrieval.embedder,
            "dim": getattr(self.embedder, "dim", None),
            "embedding_cache_hit": self.embedding_cache_hit,
            "provider": self.provider.name,
            "deterministic_provider": self.provider.deterministic,
        }

    def chunk_ids(self) -> Sequence[str]:
        self._ensure_ingested()
        return [chunk.chunk_id for chunk in self.chunks]
