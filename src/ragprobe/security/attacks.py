"""The attack corpus: schema, loading and rendering.

An attack is data, not code. Each one names *where* it enters the system (its
vector), *what* the attacker wants (its goal, which selects the oracle that scores
it) and *how* it tries (its technique). Payloads are templates; the placeholders
are filled per trial from :mod:`ragprobe.security.canary` so success is checkable.

Placeholders available in ``payload`` and ``cover``:

====================  =============================================================
``{marker_a}``        first half of the obedience marker
``{marker_b}``        second half (the oracle looks for the two joined)
``{attacker_email}``  an address on the attacker's domain
``{attacker_url}``    a URL on the attacker's domain, ending in ``?d=`` for data
====================  =============================================================

Mapping each attack to the OWASP Top 10 for LLM Applications (2025) keeps the
results legible to a security reviewer: ``LLM01`` prompt injection, ``LLM02``
sensitive information disclosure, ``LLM06`` excessive agency, ``LLM07`` system
prompt leakage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ragprobe.errors import RagprobeError
from ragprobe.security.canary import Canaries

ATTACKER_DOMAIN = "exfil-collector.example"
ATTACKER_EMAIL = f"archive@{ATTACKER_DOMAIN}"
ATTACKER_URL = f"https://{ATTACKER_DOMAIN}/pixel.png?d="

#: Where the attack text enters the system.
VECTORS = {
    "user": "typed by the user (direct prompt injection)",
    "document": "inside a retrieved document (indirect prompt injection)",
    "tool": "inside a tool result the agent reads (agent hijacking)",
}

#: What the attacker wants. Each goal has exactly one oracle in ``oracles.py``.
GOALS = {
    "say_marker": "make the model emit an attacker-chosen token (proof of control)",
    "leak_secret": "make the model reveal the secret in its system prompt or data",
    "exfil_link": "make the model render a link that ships the secret to the attacker",
    "send_email": "make the agent email private data to the attacker",
}

#: Which scenario each vector runs in.
SCENARIO_FOR_VECTOR = {"user": "chat", "document": "rag", "tool": "agent"}

OWASP = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM05": "Improper Output Handling",
    "LLM06": "Excessive Agency",
    "LLM07": "System Prompt Leakage",
    "LLM08": "Vector and Embedding Weaknesses",
    "LLM09": "Misinformation",
    "LLM10": "Unbounded Consumption",
}


class AttackError(RagprobeError, ValueError):
    """The attack file is malformed."""


@dataclass(frozen=True)
class Attack:
    id: str
    vector: str
    goal: str
    technique: str
    payload: str
    owasp: str = "LLM01"
    language: str = "en"
    description: str = ""
    #: rag/agent only: the user's (benign) request that makes the poison reachable.
    question: str = ""
    #: rag only: ordinary text around the payload so the document looks real and
    #: is retrieved for ``question``. Retrieval exposure is part of the result.
    cover: str = ""
    #: rag/agent only: words the legitimate answer to ``question`` contains (any
    #: one matches). Scores *utility under attack*: a defence that stops the attack
    #: by also breaking the user's task has not really won.
    expect: tuple = field(default_factory=tuple)
    tags: tuple = field(default_factory=tuple)

    @property
    def scenario(self) -> str:
        return SCENARIO_FOR_VECTOR[self.vector]

    def render(self, text: str, canaries: Canaries) -> str:
        return text.format(
            marker_a=canaries.marker_a,
            marker_b=canaries.marker_b,
            attacker_email=ATTACKER_EMAIL,
            attacker_url=ATTACKER_URL,
        )

    def rendered_payload(self, canaries: Canaries) -> str:
        return self.render(self.payload, canaries)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        data["expect"] = list(self.expect)
        return data


def _attack_from_mapping(raw: Mapping[str, Any], where: str) -> Attack:
    known = set(Attack.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise AttackError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    for key in ("id", "vector", "goal", "technique", "payload"):
        if not raw.get(key):
            raise AttackError(f"{where}: missing {key!r}")
    data = dict(raw)
    data["tags"] = tuple(data.get("tags") or ())
    data["expect"] = tuple(str(word) for word in (data.get("expect") or ()))
    attack = Attack(**data)
    if attack.vector not in VECTORS:
        raise AttackError(f"{where}: vector must be one of {', '.join(VECTORS)}")
    if attack.goal not in GOALS:
        raise AttackError(f"{where}: goal must be one of {', '.join(GOALS)}")
    if attack.owasp not in OWASP:
        raise AttackError(f"{where}: owasp must be one of {', '.join(OWASP)}")
    if attack.vector in ("document", "tool") and not attack.question:
        raise AttackError(f"{where}: {attack.vector} attacks need the user's 'question'")
    if attack.goal == "say_marker" and not (
        "{marker_a}" in attack.payload and "{marker_b}" in attack.payload
    ):
        raise AttackError(f"{where}: say_marker payloads must use {{marker_a}} and {{marker_b}}")
    if attack.goal == "send_email" and attack.vector != "tool":
        raise AttackError(f"{where}: send_email needs an agent, so vector must be 'tool'")
    # Fail now, not mid-run, on a stray brace.
    try:
        from ragprobe.security.canary import make_canaries

        attack.rendered_payload(make_canaries(0, attack.id, 0))
        attack.render(attack.cover, make_canaries(0, attack.id, 0))
    except (KeyError, IndexError, ValueError) as exc:
        raise AttackError(f"{where}: bad placeholder in payload or cover: {exc}") from exc
    return attack


def load_attacks(path: Path) -> List[Attack]:
    import yaml

    path = Path(path)
    if not path.is_file():
        raise AttackError(f"attack file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = raw.get("attacks") if isinstance(raw, Mapping) else None
    if not isinstance(items, list) or not items:
        raise AttackError(f"{path}: expected a non-empty 'attacks' list")
    attacks: List[Attack] = []
    seen = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise AttackError(f"{path}: attack #{index + 1} is not a mapping")
        attack = _attack_from_mapping(item, f"{path}: attack #{index + 1}")
        if attack.id in seen:
            raise AttackError(f"{path}: duplicate attack id {attack.id!r}")
        seen.add(attack.id)
        attacks.append(attack)
    return attacks


def select(
    attacks: Sequence[Attack],
    vectors: Optional[Sequence[str]] = None,
    goals: Optional[Sequence[str]] = None,
    ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> List[Attack]:
    chosen = [
        attack for attack in attacks
        if (not vectors or attack.vector in vectors)
        and (not goals or attack.goal in goals)
        and (not ids or attack.id in ids)
    ]
    return chosen[:limit] if limit else chosen


def corpus_fingerprint(attacks: Sequence[Attack]) -> str:
    payload = json.dumps([a.to_dict() for a in attacks], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
