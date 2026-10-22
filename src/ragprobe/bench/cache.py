"""An on-disk response cache so a benchmark rerun is free and exact.

Live models cost tokens and time, and they are nondeterministic: run the same
attack twice and the wording differs. For a *benchmark* that is a problem - a
reported number must be reproducible. :class:`CachingVictim` wraps any victim and
remembers each model reply, keyed by everything that could change it (the victim,
the model, the sampling settings, the exact messages and tools). A rerun with the
same inputs replays the stored replies: no network, no cost, identical results.

The cache is plain JSON files in a directory, one per key, so it is inspectable,
diff-free of secrets (only prompts and replies), and safe to commit for a frozen
run or to delete to force a refresh.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ragprobe.security.victims import Message, Reply, ToolCall, Victim


def _reply_to_dict(reply: Reply) -> Dict[str, Any]:
    return {"content": reply.content,
            "tool_calls": [tc.to_dict() for tc in reply.tool_calls],
            "finish_reason": reply.finish_reason,
            "output_tokens": reply.output_tokens}


def _reply_from_dict(data: Dict[str, Any]) -> Reply:
    return Reply(
        content=data.get("content", ""),
        tool_calls=[ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                    for tc in data.get("tool_calls", [])],
        finish_reason=data.get("finish_reason"),
        output_tokens=int(data.get("output_tokens", 0)))


class CachingVictim(Victim):
    """Wrap a victim so identical requests replay a stored reply instead of recomputing."""

    def __init__(self, inner: Victim, cache_dir: Optional[Path] = None) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.deterministic = inner.deterministic
        # With no directory this is a pure counter: nothing is stored, but replies are
        # still tallied (including cut-off ones) so a run can report them.
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0
        #: replies the model cut off at its token limit (finish_reason "length"). A
        #: reasoning model can spend its whole budget thinking and return nothing; that
        #: reads as "no attack succeeded" unless it is counted and reported.
        self.truncated = 0

    def _key(self, messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> str:
        payload = json.dumps({
            "name": self.name, "model": self.model,
            "temperature": getattr(self.inner, "temperature", None),
            "max_tokens": getattr(self.inner, "max_tokens", None),
            "messages": messages, "tools": tools,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def respond(self, messages: List[Message], tools: Optional[List[Dict[str, Any]]] = None) -> Reply:
        path = None
        if self.cache_dir is not None:
            path = self.cache_dir / f"{self._key(messages, tools)}.json"
            if path.is_file():
                try:
                    reply = _reply_from_dict(json.loads(path.read_text(encoding="utf-8")))
                except (ValueError, KeyError):
                    reply = None  # a corrupt entry: fall through and recompute
                if reply is not None:
                    self.hits += 1
                    self._note(reply)
                    return reply
        reply = self.inner.respond(messages, tools)
        self.misses += 1
        self._note(reply)
        if path is not None:
            path.write_text(json.dumps(_reply_to_dict(reply), ensure_ascii=False, sort_keys=True),
                            encoding="utf-8")
        return reply

    def _note(self, reply: Reply) -> None:
        if reply.finish_reason == "length":
            self.truncated += 1

    def stats(self) -> Dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
