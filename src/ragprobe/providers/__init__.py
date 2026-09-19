"""Provider registry.

Resolution order, highest priority first:

1. the ``RAGPROBE_PROVIDER`` environment variable
2. ``generation.provider`` in the config file
3. the built-in default, ``stub``

The environment variable wins so that the same config file and the same golden set
can be run in stub mode on CI and in live mode locally, with no file edits and
therefore no chance of accidentally committing a live-mode config.
"""

from __future__ import annotations

import os
from typing import Optional

from ragprobe.config import GenerationConfig
from ragprobe.providers.base import (
    REFUSAL_TEXT,
    AnswerRequest,
    AnswerResponse,
    ContextChunk,
    JudgeRequest,
    JudgeVerdict,
    LLMProvider,
)
from ragprobe.providers.stub import StubProvider

ENV_PROVIDER = "RAGPROBE_PROVIDER"

__all__ = [
    "REFUSAL_TEXT",
    "AnswerRequest",
    "AnswerResponse",
    "ContextChunk",
    "JudgeRequest",
    "JudgeVerdict",
    "LLMProvider",
    "StubProvider",
    "get_provider",
    "resolve_provider_name",
]


def resolve_provider_name(cfg: GenerationConfig, override: Optional[str] = None) -> str:
    if override:
        return override
    from_env = os.environ.get(ENV_PROVIDER)
    if from_env:
        return from_env.strip().lower()
    return cfg.provider


def get_provider(cfg: GenerationConfig, override: Optional[str] = None) -> LLMProvider:
    """Instantiate the configured provider."""
    name = resolve_provider_name(cfg, override)
    if name == "stub":
        return StubProvider()
    if name == "anthropic":
        # Imported lazily: the SDK is an optional dependency and must not be needed
        # to run the default suite.
        from ragprobe.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=cfg.model, max_tokens=cfg.max_tokens)
    if name == "openai":
        # Standard library only, but kept lazy so the default suite never
        # constructs a network client.
        from ragprobe.providers.openai_compat import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            model=cfg.model, max_tokens=cfg.max_tokens, base_url=cfg.base_url
        )
    raise ValueError(
        f"unknown provider {name!r}; expected 'stub', 'anthropic' or 'openai'. "
        f"Set {ENV_PROVIDER} or generation.provider."
    )
