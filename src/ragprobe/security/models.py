"""A registry of free LLM endpoints the security suite can attack.

Each entry says how to reach a model and which environment variable holds its key,
so a comparison run can build the right client per model even when several keys are
set at once. Everything here is a free tier: Groq's hosted open models and Google
AI Studio's Gemini. No entry needs a credit card.

A spec is either a registry shortname (``groq-qwen``) or ``provider:model`` for a
model not listed, where ``provider`` is ``groq`` or ``gemini`` and supplies the
base URL and key variable (e.g. ``groq:llama-3.3-70b-versatile``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

GROQ_BASE = "https://api.groq.com/openai/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    base_url: str
    model: str
    key_env: str
    note: str = ""


REGISTRY: Dict[str, ModelSpec] = {
    "groq-qwen": ModelSpec("groq-qwen", GROQ_BASE, "qwen/qwen3.8-27b", "GROQ_API_KEY",
                           "Alibaba Qwen 3.8 27B, hosted on Groq"),
    "groq-gptoss": ModelSpec("groq-gptoss", GROQ_BASE, "openai/gpt-oss-20b", "GROQ_API_KEY",
                             "OpenAI gpt-oss 20B (open weights), hosted on Groq"),
    "groq-gptoss-120b": ModelSpec("groq-gptoss-120b", GROQ_BASE, "openai/gpt-oss-120b",
                                  "GROQ_API_KEY", "OpenAI gpt-oss 120B, hosted on Groq"),
    "gemini": ModelSpec("gemini", GEMINI_BASE, "gemini-flash-latest", "GEMINI_API_KEY",
                        "Google Gemini Flash (free tier)"),
}


PROVIDER_BASES = {
    "groq": (GROQ_BASE, "GROQ_API_KEY"),
    "gemini": (GEMINI_BASE, "GEMINI_API_KEY"),
}


def resolve(spec: str) -> ModelSpec:
    if spec in REGISTRY:
        return REGISTRY[spec]
    provider, sep, model = spec.partition(":")
    if sep and provider in PROVIDER_BASES and model:
        base_url, key_env = PROVIDER_BASES[provider]
        return ModelSpec(spec, base_url, model, key_env)
    raise ValueError(
        f"unknown model {spec!r}; use one of {', '.join(REGISTRY)} "
        f"or 'provider:model' where provider is {' or '.join(PROVIDER_BASES)}"
    )


def build_victim(spec: ModelSpec, api_key: Optional[str], max_tokens: int = 512):
    """A live victim for one model, with the key chosen explicitly (not by env order)."""
    from ragprobe.providers.openai_compat import OpenAICompatibleProvider
    from ragprobe.security.victims import LiveVictim

    provider = OpenAICompatibleProvider(model=spec.model, base_url=spec.base_url, api_key=api_key)
    victim = LiveVictim(provider, max_tokens=max_tokens)
    victim.name = spec.name
    return victim
