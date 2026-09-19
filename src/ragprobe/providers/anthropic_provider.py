"""Optional live provider backed by Claude via the official ``anthropic`` SDK.

Activated with ``RAGPROBE_PROVIDER=anthropic`` (or ``generation.provider: anthropic``
in the config). Requires ``pip install 'ragprobe[anthropic]'`` and credentials.

Everything here is opt-in. The default test suite never imports this module's SDK
dependency, so a contributor without an API key can still run the full suite.
"""

from __future__ import annotations

import os
from typing import Any

from ragprobe.providers.base import (
    REFUSAL_TEXT,
    AnswerRequest,
    AnswerResponse,
    JudgeRequest,
    JudgeVerdict,
    LLMProvider,
    format_contexts,
)
from ragprobe.providers.chat_prompts import (  # noqa: F401 - re-exported for callers
    ANSWER_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT,
    JudgeParseError,
    ProviderRefusal,
    looks_like_refusal as _looks_like_refusal,
    parse_judge_json as _parse_judge_json,
)

DEFAULT_MODEL = "claude-opus-5"

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
