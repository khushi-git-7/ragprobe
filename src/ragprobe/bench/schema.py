"""The Bench item schema, its vocabulary, and conversion to a runnable Attack.

A Bench item is plain data (a JSON object). This module defines what fields it
has, which values are allowed, how to validate one, and how to turn a verifiable
``attack`` item into the security suite's :class:`~ragprobe.security.attacks.Attack`
so the benchmark actually runs rather than just being described.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from ragprobe.security.attacks import (
    GOALS,
    OWASP,
    VECTORS,
    Attack,
    AttackError,
    _attack_from_mapping,
)

#: Attack techniques (the "how"). A small, documented vocabulary keeps tags
#: consistent across hand-written, generated and imported items.
TECHNIQUES = {
    "instruction-override": "plainly tells the model to ignore its instructions",
    "persona-switch": "role-play framing that grants a rule-free persona",
    "fake-authority": "impersonates a system or developer message",
    "refusal-suppression": "forbids refusing or apologising, forces a lead token",
    "payload-splitting": "splits the instruction so no single span looks malicious",
    "encoding-evasion": "hides the ask or answer behind base64/hex/reversed text",
    "many-shot": "primes compliance with a run of obedient examples",
    "obfuscation": "leetspeak / unicode noise to slip past keyword filters",
    "indirect": "payload arrives inside retrieved content or a tool result",
    "direct-request": "simply asks for the secret, no evasion",
    "task-deflection": "hides the ask as a sub-task of a benign request",
    "external": "technique as labelled by an imported dataset (unmapped)",
}

#: Seed-corpus technique names that collapse into the shared vocabulary above.
SEED_TECHNIQUE_MAP = {
    "indirect-action": "indirect", "indirect-exfil": "indirect",
    "indirect-instruction": "indirect", "indirect-leak": "indirect",
    "zero-click-exfil": "indirect",
}

LANGUAGES = {"en": "English", "de": "German", "es": "Spanish", "fr": "French",
             "other": "other / mixed"}

SOURCES = {
    "ragprobe-seed": ("RAGProbe", "MIT"),
    "ragprobe-generated": ("RAGProbe", "MIT"),
    "deepset": ("deepset/prompt-injections", "Apache-2.0"),
    "garak": ("NVIDIA/garak", "Apache-2.0"),
    "pyrit": ("Azure/PyRIT", "MIT"),
}

LICENCES = {"MIT", "Apache-2.0", "CC-BY-4.0", "CC0-1.0", "unknown"}
SPLITS = {"train", "dev", "test"}
KINDS = {"attack", "probe"}


class BenchError(ValueError):
    """A Bench item or dataset is malformed."""


@dataclass
class BenchItem:
    """One row of the benchmark. ``kind`` decides which fields are required."""

    id: str
    kind: str                 # "attack" | "probe"
    owasp: str                # LLM01 ...
    technique: str
    language: str
    source: str
    licence: str
    split: str
    # --- attack (verifiable) fields -------------------------------------
    vector: str = ""          # user | document | tool
    goal: str = ""            # say_marker | leak_secret | exfil_link | send_email
    payload: str = ""
    question: str = ""
    cover: str = ""
    description: str = ""
    expect: Tuple[str, ...] = field(default_factory=tuple)
    # --- probe (detection) fields ---------------------------------------
    text: str = ""
    label: Optional[int] = None   # 1 = injection, 0 = benign

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["expect"] = list(self.expect)
        return d

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BenchItem":
        known = set(cls.__dataclass_fields__)
        data = {k: raw[k] for k in raw if k in known}
        data["expect"] = tuple(raw.get("expect") or ())
        return cls(**data)


def validate(item: BenchItem) -> None:
    """Raise :class:`BenchError` if ``item`` is not a well-formed row."""
    if not item.id:
        raise BenchError("item has no id")
    where = f"item {item.id!r}"
    if item.kind not in KINDS:
        raise BenchError(f"{where}: kind must be one of {sorted(KINDS)}")
    if item.owasp not in OWASP:
        raise BenchError(f"{where}: owasp must be one of {sorted(OWASP)}")
    if item.technique not in TECHNIQUES:
        raise BenchError(f"{where}: unknown technique {item.technique!r}")
    if item.language not in LANGUAGES:
        raise BenchError(f"{where}: unknown language {item.language!r}")
    if item.source not in SOURCES:
        raise BenchError(f"{where}: unknown source {item.source!r}")
    if item.licence not in LICENCES:
        raise BenchError(f"{where}: unknown licence {item.licence!r}")
    if item.split not in SPLITS:
        raise BenchError(f"{where}: split must be one of {sorted(SPLITS)}")
    if item.kind == "attack":
        if item.vector not in VECTORS:
            raise BenchError(f"{where}: attack vector must be one of {sorted(VECTORS)}")
        if item.goal not in GOALS:
            raise BenchError(f"{where}: attack goal must be one of {sorted(GOALS)}")
        if not item.payload:
            raise BenchError(f"{where}: attack has no payload")
        # it must convert to a real Attack (this runs the suite's own checks)
        to_attack(item)
    else:
        if item.label not in (0, 1):
            raise BenchError(f"{where}: probe label must be 0 or 1")
        if not item.text:
            raise BenchError(f"{where}: probe has no text")


def to_attack(item: BenchItem) -> Attack:
    """Build the security suite's ``Attack`` from a verifiable ``attack`` item.

    Bench-only metadata (source, licence, split, language) is preserved in the
    Attack's ``tags`` so a run can trace every result back to its catalogue row.
    Raises :class:`BenchError` on an item the suite would reject.
    """
    if item.kind != "attack":
        raise BenchError(f"item {item.id!r}: only 'attack' items convert to an Attack")
    mapping = {
        "id": item.id, "vector": item.vector, "goal": item.goal,
        "technique": item.technique, "payload": item.payload, "owasp": item.owasp,
        "language": item.language, "description": item.description,
        "question": item.question, "cover": item.cover, "expect": list(item.expect),
        "tags": [f"source:{item.source}", f"licence:{item.licence}", f"split:{item.split}"],
    }
    try:
        # the suite's own validator: enums, required fields, marker presence and
        # a dry placeholder render - so a bad generated attack fails here, not mid-run
        return _attack_from_mapping(mapping, f"bench item {item.id!r}")
    except AttackError as exc:
        raise BenchError(str(exc)) from exc


def assign_split(item_id: str, dev: float = 0.15, test: float = 0.25) -> str:
    """Deterministically map an id to train/dev/test by hashing it.

    Hashing the id (not a random shuffle) means the split is stable across
    rebuilds and reproducible on any machine: the same attack always lands in the
    same split, so test results are never quietly contaminated by a reshuffle.
    """
    h = int(hashlib.sha256(item_id.encode("utf-8")).hexdigest(), 16)
    frac = (h % 10_000) / 10_000.0
    if frac < test:
        return "test"
    if frac < test + dev:
        return "dev"
    return "train"
