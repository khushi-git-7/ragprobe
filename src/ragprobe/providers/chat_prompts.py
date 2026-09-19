"""Prompts and response parsing shared by every live chat-model provider.

Kept in one place so the Anthropic and OpenAI-compatible providers cannot drift:
a prompt change is a behaviour change and must apply to both.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

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


class ProviderRefusal(RuntimeError):
    """Raised when the model declines to respond."""


class JudgeParseError(ValueError):
    """Raised when the judge returns something that is not usable JSON."""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def looks_like_refusal(text: str) -> bool:
    from ragprobe.evaluation.evaluators import detect_refusal

    return detect_refusal(text)


def parse_judge_json(raw: str) -> Dict[str, Any]:
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
