"""Configuration objects for RAGProbe.

Every knob that can change pipeline behaviour lives here, and the whole config is
hashed into a ``fingerprint`` that is written into every results file. That is the
mechanism that makes the regression diff trustworthy: if someone compares two runs
that used different chunk sizes or a different prompt version, the diff report says
so instead of silently attributing the delta to the change under test.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

DEFAULT_CONFIG_FILENAME = "ragprobe.yaml"


class ConfigError(ValueError):
    """Raised when a config file contains unknown or invalid keys."""


def _build(cls, data: Mapping[str, Any], path: str):
    """Construct a dataclass from a mapping, rejecting unknown keys.

    Silently ignoring an unknown key is how a typo'd ``top_k`` ends up costing an
    afternoon, so this is strict on purpose.
    """
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(
            f"unknown key(s) in '{path}': {', '.join(sorted(unknown))}. "
            f"Valid keys: {', '.join(sorted(known))}"
        )
    return cls(**dict(data))


@dataclass
class ChunkConfig:
    """How documents are split into retrievable units."""

    strategy: str = "heading"  # "heading" | "fixed"
    max_words: int = 180
    overlap_words: int = 30
    min_words: int = 5

    def validate(self) -> None:
        if self.strategy not in {"heading", "fixed"}:
            raise ConfigError(f"chunk.strategy must be 'heading' or 'fixed', got {self.strategy!r}")
        if self.max_words <= 0:
            raise ConfigError("chunk.max_words must be > 0")
        if self.overlap_words < 0 or self.overlap_words >= self.max_words:
            raise ConfigError("chunk.overlap_words must be >= 0 and < chunk.max_words")


@dataclass
class RetrievalConfig:
    """Embedding + search behaviour."""

    embedder: str = "tfidf"  # "tfidf" | "fastembed" | "sentence-transformers"
    dim: int = 512
    top_k: int = 3
    min_score: float = 0.0
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"

    def validate(self) -> None:
        if self.top_k <= 0:
            raise ConfigError("retrieval.top_k must be > 0")
        if self.dim <= 8:
            raise ConfigError("retrieval.dim must be > 8")


@dataclass
class GenerationConfig:
    """Answer-synthesis behaviour.

    ``prompt_version`` exists so a prompt edit shows up in the config fingerprint.
    A prompt change is a code change; it should be versioned like one.
    """

    provider: str = "stub"  # "stub" | "anthropic"
    model: str = "claude-opus-5"
    prompt_version: str = "v1"
    max_sentences: int = 2
    include_citations: bool = True
    refusal_threshold: float = 0.10
    max_tokens: int = 1024

    def validate(self) -> None:
        if self.provider not in {"stub", "anthropic"}:
            raise ConfigError(f"generation.provider must be 'stub' or 'anthropic', got {self.provider!r}")
        if self.max_sentences <= 0:
            raise ConfigError("generation.max_sentences must be > 0")


@dataclass
class EvaluationConfig:
    """Thresholds for the answer-quality evaluators."""

    fuzzy_threshold: float = 0.60
    grounding_threshold: float = 0.55
    claim_support_threshold: float = 0.50
    judge_enabled: bool = True
    # Checks whose failure fails the case. Everything else is reported but advisory.
    required_checks: tuple = (
        "keyword_presence",
        "forbidden_absent",
        "refusal_behaviour",
        "citation_present",
        "grounding",
    )

    def validate(self) -> None:
        for name, value in (
            ("fuzzy_threshold", self.fuzzy_threshold),
            ("grounding_threshold", self.grounding_threshold),
            ("claim_support_threshold", self.claim_support_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ConfigError(f"evaluation.{name} must be between 0 and 1")


@dataclass
class TargetConfig:
    """What system is under test.

    ``builtin`` is RAGProbe's own reference pipeline. ``http`` and ``python`` point the
    harness at *your* RAG - a service behind an endpoint, or a Python callable - so the
    same golden set, evaluators and regression gate apply to the thing you actually
    ship. Header values may reference environment variables (``Bearer ${RAG_TOKEN}``);
    they are expanded at request time and stored unexpanded, so a results file never
    contains a secret.
    """

    kind: str = "builtin"  # "builtin" | "http" | "python"
    url: str = ""  # http: endpoint that answers a question
    entry: str = ""  # python: "package.module:callable" or "package.module:Class"
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 60.0
    question_field: str = "question"  # request body key carrying the question
    answer_field: str = "answer"  # dotted path into the response
    contexts_field: str = "contexts"  # dotted path to the retrieved chunks
    refused_field: str = "refused"  # optional dotted path to a refusal flag
    extra_body: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.kind not in {"builtin", "http", "python"}:
            raise ConfigError(
                f"target.kind must be 'builtin', 'http' or 'python', got {self.kind!r}"
            )
        if self.kind == "http" and not self.url:
            raise ConfigError("target.url is required when target.kind is 'http'")
        if self.kind == "python" and ":" not in self.entry:
            raise ConfigError(
                "target.entry must look like 'package.module:callable' when target.kind is 'python'"
            )
        if self.method.upper() not in {"POST", "GET"}:
            raise ConfigError(f"target.method must be POST or GET, got {self.method!r}")
        if self.timeout <= 0:
            raise ConfigError("target.timeout must be > 0")


@dataclass
class ProbeConfig:
    """Top-level configuration."""

    corpus_dir: str = "datasets/docs"
    dataset_path: str = "datasets/golden_set.yaml"
    chunk: ChunkConfig = field(default_factory=ChunkConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    target: TargetConfig = field(default_factory=TargetConfig)

    # ---------------------------------------------------------------- loading

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]], source: str = "<dict>") -> "ProbeConfig":
        data = dict(data or {})
        sections = {
            "chunk": ChunkConfig,
            "retrieval": RetrievalConfig,
            "generation": GenerationConfig,
            "evaluation": EvaluationConfig,
            "target": TargetConfig,
        }
        kwargs: Dict[str, Any] = {}
        for key, sub_cls in sections.items():
            kwargs[key] = _build(sub_cls, data.pop(key, {}) or {}, f"{source}:{key}")
        for scalar in ("corpus_dir", "dataset_path"):
            if scalar in data:
                kwargs[scalar] = str(data.pop(scalar))
        if data:
            raise ConfigError(
                f"unknown top-level key(s) in '{source}': {', '.join(sorted(data))}"
            )
        cfg = cls(**kwargs)
        cfg.validate()
        return cfg

    @classmethod
    def from_yaml(cls, path: Path) -> "ProbeConfig":
        import yaml  # imported lazily so `--help` works without PyYAML

        path = Path(path)
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not isinstance(raw, Mapping):
            raise ConfigError(f"config file must contain a mapping at the top level: {path}")
        return cls.from_dict(raw, source=str(path))

    @classmethod
    def load(cls, path: Optional[Path]) -> "ProbeConfig":
        """Load from an explicit path, else the default file, else built-in defaults."""
        if path is not None:
            return cls.from_yaml(Path(path))
        default = Path(DEFAULT_CONFIG_FILENAME)
        if default.exists():
            return cls.from_yaml(default)
        return cls()

    # ------------------------------------------------------------- behaviour

    def validate(self) -> None:
        self.chunk.validate()
        self.retrieval.validate()
        self.generation.validate()
        self.evaluation.validate()
        self.target.validate()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # tuples round-trip through JSON as lists; normalise now so the fingerprint
        # of a loaded config matches the fingerprint of an in-memory one.
        data["evaluation"]["required_checks"] = list(self.evaluation.required_checks)
        return data

    def fingerprint(self) -> str:
        """Stable short hash of every behaviour-affecting setting."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def apply_overrides(self, overrides: Mapping[str, Any]) -> "ProbeConfig":
        """Return a copy with dotted-path overrides applied (e.g. ``retrieval.top_k``)."""
        data = self.to_dict()
        for dotted, value in overrides.items():
            if value is None:
                continue
            parts = dotted.split(".")
            node: Any = data
            for part in parts[:-1]:
                if part not in node:
                    raise ConfigError(f"unknown config section in override: {dotted}")
                node = node[part]
            if parts[-1] not in node:
                raise ConfigError(f"unknown config key in override: {dotted}")
            node[parts[-1]] = value
        return ProbeConfig.from_dict(data, source="<overrides>")
