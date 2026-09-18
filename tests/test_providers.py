"""Tests for provider selection and the live-provider adapter.

The Anthropic provider is tested with an **injected fake client**. No network call
is made and no API key is needed, so these tests run in the same offline CI job as
everything else. What is under test is our adapter - prompt assembly, refusal
handling and above all the judge-response parsing - not the SDK.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ragprobe.config import GenerationConfig
from ragprobe.providers import get_provider, resolve_provider_name
from ragprobe.providers.anthropic_provider import (
    AnthropicProvider,
    JudgeParseError,
    ProviderRefusal,
    _parse_judge_json,
)
from ragprobe.providers.base import AnswerRequest, ContextChunk, JudgeRequest
from ragprobe.providers.stub import StubProvider

CONTEXTS = [
    ContextChunk(
        chunk_id="doc#retention",
        heading="Data Retention",
        text="Telemetry data is retained for 13 months.",
        score=0.9,
    )
]


class FakeClient:
    """Minimal stand-in for ``anthropic.Anthropic``."""

    def __init__(self, text: str = "", stop_reason: str = "end_turn"):
        self.text = text
        self.stop_reason = stop_reason
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)],
            stop_reason=self.stop_reason,
            stop_details=SimpleNamespace(category="cyber") if self.stop_reason == "refusal" else None,
        )


class TestProviderRegistry:
    def test_default_is_the_stub(self, monkeypatch):
        monkeypatch.delenv("RAGPROBE_PROVIDER", raising=False)
        assert resolve_provider_name(GenerationConfig()) == "stub"
        assert isinstance(get_provider(GenerationConfig()), StubProvider)

    def test_env_var_overrides_the_config(self, monkeypatch):
        """So CI can run stub mode and a developer can run live mode from the same
        config file, with no risk of committing a live-mode default."""
        monkeypatch.setenv("RAGPROBE_PROVIDER", "anthropic")
        assert resolve_provider_name(GenerationConfig(provider="stub")) == "anthropic"

    def test_explicit_override_beats_the_env_var(self, monkeypatch):
        monkeypatch.setenv("RAGPROBE_PROVIDER", "anthropic")
        assert resolve_provider_name(GenerationConfig(), override="stub") == "stub"

    def test_unknown_provider_is_rejected(self, monkeypatch):
        monkeypatch.delenv("RAGPROBE_PROVIDER", raising=False)
        with pytest.raises(ValueError, match="unknown provider"):
            get_provider(GenerationConfig(), override="gpt-9")


class TestAnthropicAdapter:
    def test_answer_uses_the_model_response(self):
        client = FakeClient(text="Telemetry is retained for 13 months. [doc#retention]")
        provider = AnthropicProvider(client=client)
        result = provider.answer(
            AnswerRequest("How long?", CONTEXTS, GenerationConfig(provider="anthropic"))
        )
        assert "13 months" in result.text
        assert result.provider == "anthropic"
        assert result.refused is False

    def test_is_marked_nondeterministic(self):
        assert AnthropicProvider(client=FakeClient()).deterministic is False

    def test_prompt_includes_contexts_and_the_question(self):
        client = FakeClient(text="answer")
        AnthropicProvider(client=client).answer(
            AnswerRequest("How long is telemetry retained?", CONTEXTS, GenerationConfig())
        )
        user_message = client.calls[0]["messages"][0]["content"]
        assert "doc#retention" in user_message
        assert "How long is telemetry retained?" in user_message

    def test_system_prompt_requests_citations_and_sets_the_refusal_string(self):
        client = FakeClient(text="answer")
        AnthropicProvider(client=client).answer(
            AnswerRequest("q", CONTEXTS, GenerationConfig())
        )
        system = client.calls[0]["system"]
        assert "square brackets" in system
        assert "do not have enough information" in system.lower()

    def test_empty_context_short_circuits_without_calling_the_model(self):
        """Never pay for a request that cannot possibly be grounded."""
        client = FakeClient(text="should not be used")
        result = AnthropicProvider(client=client).answer(
            AnswerRequest("q", [], GenerationConfig())
        )
        assert result.refused
        assert client.calls == []

    def test_model_refusal_raises(self):
        client = FakeClient(text="", stop_reason="refusal")
        with pytest.raises(ProviderRefusal):
            AnthropicProvider(client=client).answer(
                AnswerRequest("q", CONTEXTS, GenerationConfig())
            )

    def test_model_id_can_be_overridden_by_env(self, monkeypatch):
        monkeypatch.setenv("RAGPROBE_MODEL", "claude-sonnet-5")
        assert AnthropicProvider(client=FakeClient()).model == "claude-sonnet-5"

    def test_judge_returns_a_parsed_verdict(self):
        client = FakeClient(
            text='{"score": 0.2, "grounded": false, '
            '"unsupported_claims": ["invented figure"], "rationale": "not in sources"}'
        )
        verdict = AnthropicProvider(client=client).judge_faithfulness(
            JudgeRequest("q", "Telemetry is retained for 99 years.", CONTEXTS)
        )
        assert verdict.grounded is False
        assert verdict.score == pytest.approx(0.2)
        assert verdict.unsupported_claims == ["invented figure"]
        assert verdict.deterministic is False


class TestJudgeResponseParsing:
    """The judge returning prose instead of JSON is a real, frequent failure mode."""

    def test_parses_clean_json(self):
        parsed = _parse_judge_json('{"score": 1.0, "grounded": true, "rationale": "ok"}')
        assert parsed["score"] == pytest.approx(1.0)
        assert parsed["grounded"] is True

    def test_tolerates_surrounding_prose(self):
        parsed = _parse_judge_json(
            'Sure! Here is my assessment:\n{"score": 0.5, "grounded": false}\nHope that helps.'
        )
        assert parsed["score"] == pytest.approx(0.5)

    def test_clamps_out_of_range_scores(self):
        assert _parse_judge_json('{"score": 7}')["score"] == pytest.approx(1.0)
        assert _parse_judge_json('{"score": -3}')["score"] == pytest.approx(0.0)

    def test_infers_grounded_from_claims_when_the_field_is_missing(self):
        assert _parse_judge_json('{"score": 0.9}')["grounded"] is True
        assert _parse_judge_json('{"score": 0.1, "unsupported_claims": ["x"]}')["grounded"] is False

    def test_prose_response_raises_rather_than_scoring_zero(self):
        """A silent 0.0 looks exactly like a detected hallucination.

        If the judge misbehaves, that must surface as an error - otherwise a broken
        judge quietly poisons the baseline with fake hallucination findings.
        """
        with pytest.raises(JudgeParseError):
            _parse_judge_json("I think the answer looks broadly fine, honestly.")

    def test_malformed_json_raises(self):
        with pytest.raises(JudgeParseError):
            _parse_judge_json('{"score": 0.5, "grounded":}')

    def test_missing_score_raises(self):
        with pytest.raises(JudgeParseError):
            _parse_judge_json('{"grounded": true}')

    def test_non_numeric_score_raises(self):
        with pytest.raises(JudgeParseError):
            _parse_judge_json('{"score": "very good"}')
