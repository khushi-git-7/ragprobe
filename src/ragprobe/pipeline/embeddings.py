"""Embedding backends.

The default embedder is a **deterministic, pure-Python hashed TF-IDF** model. That
is a design decision, not a shortcut:

* It has zero dependencies and installs in seconds, so ``pytest`` and CI run offline.
* It is *bit-for-bit deterministic across processes*. Python's built-in ``hash()`` is
  randomised per interpreter run (PYTHONHASHSEED), so a naive hashing embedder would
  produce different vectors on every invocation and every "regression" the harness
  reported would be noise. ``zlib.crc32`` is stable, so the same corpus always
  produces the same index.

A neural embedder is available as an optional extra. It is strictly better at
semantic matching; it is also a multi-gigabyte install, so it is opt-in.
"""

from __future__ import annotations

import math
import zlib
from abc import ABC, abstractmethod
from collections import Counter
from typing import Dict, List, Optional, Sequence

from ragprobe.config import RetrievalConfig
from ragprobe.text_utils import tokenize

Vector = List[float]


class Embedder(ABC):
    """Interface every embedding backend implements."""

    name: str = "abstract"
    dim: int = 0

    @abstractmethod
    def fit(self, corpus: Sequence[str]) -> "Embedder":
        """Learn any corpus statistics (e.g. IDF). Must be idempotent."""

    @abstractmethod
    def embed(self, text: str) -> Vector:
        """Return an L2-normalised vector for ``text``."""

    def embed_many(self, texts: Sequence[str]) -> List[Vector]:
        """Embed passages. Backends with batched inference override this."""
        return [self.embed(text) for text in texts]

    def embed_query(self, text: str) -> Vector:
        """Embed a *question*. Same as ``embed`` unless the model distinguishes the two.

        Retrieval models such as bge are trained asymmetrically: a query and a
        passage are encoded differently, and using the passage path for both costs
        measurable recall. The pipeline calls this for questions only.
        """
        return self.embed(text)


def _l2_normalize(vector: Vector) -> Vector:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


class HashingTfidfEmbedder(Embedder):
    """Signed hashing-trick TF-IDF vectoriser.

    Each token is hashed to a bucket with ``crc32`` and given a deterministic sign
    from a second hash bit. The sign halves the bias introduced by hash collisions:
    two colliding tokens are as likely to cancel as to reinforce, so a collision
    degrades into noise rather than a systematic similarity inflation.

    Weighting is sublinear TF (``1 + log tf``) times smoothed IDF.
    """

    name = "tfidf"

    def __init__(self, dim: int = 512) -> None:
        if dim <= 8:
            raise ValueError("dim must be > 8")
        self.dim = dim
        self._idf: Dict[str, float] = {}
        self._default_idf: float = 1.0
        self._fitted = False

    # ------------------------------------------------------------------ fit

    def fit(self, corpus: Sequence[str]) -> "HashingTfidfEmbedder":
        doc_count = len(corpus)
        document_frequency: Counter = Counter()
        for text in corpus:
            for token in set(tokenize(text)):
                document_frequency[token] += 1
        # Smoothed IDF; the +1 in the numerator and denominator keeps a token that
        # appears in every document at a small positive weight instead of exactly 0,
        # so a query made entirely of common words still retrieves something.
        self._idf = {
            token: math.log((doc_count + 1) / (freq + 1)) + 1.0
            for token, freq in document_frequency.items()
        }
        # An unseen query token is treated as maximally rare.
        self._default_idf = math.log(doc_count + 1) + 1.0
        self._fitted = True
        return self

    # ---------------------------------------------------------------- embed

    @staticmethod
    def _bucket(token: str, dim: int) -> int:
        return zlib.crc32(token.encode("utf-8")) % dim

    @staticmethod
    def _sign(token: str) -> float:
        # A second, independent-ish hash. The seed makes it differ from _bucket.
        return 1.0 if zlib.crc32(token.encode("utf-8"), 0x9E3779B9) & 1 else -1.0

    def embed(self, text: str) -> Vector:
        vector = [0.0] * self.dim
        counts = Counter(tokenize(text))
        for token, count in counts.items():
            weight = (1.0 + math.log(count)) * self._idf.get(token, self._default_idf)
            vector[self._bucket(token, self.dim)] += self._sign(token) * weight
        return _l2_normalize(vector)

    @property
    def fitted(self) -> bool:
        return self._fitted


class SentenceTransformerEmbedder(Embedder):
    """Optional neural embedder. Requires ``pip install 'ragprobe[neural]'``.

    Note for anyone swapping this in: it is *not* a drop-in for the golden set's
    numeric thresholds. Cosine similarities from a neural model sit in a different
    range than TF-IDF cosines, so ``generation.refusal_threshold`` and
    ``retrieval.min_score`` have to be re-calibrated. Re-baseline after switching.
    """

    name = "sentence-transformers"

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised only when extra absent
            raise ImportError(
                "The 'sentence-transformers' embedder requires the optional extra:\n"
                "    pip install 'ragprobe[neural]'\n"
                "The default 'tfidf' embedder needs no extra dependencies."
            ) from exc
        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.model_name = model_name

    def fit(self, corpus: Sequence[str]) -> "SentenceTransformerEmbedder":
        return self  # pre-trained; nothing to learn from the corpus

    def embed(self, text: str) -> Vector:  # pragma: no cover - optional path
        vector = self._model.encode(text, normalize_embeddings=True)
        return [float(value) for value in vector]


class FastEmbedEmbedder(Embedder):
    """Neural embeddings through ONNX Runtime. Requires ``pip install 'ragprobe[fastembed]'``.

    This is the practical neural option: no PyTorch, a ~130 MB model, and CPU
    inference fast enough to re-index a few thousand chunks in a minute. The
    default model, ``BAAI/bge-small-en-v1.5``, is a strong small retrieval model;
    fastembed applies its query instruction automatically in ``embed_query``.

    As with any neural embedder, cosine scores live in a different range from
    TF-IDF cosines: re-calibrate ``generation.refusal_threshold`` and re-baseline.
    """

    name = "fastembed"
    DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

    def __init__(self, model_name: Optional[str] = None, batch_size: int = 32) -> None:
        try:
            from fastembed import TextEmbedding  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised only when extra absent
            raise ImportError(
                "The 'fastembed' embedder requires the optional extra: "
                "pip install 'ragprobe[fastembed]'. "
                "The default 'tfidf' embedder needs no extra dependencies."
            ) from exc
        self.model_name = model_name or self.DEFAULT_MODEL
        self.batch_size = batch_size
        self._model = TextEmbedding(model_name=self.model_name)
        self.dim = self._probe_dim()

    def _probe_dim(self) -> int:
        return len(self._first(self._model.embed(["dimension probe"])))

    @staticmethod
    def _first(vectors) -> Vector:  # noqa: ANN001 - generator of numpy arrays
        for vector in vectors:
            return [float(value) for value in vector]
        raise RuntimeError("embedding model returned no vectors")

    def fit(self, corpus: Sequence[str]) -> "FastEmbedEmbedder":
        return self  # pre-trained; nothing to learn from the corpus

    def embed(self, text: str) -> Vector:
        return _l2_normalize(self._first(self._model.embed([text])))

    def embed_many(self, texts: Sequence[str]) -> List[Vector]:
        vectors = self._model.embed(list(texts), batch_size=self.batch_size)
        return [_l2_normalize([float(value) for value in vector]) for vector in vectors]

    def embed_query(self, text: str) -> Vector:
        return _l2_normalize(self._first(self._model.query_embed(text)))


EMBEDDERS = ("tfidf", "fastembed", "sentence-transformers")


def get_embedder(cfg: RetrievalConfig) -> Embedder:
    """Factory keyed on ``retrieval.embedder``."""
    if cfg.embedder == "tfidf":
        return HashingTfidfEmbedder(dim=cfg.dim)
    if cfg.embedder == "fastembed":
        model = cfg.model_name if cfg.model_name and "sentence-transformers/" not in cfg.model_name else None
        return FastEmbedEmbedder(model_name=model)
    if cfg.embedder == "sentence-transformers":
        return SentenceTransformerEmbedder(model_name=cfg.model_name)
    raise ValueError(
        f"unknown embedder {cfg.embedder!r}; expected one of {', '.join(EMBEDDERS)}"
    )
