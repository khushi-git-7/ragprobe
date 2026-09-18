"""Optional live provider backed by Claude via the official ``anthropic`` SDK.

Activated with ``RAGPROBE_PROVIDER=anthropic`` (or ``generation.provider: anthropic``
in the config). Requires ``pip install 'ragprobe[anthropic]'`` and credentials.

Everything here is opt-in. The default test suite never imports this module's SDK
dependency, so a contributor without an API key can still run the full suite.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from ragprobe.providers.base import (
    REFUSAL_TEXT,
    AnswerRequest,
    AnswerResponse,
    JudgeRequest,
    JudgeVerdict,
    LLMProvider,
    format_contexts,
)

DEFAULT_MODEL = "claude-opus-5"

ANSWER_SYSTEM_PROMPT = """You are a retrieval-grounded question answering system.

Rules:
- Answer using ONLY the numbered source documents provided. Do not use outside knowledge.
- Cite the chunk id of every source you use, in square brackets, e.g. [security_policy#data-retention].
- Be concise: at most {max_sentences} sentence(s).
- If the sources do not contain the answer, reply with exactly this sentence and nothing else:
{refusal_text}"""

JUDGE_SYSTEM_PROMPT = """You are a strict faithfulness grader for a RAG system.

You will be given a QUESTION, the SOURCE DOCUMENTS that were retrieved, and an ANSWER.
Decide whether every factual claim in the ANSWER is directly supported by the SOURCE
DOCUMENTS. A claim that is true in the real world but absent from the sources is
NOT supported. Ignore style, tone and completeness; grade only groundedness.

Respond with a single JSON object and nothing else:
{"score": <float 0..1>, "grounded": <true|false>, "unsupported_claims": [<string>, ...], "rationale": "<one sentence>"}"""


class AnthropicProvider(LLMProvider):
    """Live Claude-backed provider."""

    name = "anthropic"
    deterministic = False

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
        client: Any = None,
    ) -> None:
        self.model = os.environ.get("RAGPROBE_MODEL", model)
        self.max_tokens = max_tokens
        if client is not None:
            # Injection point used by the unit tests, which never touch the network.
            self._client = client
        else:  # pragma: no cover - requires the optional SDK and credentials
            try:
                import anthropic
            except ImportError as exc:
                raise ImportError(
                    "The 'anthropic' provider requires the optional extra:\n"
                    "    pip install 'ragprobe[anthropic]'\n"
                    "RAGProbe's default 'stub' provider needs no API key."
                ) from exc
            self._client = anthropic.Anthropic()

    # --------------------------------------------------------------- helpers

    def _complete(self, system: str, user: str, max_tokens: int) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise ProviderRefusal(f"model declined the request (category={category})")
        return "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()

    # -------------------------------------------------------------- answering

    def answer(self, request: AnswerRequest) -> AnswerResponse:
        cfg = request.config
        if not request.contexts:
            return AnswerResponse(
                text=REFUSAL_TEXT,
                refused=True,
                provider=self.name,
                model=self.model,
                metadata={"reason": "no_context"},
            )
        system = ANSWER_SYSTEM_PROMPT.format(
            max_sentences=cfg.max_sentences, refusal_text=REFUSAL_TEXT
        )
        user = (
            f"SOURCE DOCUMENTS:\n{format_contexts(request.contexts)}\n\n"
            f"QUESTION: {request.question}"
        )
        text = self._complete(system, user, cfg.max_tokens)
        return AnswerResponse(
            text=text,
            refused=_looks_like_refusal(text),
            provider=self.name,
            model=self.model,
            metadata={"prompt_version": cfg.prompt_version},
        )

    # ---------------------------------------------------------------- judging

    def judge_faithfulness(self, request: JudgeRequest) -> JudgeVerdict:
        user = (
            f"QUESTION: {request.question}\n\n"
            f"SOURCE DOCUMENTS:\n{format_contexts(request.contexts)}\n\n"
            f"ANSWER:\n{request.answer}"
        )
        raw = self._complete(JUDGE_SYSTEM_PROMPT, user, 1024)
        parsed = _parse_judge_json(raw)
        return JudgeVerdict(
            score=parsed["score"],
            grounded=parsed["grounded"],
            unsupported_claims=parsed["unsupported_claims"],
            rationale=parsed["rationale"],
            provider=self.name,
            deterministic=False,
        )


class ProviderRefusal(RuntimeError):
    """Raised when the model declines to respond."""


class JudgeParseError(ValueError):
    """Raised when the judge returns something that is not usable JSON."""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _looks_like_refusal(text: str) -> bool:
    from ragprobe.evaluation.evaluators import detect_refusal

    return detect_refusal(text)


def _parse_judge_json(raw: str) -> Dict[str, Any]:
    """Parse the judge response defensively.

    A judge that returns prose instead of JSON is a real and frequent failure mode.
    It must surface as an explicit error rather than a silent 0.0, because a silent
    zero looks exactly like a detected hallucination and would poison the baseline.
    """
    match = _JSON_RE.search(raw or "")
    if not match:
        raise JudgeParseError(f"judge did not return JSON; got: {raw[:200]!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"judge returned malformed JSON: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise JudgeParseError(f"judge returned a non-object: {raw[:200]!r}")

    try:
        score = float(data["score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise JudgeParseError(f"judge response missing a numeric 'score': {data!r}") from exc
    score = min(1.0, max(0.0, score))

    claims: List[str] = []
    for claim in data.get("unsupported_claims") or []:
        claims.append(str(claim))

    grounded = data.get("grounded")
    if not isinstance(grounded, bool):
        grounded = not claims

    return {
        "score": score,
        "grounded": grounded,
        "unsupported_claims": claims,
        "rationale": str(data.get("rationale", "")).strip(),
    }
