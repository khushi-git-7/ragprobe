"""The deterministic stub provider - RAGProbe's default.

The stub is an *extractive* answerer: it selects the sentences from the retrieved
chunks that overlap most with the question and stitches them together with
citations. It is not pretending to be a language model. It is a fixed, inspectable
function of (question, retrieved chunks, generation config), which gives the harness
three properties that a real model cannot:

1. Identical input always produces identical output, so every diff the regression
   gate reports is caused by the change under test.
2. It responds to prompt/config changes (``prompt_version``, ``max_sentences``,
   ``include_citations``, ``refusal_threshold``), so the regression machinery is
   genuinely exercised rather than trivially always-green.
3. It costs nothing and needs no network, so CI runs it on every push.

Because it is extractive, it is faithful by construction - it cannot hallucinate.
That is a *limitation to be honest about*: stub mode proves the plumbing works, it
does not prove your real model is faithful. Use live mode for that. The grounding
evaluator is still exercised in stub mode via the negative-control fixtures in the
test suite, which feed it deliberately unfaithful answers.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from ragprobe.providers.base import (
    REFUSAL_TEXT,
    AnswerRequest,
    AnswerResponse,
    ContextChunk,
    JudgeRequest,
    JudgeVerdict,
    LLMProvider,
)
from ragprobe.text_utils import content_tokens, split_sentences


class StubProvider(LLMProvider):
    """Deterministic extractive provider."""

    name = "stub"
    deterministic = True

    # ----------------------------------------------------------- answering

    def answer(self, request: AnswerRequest) -> AnswerResponse:
        cfg = request.config
        contexts = request.contexts

        # Refuse when retrieval came back empty or weak. This is the behaviour a
        # real RAG system should have and the golden set asserts on it.
        if not contexts or contexts[0].score < cfg.refusal_threshold:
            return AnswerResponse(
                text=REFUSAL_TEXT,
                refused=True,
                provider=self.name,
                model=None,
                metadata={
                    "reason": "no_context" if not contexts else "below_refusal_threshold",
                    "top_score": round(contexts[0].score, 6) if contexts else 0.0,
                },
            )

        selected = self._select_sentences(request.question, contexts, cfg.max_sentences)
        if not selected:
            return AnswerResponse(
                text=REFUSAL_TEXT,
                refused=True,
                provider=self.name,
                model=None,
                metadata={"reason": "no_overlapping_sentence"},
            )

        text = self._render(selected, cfg.prompt_version, cfg.include_citations)
        return AnswerResponse(
            text=text,
            refused=False,
            provider=self.name,
            model=None,
            metadata={
                "prompt_version": cfg.prompt_version,
                "sentences_used": len(selected),
                "cited_chunks": sorted({chunk_id for chunk_id, _, _, _ in selected}),
            },
        )

    @staticmethod
    def _select_sentences(
        question: str,
        contexts: Sequence[ContextChunk],
        max_sentences: int,
    ) -> List[Tuple[str, int, int, str]]:
        """Pick the best-matching sentences.

        Returns ``(chunk_id, chunk_rank, sentence_index, sentence)`` tuples in
        reading order. Scoring is question-token coverage, with the retrieval score
        as a mild prior so that a strong chunk wins ties against a weak one.
        """
        question_tokens = set(content_tokens(question))
        if not question_tokens:
            return []

        scored: List[Tuple[float, int, int, str, str]] = []
        for rank, context in enumerate(contexts):
            for index, sentence in enumerate(split_sentences(context.text)):
                tokens = set(content_tokens(sentence))
                if not tokens:
                    continue
                overlap = len(question_tokens & tokens) / len(question_tokens)
                if overlap <= 0.0:
                    continue
                # Retrieval score breaks ties toward the better-retrieved chunk
                # without being able to override a clearly better sentence.
                score = overlap + 0.05 * context.score
                scored.append((score, rank, index, context.chunk_id, sentence))

        if not scored:
            return []
        # Deterministic ordering: best score first, then chunk rank, then position.
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        chosen = scored[:max_sentences]
        # Re-sort into reading order so the answer is coherent.
        chosen.sort(key=lambda item: (item[1], item[2]))
        return [(chunk_id, rank, index, sentence) for _, rank, index, chunk_id, sentence in chosen]

    @staticmethod
    def _render(
        selected: Sequence[Tuple[str, int, int, str]],
        prompt_version: str,
        include_citations: bool,
    ) -> str:
        """Render the answer. ``prompt_version`` changes the output shape.

        This is the knob that makes the regression demo real: switching v1 -> v2
        changes citation placement and adds a preamble, which is exactly the kind of
        "harmless" prompt edit that quietly breaks a downstream citation parser.
        """
        if prompt_version == "v2":
            body = " ".join(sentence for _, _, _, sentence in selected)
            text = f"Based on the retrieved documentation, {body[0].lower()}{body[1:]}" if body else ""
            if include_citations:
                cited = []
                for chunk_id, _, _, _ in selected:
                    if chunk_id not in cited:
                        cited.append(chunk_id)
                text = f"{text} (Sources: {', '.join(f'[{cid}]' for cid in cited)})"
            return text

        # v1 (default): citation immediately after the sentence it supports.
        parts: List[str] = []
        previous_chunk: str | None = None
        for chunk_id, _, _, sentence in selected:
            if include_citations and chunk_id != previous_chunk:
                parts.append(f"{sentence} [{chunk_id}]")
            else:
                parts.append(sentence)
            previous_chunk = chunk_id
        return " ".join(parts)

    # ------------------------------------------------------------- judging

    def judge_faithfulness(self, request: JudgeRequest) -> JudgeVerdict:
        """Deterministic stand-in for an LLM judge.

        It delegates to the heuristic grounding scorer. Be clear about what this
        does and does not buy you: it exercises the judge *code path* offline and
        keeps CI green without a key, but it is not an independent opinion - it
        cannot catch a hallucination that the heuristic also misses. Set
        ``RAGPROBE_PROVIDER=anthropic`` for a genuinely independent judgement.
        """
        from ragprobe.evaluation.grounding import score_grounding

        context_text = "\n\n".join(item.text for item in request.contexts)
        result = score_grounding(request.answer, context_text)
        return JudgeVerdict(
            score=result.score,
            grounded=result.grounded,
            unsupported_claims=[claim.text for claim in result.unsupported_claims],
            rationale=(
                "stub judge: deterministic n-gram grounding heuristic "
                f"over {len(request.contexts)} retrieved chunk(s)"
            ),
            provider=self.name,
            deterministic=True,
        )
