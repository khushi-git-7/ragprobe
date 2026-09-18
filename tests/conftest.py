"""Shared fixtures.

``PROJECT_ROOT`` points at the repository root so tests can run the real corpus and
the real golden set. Testing against the shipped data - rather than only against
toy fixtures - is deliberate: it means the suite fails if someone edits a sample
document in a way that breaks the dataset's expected chunk IDs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ragprobe.config import ProbeConfig  # noqa: E402
from ragprobe.pipeline.rag import RagPipeline  # noqa: E402


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def config(project_root: Path) -> ProbeConfig:
    return ProbeConfig.from_yaml(project_root / "ragprobe.yaml")


@pytest.fixture(scope="session")
def pipeline(config: ProbeConfig, project_root: Path) -> RagPipeline:
    """Session-scoped: ingesting the corpus once keeps the suite fast."""
    return RagPipeline(config, base_dir=project_root).ingest()
