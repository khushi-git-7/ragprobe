"""Evaluate a RAG service behind an HTTP endpoint.

Request (POST, JSON)::

    {"question": "<the golden-set question>", ...extra_body}

Response - any JSON object; the field names are configurable and default to::

    {"answer": "...", "contexts": [{"id": "doc#section", "text": "...", "score": 0.81}], "refused": false}

Only ``answer`` is mandatory. Without ``contexts`` the answer-quality checks still
run, but retrieval metrics are empty - so return the chunks if you can, with the
stable ids your golden set names in ``expected_chunks``.

Uses only the standard library so a service can be gated in CI with nothing but
``pip install ragprobe``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict

from ragprobe.config import ProbeConfig
from ragprobe.pipeline.rag import RagResult
from ragprobe.providers import get_provider
from ragprobe.targets.base import Target, TargetError, result_from_payload


class HttpTarget(Target):
    kind = "http"

    def __init__(self, config: ProbeConfig) -> None:
        self.config = config
        self.target = config.target
        self.provider = get_provider(config.generation)

    # Header values are expanded on every call, never at load time, so the value
    # that lands in results/baseline files is the ``${VAR}`` placeholder.
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        for key, value in self.target.headers.items():
            headers[str(key)] = os.path.expandvars(str(value))
        return headers

    def _request(self, question: str) -> urllib.request.Request:
        body: Dict[str, Any] = dict(self.target.extra_body)
        body[self.target.question_field] = question
        if self.target.method.upper() == "GET":
            query = urllib.parse.urlencode({k: str(v) for k, v in body.items()})
            joiner = "&" if "?" in self.target.url else "?"
            return urllib.request.Request(
                self.target.url + joiner + query, headers=self._headers(), method="GET"
            )
        return urllib.request.Request(
            self.target.url,
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )

    def answer(self, question: str) -> RagResult:
        request = self._request(question)
        try:
            with urllib.request.urlopen(request, timeout=self.target.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise TargetError(f"{self.target.url} returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TargetError(f"could not reach {self.target.url}: {exc.reason}") from exc
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise TargetError(f"{self.target.url} did not return JSON: {raw[:200]!r}") from exc
        return result_from_payload(
            question,
            payload,
            answer_field=self.target.answer_field,
            contexts_field=self.target.contexts_field,
            refused_field=self.target.refused_field,
            provider="http",
        )

    def stats(self) -> Dict[str, Any]:
        return {
            "target": "http",
            "url": self.target.url,
            "method": self.target.method.upper(),
            "judge_provider": self.provider.name,
        }
