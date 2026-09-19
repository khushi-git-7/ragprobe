"""Systems under test: the built-in pipeline, an HTTP service, or a Python callable."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from ragprobe.config import ProbeConfig
from ragprobe.targets.base import Target, TargetError, normalise_chunks, result_from_payload


def parse_target_spec(spec: str) -> Dict[str, str]:
    """Turn a ``--target`` value into a ``target`` config block.

    ``http://...`` / ``https://...`` selects the HTTP adapter, ``module:name`` the
    Python adapter, and ``builtin`` the reference pipeline.
    """
    value = spec.strip()
    if value in ("", "builtin"):
        return {"kind": "builtin"}
    if value.startswith("http://") or value.startswith("https://"):
        return {"kind": "http", "url": value}
    if ":" in value and "/" not in value and "\\" not in value:
        return {"kind": "python", "entry": value}
    raise TargetError(
        f"cannot tell what {spec!r} is; use a URL, 'package.module:name' or 'builtin'"
    )


def get_target(config: ProbeConfig, base_dir: Optional[Path] = None) -> Target:
    """Instantiate the configured system under test (not yet ingested)."""
    kind = config.target.kind
    if kind == "builtin":
        from ragprobe.pipeline.rag import RagPipeline

        return RagPipeline(config, base_dir=base_dir)
    if kind == "http":
        from ragprobe.targets.http_target import HttpTarget

        return HttpTarget(config)
    if kind == "python":
        from ragprobe.targets.python_target import PythonTarget

        return PythonTarget(config, base_dir=base_dir)
    raise TargetError(f"unknown target kind {kind!r}")


__all__ = [
    "Target",
    "TargetError",
    "get_target",
    "normalise_chunks",
    "parse_target_spec",
    "result_from_payload",
]
