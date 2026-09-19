"""Evaluate a RAG pipeline that lives in your own Python code.

``target.entry`` is ``package.module:name``. ``name`` may be:

* a function ``(question: str) -> str | dict | RagResult``
* a class or factory; it is called with no arguments and the instance's ``answer``
  (or ``query``, ``ask``, ``run``, ``__call__``) method is used. An ``ingest`` or
  ``setup`` method, if present, runs once before the suite.

Return shapes follow the HTTP contract: a string is an answer with no retrieval, a
mapping carries ``answer`` / ``contexts`` / ``refused``, and a ``RagResult`` is used
as-is. That is enough to wrap a LangChain chain or a LlamaIndex query engine in a
few lines - see ``examples/`` for both.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ragprobe.config import ProbeConfig
from ragprobe.pipeline.rag import RagResult
from ragprobe.providers import get_provider
from ragprobe.targets.base import Target, TargetError, result_from_payload

ANSWER_METHODS = ("answer", "query", "ask", "run", "__call__")
SETUP_METHODS = ("ingest", "setup", "prepare")


def load_entry(entry: str, base_dir: Optional[Path] = None) -> Any:
    """Import ``package.module:name``.

    ``base_dir`` is put on ``sys.path`` so a project-local module works without
    packaging it first.
    """
    module_name, _, attr = entry.partition(":")
    if not module_name or not attr:
        raise TargetError(f"target.entry must be 'package.module:name', got {entry!r}")
    if base_dir is not None:
        root = str(Path(base_dir).resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise TargetError(f"cannot import {module_name!r}: {exc}") from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise TargetError(f"{module_name!r} has no attribute {attr!r}") from exc


def _resolve(obj: Any) -> Callable[[str], Any]:
    """Turn whatever the entry point names into a ``question -> payload`` callable."""
    # A plain function or lambda answers directly.
    if inspect.isfunction(obj) or inspect.isbuiltin(obj):
        return obj
    # A class or factory: instantiate, run the optional setup hook once, then pick
    # the conventional answer method.
    instance = obj() if inspect.isclass(obj) or (callable(obj) and not hasattr(obj, "answer")) else obj
    for name in SETUP_METHODS:
        hook = getattr(instance, name, None)
        if callable(hook):
            hook()
            break
    for name in ANSWER_METHODS:
        method = getattr(instance, name, None)
        if callable(method):
            return method
    raise TargetError(
        f"{type(instance).__name__} has none of the methods {', '.join(ANSWER_METHODS)}"
    )


class PythonTarget(Target):
    kind = "python"

    def __init__(self, config: ProbeConfig, base_dir: Optional[Path] = None) -> None:
        self.config = config
        self.target = config.target
        self.base_dir = base_dir
        self.provider = get_provider(config.generation)
        self._callable: Optional[Callable[[str], Any]] = None

    def ingest(self) -> "PythonTarget":
        self._callable = _resolve(load_entry(self.target.entry, self.base_dir))
        return self

    def answer(self, question: str) -> RagResult:
        if self._callable is None:
            self.ingest()
        assert self._callable is not None
        try:
            payload = self._callable(question)
        except Exception as exc:  # noqa: BLE001 - surfaced per case by the runner
            raise TargetError(f"{self.target.entry} raised {type(exc).__name__}: {exc}") from exc
        return result_from_payload(
            question,
            payload,
            answer_field=self.target.answer_field,
            contexts_field=self.target.contexts_field,
            refused_field=self.target.refused_field,
            provider="python",
        )

    def stats(self) -> Dict[str, Any]:
        return {
            "target": "python",
            "entry": self.target.entry,
            "judge_provider": self.provider.name,
        }
