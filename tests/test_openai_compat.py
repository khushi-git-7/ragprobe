"""The OpenAI-compatible provider, tested with an injected transport (no network)."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

import pytest

from ragprobe.config import ConfigError, GenerationConfig, ProbeConfig
from ragprobe.providers import get_provider
from ragprobe.providers.base import AnswerRequest, ContextChunk, JudgeRequest, REFUSAL_TEXT
from ragprobe.providers.chat_prompts import JudgeParseError, ProviderRefusal
from ragprobe.providers.openai_compat import (
    API_KEY_VARIABLES,
    OpenAICompatibleProvider,
    ProviderHTTPError,
    resolve_api_key,
)


class _Response:
    def __init__(self, payload: Any) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, body: str = "", headers: Dict[str, str] = None) -> urllib.error.HTTPError:
    import email.message

    msg = email.message.Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    return urllib.error.HTTPError("http://x", code, "err", msg, io.BytesIO(body.encode("utf-8")))


def _chat(content: Any, finish: str = "stop") -> Dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}


class FakeTransport:
    """Scripted responses: each item is a payload dict or an exception to raise."""

    def __init__(self, script: List[Any]) -> None:
        self.script = list(script)
        self.requests: List[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float):
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Response(item)


def _provider(script, **kwargs) -> OpenAICompatibleProvider:
    sleeps: List[float] = []
    kwargs.setdefault("api_key", "test-key")
    provider = OpenAICompatibleProvider(
        model="test-model", transport=FakeTransport(script), sleep=sleeps.append, **kwargs
    )
    provider.sleeps = sleeps  # type: ignore[attr-defined]
    return provider


def _answer_request(question="q", contexts=None) -> AnswerRequest:
    if contexts is None:
        contexts = [ContextChunk(chunk_id="doc#a", heading="A", text="Twenty days.", score=0.9)]
    return AnswerRequest(question=question, contexts=contexts, config=GenerationConfig())


# ------------------------------------------------------------------ config


class TestConfigAndFactory:
    def test_openai_is_a_valid_provider(self):
        cfg = ProbeConfig.from_dict({"generation": {"provider": "openai", "base_url": "http://x/v1"}})
        assert cfg.generation.base_url == "http://x/v1"

    def test_unknown_provider_lists_openai(self):
        with pytest.raises(ConfigError, match="'openai'"):
            ProbeConfig.from_dict({"generation": {"provider": "cohere"}})

    def test_factory_builds_provider_from_config(self, monkeypatch):
        monkeypatch.delenv("RAGPROBE_MODEL", raising=False)
        monkeypatch.delenv("RAGPROBE_BASE_URL", raising=False)
        cfg = GenerationConfig(provider="openai", model="gemini-2.5-flash",
                               base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
        provider = get_provider(cfg)
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.model == "gemini-2.5-flash"
        assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"

    def test_api_key_resolution_order(self, monkeypatch):
        for name in API_KEY_VARIABLES:
            monkeypatch.delenv(name, raising=False)
        assert resolve_api_key() is None
        monkeypatch.setenv("GEMINI_API_KEY", "g")
        assert resolve_api_key() == "g"
        monkeypatch.setenv("RAGPROBE_API_KEY", "override")
        assert resolve_api_key() == "override"


# --------------------------------------------------------------- answering


class TestAnswer:
    def test_sends_chat_completion_and_returns_text(self):
        provider = _provider([_chat("Twenty days. [doc#a]")])
        response = provider.answer(_answer_request("How many?"))
        assert response.text == "Twenty days. [doc#a]"
        assert response.refused is False
        assert response.provider == "openai" and response.model == "test-model"

        request = provider._transport.requests[0]  # type: ignore[attr-defined]
        assert request.full_url == "https://api.openai.com/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer test-key"
        body = json.loads(request.data.decode("utf-8"))
        assert body["model"] == "test-model" and body["temperature"] == 0
        assert body["messages"][0]["role"] == "system"
        assert "[doc#a] A" in body["messages"][1]["content"]
        assert body["messages"][1]["content"].endswith("QUESTION: How many?")

    def test_no_contexts_refuses_without_a_call(self):
        provider = _provider([])
        response = provider.answer(_answer_request(contexts=[]))
        assert response.refused and response.text == REFUSAL_TEXT
        assert provider.calls == 0

    def test_refusal_text_is_detected(self):
        provider = _provider([_chat(REFUSAL_TEXT)])
        assert provider.answer(_answer_request()).refused is True

    def test_content_parts_are_joined(self):
        provider = _provider([_chat([{"type": "text", "text": "A "}, {"type": "text", "text": "B"}])])
        assert provider.answer(_answer_request()).text == "A B"

    def test_content_filter_is_a_refusal_error(self):
        provider = _provider([_chat("", finish="content_filter")])
        with pytest.raises(ProviderRefusal):
            provider.answer(_answer_request())

    def test_no_auth_header_without_a_key(self):
        provider = _provider([_chat("x")], api_key="")
        provider.answer(_answer_request())
        assert provider._transport.requests[0].get_header("Authorization") is None  # type: ignore[attr-defined]


# ----------------------------------------------------------------- retries


class TestRetry:
    def test_retries_on_429_and_honours_retry_after(self):
        provider = _provider([_http_error(429, "slow down", {"Retry-After": "7"}), _chat("ok")])
        assert provider.answer(_answer_request()).text == "ok"
        assert provider.calls == 2 and provider.retries == 1
        assert provider.sleeps == [7.0]  # type: ignore[attr-defined]

    def test_backoff_doubles_without_retry_after(self):
        provider = _provider([_http_error(503), _http_error(502), _chat("ok")])
        provider.answer(_answer_request())
        assert provider.sleeps == [2.0, 4.0]  # type: ignore[attr-defined]

    def test_non_retryable_status_raises_with_detail(self):
        provider = _provider([_http_error(401, '{"error": "bad key"}')])
        with pytest.raises(ProviderHTTPError, match="HTTP 401.*bad key"):
            provider.answer(_answer_request())
        assert provider.retries == 0

    def test_gives_up_after_max_attempts(self):
        provider = _provider([_http_error(429)] * 6)
        with pytest.raises(ProviderHTTPError, match="HTTP 429"):
            provider.answer(_answer_request())
        assert provider.calls == 6

    def test_connection_errors_retry_then_raise(self):
        provider = _provider([urllib.error.URLError("refused")] * 6)
        with pytest.raises(ProviderHTTPError, match="could not reach"):
            provider.answer(_answer_request())

    def test_unexpected_shape_is_an_error(self):
        provider = _provider([{"unexpected": True}])
        with pytest.raises(ProviderHTTPError, match="unexpected response shape"):
            provider.answer(_answer_request())


# ----------------------------------------------------------------- judging


class TestJudge:
    def test_parses_verdict(self):
        verdict_json = json.dumps({"score": 0.25, "grounded": False, "unsupported_claims": ["x"], "rationale": "r"})
        provider = _provider([_chat("Sure:\n" + verdict_json)])
        verdict = provider.judge_faithfulness(JudgeRequest(question="q", answer="a", contexts=[]))
        assert verdict.score == 0.25 and verdict.grounded is False
        assert verdict.unsupported_claims == ["x"] and verdict.deterministic is False

    def test_prose_from_judge_is_an_explicit_error(self):
        provider = _provider([_chat("I think it is fine.")])
        with pytest.raises(JudgeParseError):
            provider.judge_faithfulness(JudgeRequest(question="q", answer="a", contexts=[]))
