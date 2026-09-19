"""The system-under-test interface.

RAGProbe ships a reference pipeline, but the point of a harness is to evaluate the
RAG you actually run. A *target* is anything that can take a question and return an
answer plus the chunks it retrieved. The runner only ever talks to this interface, so
the golden set, every evaluator and the regression gate apply unchanged whether the
target is the built-in pipeline, a service behind an HTTP endpoint or a Python
function in your own codebase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Mapping, Sequence

from ragprobe.pipeline.rag import RagResult, RetrievedChunk
from ragprobe.providers.base import LLMProvider

#: Accepted spellings for each chunk field in an external response. The first
#: spelling is RAGProbe's own; the rest are what LangChain, LlamaIndex and most
#: hand-rolled services emit, so a target rarely needs a translation layer.
CHUNK_ID_KEYS = ("chunk_id", "id", "source", "doc_id")
CHUNK_TEXT_KEYS = ("text", "content", "page_content", "chunk", "passage")
CHUNK_HEADING_KEYS = ("heading", "title", "section", "source")
CHUNK_DOC_KEYS = ("doc_id", "document", "source", "file")
CHUNK_SCORE_KEYS = ("score", "similarity", "relevance", "distance")


class TargetError(RuntimeError):
    """The target could not be reached or answered in an unusable shape."""


class Target(ABC):
    """Every system under test implements this."""

    #: Short label written into results ("builtin", "http", "python").
    kind: str = "abstract"
    #: Whether repeated calls with identical input return identical output. External
    #: systems are assumed nondeterministic unless they say otherwise.
    deterministic: bool = False
    #: Provider used by the *evaluators* (the LLM-as-judge). This is deliberately
    #: separate from whatever model the target uses to answer.
    provider: LLMProvider

    def ingest(self) -> "Target":
        """Prepare the target. External targets usually have nothing to do."""
        return self

    @abstractmethod
    def answer(self, question: str) -> RagResult:
        """Answer one question and report what was retrieved."""

    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        """Describe the target for the results file."""

    @property
    def provider_name(self) -> str:
        """What answered the questions. Shown in reports next to the determinism flag."""
        return self.kind


def dig(payload: Any, path: str, default: Any = None) -> Any:
    """Follow a dotted path (``data.result.answer``) into nested mappings and lists."""
    if not path:
        return payload
    node = payload
    for part in path.split("."):
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        elif isinstance(node, Sequence) and not isinstance(node, str) and part.isdigit():
            index = int(part)
            if index >= len(node):
                return default
            node = node[index]
        else:
            return default
    return node


def _first(mapping: Mapping[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def normalise_chunks(raw: Any) -> List[RetrievedChunk]:
    """Turn whatever an external system returned into ranked ``RetrievedChunk``s.

    Accepts a list of mappings (any of the key spellings above), a list of strings
    (ids are then positional, ``ctx-1``...), or nothing. Rank is the list order,
    which is what every retrieval metric keys off.
    """
    if raw is None:
        return []
    if isinstance(raw, str) or isinstance(raw, Mapping) or not isinstance(raw, Sequence):
        raise TargetError(f"contexts must be a list, got {type(raw).__name__}")
    chunks: List[RetrievedChunk] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            chunks.append(
                RetrievedChunk(
                    chunk_id=f"ctx-{index}", doc_id="", heading="", text=item,
                    score=0.0, rank=index,
                )
            )
            continue
        if not isinstance(item, Mapping):
            raise TargetError(f"context {index} must be a string or an object")
        meta = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        chunk_id = _first(item, CHUNK_ID_KEYS) or _first(meta, CHUNK_ID_KEYS) or f"ctx-{index}"
        text = _first(item, CHUNK_TEXT_KEYS, "")
        score = _first(item, CHUNK_SCORE_KEYS) or _first(meta, CHUNK_SCORE_KEYS) or 0.0
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        chunks.append(
            RetrievedChunk(
                chunk_id=str(chunk_id),
                doc_id=str(_first(item, CHUNK_DOC_KEYS) or _first(meta, CHUNK_DOC_KEYS) or ""),
                heading=str(_first(item, CHUNK_HEADING_KEYS) or _first(meta, CHUNK_HEADING_KEYS) or ""),
                text=str(text),
                score=score,
                rank=index,
            )
        )
    return chunks


def result_from_payload(
    question: str,
    payload: Any,
    *,
    answer_field: str = "answer",
    contexts_field: str = "contexts",
    refused_field: str = "refused",
    provider: str = "external",
) -> RagResult:
    """Build a ``RagResult`` from an external response.

    The response may already be a ``RagResult`` (Python targets), a bare string
    (answer only, no retrieval metrics), or a mapping with the configured fields.
    A missing refusal flag is fine: the refusal evaluator reads the answer text.
    """
    if isinstance(payload, RagResult):
        return payload
    if isinstance(payload, str):
        return RagResult(question=question, answer=payload, refused=False, provider=provider)
    if not isinstance(payload, Mapping):
        raise TargetError(
            f"target returned {type(payload).__name__}; expected a mapping, a string or a RagResult"
        )
    answer = dig(payload, answer_field)
    if answer is None:
        raise TargetError(
            f"response has no {answer_field!r} field; keys present: {', '.join(sorted(map(str, payload)))}"
        )
    refused_raw = dig(payload, refused_field, None)
    retrieved = normalise_chunks(dig(payload, contexts_field))
    model = payload.get("model") if isinstance(payload.get("model"), str) else None
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    return RagResult(
        question=question,
        answer=str(answer),
        refused=bool(refused_raw) if refused_raw is not None else False,
        retrieved=retrieved,
        provider=provider,
        model=model,
        metadata=dict(metadata),
    )


