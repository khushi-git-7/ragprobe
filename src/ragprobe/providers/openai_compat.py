"""Live provider for any OpenAI-compatible chat completions endpoint.

One adapter covers the services people actually have keys for, including the free
ones, because they all speak the same ``/chat/completions`` dialect:

==================  =====================================================  ==================
service             ``generation.base_url``                                key variable
==================  =====================================================  ==================
Google AI Studio    https://generativelanguage.googleapis.com/v1beta/openai  GEMINI_API_KEY
Groq                https://api.groq.com/openai/v1                         GROQ_API_KEY
OpenAI              https://api.openai.com/v1                              OPENAI_API_KEY
Ollama (local)      http://localhost:11434/v1                              (none needed)
==================  =====================================================  ==================

Activated with ``generation.provider: openai`` (or ``RAGPROBE_PROVIDER=openai``).
``RAGPROBE_API_KEY`` overrides every service-specific variable. Standard library only:
no SDK to install, nothing to pin.

Free tiers are rate-limited per minute, so a 429 is expected on a suite of any size.
The adapter retries with backoff and honours ``Retry-After``; a run over 60 cases on a
10-requests-per-minute tier simply takes a few minutes rather than failing.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from ragprobe.providers.base import (
    REFUSAL_TEXT,
    AnswerRequest,
    AnswerResponse,
    JudgeRequest,
    JudgeVerdict,
    LLMProvider,
    format_contexts,
)
from ragprobe.providers.chat_prompts import (
    ANSWER_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT,
    ProviderRefusal,
    looks_like_refusal,
    parse_judge_json,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

#: Checked in order; the first one set wins. ``RAGPROBE_API_KEY`` is first so a
#: machine with several keys can pick explicitly.
API_KEY_VARIABLES = ("RAGPROBE_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY")

RETRY_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6


class ProviderHTTPError(RuntimeError):
    """The endpoint answered with an error the adapter could not recover from."""


def resolve_api_key() -> Optional[str]:
    for name in API_KEY_VARIABLES:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


class OpenAICompatibleProvider(LLMProvider):
    """Chat-completions client with retry, for OpenAI-compatible endpoints."""

    name = "openai"
    deterministic = False

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
        base_url: str = DEFAULT_BASE_URL,
        api_key: Optional[str] = None,
        timeout: float = 120.0,
        transport: Optional[Callable[[urllib.request.Request, float], Any]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = os.environ.get("RAGPROBE_MODEL", model)
        self.max_tokens = max_tokens
        self.base_url = (os.environ.get("RAGPROBE_BASE_URL", base_url) or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else resolve_api_key()
        self.timeout = timeout
        # Injection points used by the unit tests, which never touch the network.
        self._transport = transport or self._urlopen
        self._sleep = sleep
        self.calls = 0
        self.retries = 0

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _urlopen(request: urllib.request.Request, timeout: float) -> Any:
        return urllib.request.urlopen(request, timeout=timeout)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        return headers

    def _complete(self, system: str, user: str, max_tokens: int) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        payload = self._post("/chat/completions", body)
        try:
            choice = payload["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderHTTPError(f"unexpected response shape: {json.dumps(payload)[:200]}") from exc
        if choice.get("finish_reason") == "content_filter":
            raise ProviderRefusal("model declined the request (content_filter)")
        content = message.get("content")
        if isinstance(content, list):  # some servers return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return str(content or "").strip()

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8")
        delay = 2.0
        last_error = "no attempt made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            request = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
            self.calls += 1
            try:
                with self._transport(request, self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                last_error = f"HTTP {exc.code} from {url}: {detail}"
                if exc.code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                    raise ProviderHTTPError(last_error) from exc
                wait = _retry_after(exc.headers.get("Retry-After") if exc.headers else None, delay)
            except urllib.error.URLError as exc:
                last_error = f"could not reach {url}: {exc.reason}"
                if attempt == MAX_ATTEMPTS:
                    raise ProviderHTTPError(last_error) from exc
                wait = delay
            self.retries += 1
            self._sleep(wait)
            delay = min(delay * 2, 60.0)
        raise ProviderHTTPError(last_error)  # pragma: no cover - loop always returns or raises

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
            refused=looks_like_refusal(text),
            provider=self.name,
            model=self.model,
            metadata={"prompt_version": cfg.prompt_version, "base_url": self.base_url},
        )

    # ---------------------------------------------------------------- judging

    def judge_faithfulness(self, request: JudgeRequest) -> JudgeVerdict:
        user = (
            f"QUESTION: {request.question}\n\n"
            f"SOURCE DOCUMENTS:\n{format_contexts(request.contexts)}\n\n"
            f"ANSWER:\n{request.answer}"
        )
        raw = self._complete(JUDGE_SYSTEM_PROMPT, user, 1024)
        parsed = parse_judge_json(raw)
        return JudgeVerdict(
            score=parsed["score"],
            grounded=parsed["grounded"],
            unsupported_claims=parsed["unsupported_claims"],
            rationale=parsed["rationale"],
            provider=self.name,
            deterministic=False,
        )


def _retry_after(header: Optional[str], fallback: float) -> float:
    """Seconds to wait: the server's ``Retry-After`` if it is a sane number, else ours."""
    if header:
        try:
            value = float(header)
            if 0 < value <= 120:
                return value
        except ValueError:
            pass
    return fallback


__all__: List[str] = [
    "API_KEY_VARIABLES",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "OpenAICompatibleProvider",
    "ProviderHTTPError",
    "resolve_api_key",
]
