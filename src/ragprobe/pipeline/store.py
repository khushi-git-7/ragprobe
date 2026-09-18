"""In-memory vector store with exact cosine search.

Exact brute-force search over a few hundred chunks costs microseconds and has no
dependencies. More importantly for a *test harness*: it is exact. An ANN index
(FAISS, Chroma) is approximate, and its recall varies with index parameters and
sometimes with insertion order. Building a regression detector on top of a
nondeterministic retriever means chasing diffs that came from the index, not from
the change under test. If you swap in an ANN backend, pin the index parameters and
re-baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from ragprobe.pipeline.chunking import Chunk
from ragprobe.pipeline.embeddings import Vector


def cosine(left: Vector, right: Vector) -> float:
    """Dot product of two vectors.

    Both the embedder and ``add`` normalise, so the dot product *is* the cosine.
    """
    if len(left) != len(right):
        raise ValueError(f"vector dimension mismatch: {len(left)} != {len(right)}")
    return sum(a * b for a, b in zip(left, right))


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float


class InMemoryVectorStore:
    """Exact cosine-similarity index over chunk vectors."""

    def __init__(self) -> None:
        self._chunks: List[Chunk] = []
        self._vectors: List[Vector] = []
        self._by_id: Dict[str, Chunk] = {}

    def __len__(self) -> int:
        return len(self._chunks)

    @property
    def chunks(self) -> Sequence[Chunk]:
        return tuple(self._chunks)

    def get(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)

    def add(self, chunk: Chunk, vector: Vector) -> None:
        if chunk.chunk_id in self._by_id:
            raise ValueError(f"duplicate chunk_id: {chunk.chunk_id}")
        self._chunks.append(chunk)
        self._vectors.append(vector)
        self._by_id[chunk.chunk_id] = chunk

    def add_many(self, pairs: Sequence[Tuple[Chunk, Vector]]) -> None:
        for chunk, vector in pairs:
            self.add(chunk, vector)

    def search(self, query: Vector, k: int, min_score: float = 0.0) -> List[ScoredChunk]:
        """Return the top ``k`` chunks scoring at least ``min_score``.

        Ties are broken by chunk order, not by whatever order Python's sort happened
        to see. Without a deterministic tiebreak, two chunks with identical scores
        can swap places between runs and show up as a phantom retrieval regression.
        """
        if k <= 0:
            raise ValueError("k must be > 0")
        scored = [
            ScoredChunk(chunk=chunk, score=cosine(query, vector))
            for chunk, vector in zip(self._chunks, self._vectors)
        ]
        scored = [item for item in scored if item.score >= min_score]
        scored.sort(key=lambda item: (-item.score, item.chunk.order))
        return scored[:k]
