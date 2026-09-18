"""The pluggable LLM provider interface.

Why this interface exists at all, since it is the single most important design
decision in RAGProbe:

A test suite that cannot run without a paid API key is not a test suite. It is a
manual procedure with extra steps. Nobody runs it on every pull request, so it stops
catching anything. By putting every model call behind this interface and shipping a
**deterministic stub as the default**, the whole harness runs in CI, offline, for
free, on every push - and the same suite can be pointed at a real model when you
want to measure real quality.

The two modes answer different questions, and conflating them is a common mistake:

* **Stub mode** answers *"did my retrieval, chunking, prompt-assembly and evaluation
  code change behaviour?"* It is fully deterministic, so any diff is a real diff.
* **Live mode** answers *"did answer quality change?"* It is nondeterministic, so a
  single run proves very little and small diffs must not be read as signal.

Stub mode is the regression gate. Live mode is a measurement you take deliberately.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ragprobe.config import GenerationConfig

#: The canonical refusal string. Kept as a constant so the pipeline and the refusal
#: evaluator cannot drift apart.
REFUSAL_TEXT = (
    "I do not have enough information in the provided documents to answer that."
)


@dataclass
class ContextChunk:
    """One retrieved chunk as handed to the provider."""

    chunk_id: str
    heading: str
    text: str
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnswerRequest:
    question: str
    contexts: List[ContextChunk]
    config: GenerationConfig


@dataclass
class AnswerResponse:
    text: str
    refused: bool
    provider: str
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgeRequest:
    question: str
    answer: str
    contexts: List[ContextChunk]


@dataclass
class JudgeVerdict:
    """Result of a faithfulness judgement."""

    score: float
    grounded: bool
    unsupported_claims: List[str]
    rationale: str
    provider: str
    #: True when the verdict is reproducible. False for any real model call - which
    #: is exactly why live-mode judge scores must not be used as a hard CI gate.
    deterministic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LLMProvider(ABC):
    """Every model interaction in RAGProbe goes through this interface."""

    name: str = "abstract"
    #: Whether repeated calls with identical input return identical output.
    deterministic: bool = False

    @abstractmethod
    def answer(self, request: AnswerRequest) -> AnswerResponse:
        """Synthesise an answer from the retrieved contexts."""

    @abstractmethod
    def judge_faithfulness(self, request: JudgeRequest) -> JudgeVerdict:
        """Judge whether every claim in the answer is supported by the contexts."""


def format_contexts(contexts: List[ContextChunk]) -> str:
    """Render contexts into the numbered block shared by every prompt."""
    if not contexts:
        return "(no documents retrieved)"
    blocks = []
    for item in contexts:
        blocks.append(f"[{item.chunk_id}] {item.heading}\n{item.text.strip()}")
    return "\n\n".join(blocks)
