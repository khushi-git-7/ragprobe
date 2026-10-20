"""Prompt-injection detectors.

Two interchangeable detectors sit behind one interface:

``heuristic``
    Weighted pattern rules, standard library only, microseconds per text. Each rule
    targets one *mechanism* attackers rely on (overriding prior instructions, role
    hijack, fake delimiters, addressing the AI from inside data, exfiltration
    syntax...), in English and the European languages the attack corpus uses. The
    score is the sum of the weights of the distinct rules that fire; the threshold
    was chosen on the deepset/prompt-injections *train* split only.

``protectai``
    ProtectAI's open DeBERTa-v3 classifier (Apache-2.0,
    ``protectai/deberta-v3-base-prompt-injection-v2``), a fine-tuned transformer.
    Optional - it needs ``transformers`` and ``torch`` - so it runs in CI or on a
    free notebook GPU, never as a requirement of the base install.

Comparing them on the same held-out data is the point: the rules are explainable
and free to run on every request, the model is stronger on paraphrase; the
benchmark says by how much, with confidence intervals, instead of assuming.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Pattern, Sequence, Tuple

I = re.IGNORECASE


@dataclass(frozen=True)
class Rule:
    name: str
    weight: float
    pattern: Pattern[str]


@dataclass
class Verdict:
    flagged: bool
    score: float
    rules: List[str] = field(default_factory=list)


def _r(name: str, weight: float, pattern: str, flags: int = I) -> Rule:
    return Rule(name, weight, re.compile(pattern, flags))


# Ordered by how directly the rule identifies an attack. Weights reflect how often
# the pattern appears in *benign* text (the train split's label-0 rows and the
# hard-negative benign set): a phrase ordinary users say gets a low weight.
RULES: Tuple[Rule, ...] = (
    # --- overriding what came before -------------------------------------------
    _r("override", 3.0,
       r"\b(ignore|disregard|forget|overlook|bypass|override|discard)\b[^.\n]{0,40}?"
       r"\b(previous|prior|above|earlier|preceding|foregoing|all|any|every|your|the|those|these)\b"
       r"[^.\n]{0,25}?\b(instructions?|rules?|directions?|guidelines?|orders?|prompts?|"
       r"context|commands?|constraints?|tasks?|information|text|content|messages?)\b"),
    _r("forget_everything", 3.0, r"\bforget\s+(about\s+)?(everything|all|what|anything)\b"),
    _r("override_de", 3.0,
       r"\b(ignorier\w*|vergiss|vergessen\s+sie|missachte\w*|vernachlässig\w*)\b"),
    _r("override_de_prior", 2.5,
       r"\b(alle|die)\s+(bisherigen|vorherigen|vorangegangenen|obigen)\s+"
       r"(informationen|anweisungen|angaben|aufgaben|befehle|instruktionen)"),
    _r("override_romance", 3.0,
       r"\b(ignora|ignore[zr]?|olvida|oublie[zr]?|dimentica|esquece|esqueça|desconsidera)\b"
       r"[^.\n]{0,40}?\b(instrucciones|instructions|istruzioni|instruções|consignes|"
       r"indicaciones|regole|reglas|règles|regras)\b"),
    _r("new_instructions", 2.0,
       r"\b(new|updated|revised|real|actual|following)\s+(instructions?|task|rules?|directives?|orders?)\s*[:!]"
       r"|\bneue\s+(aufgabe|anweisung|anweisungen)\b|\bchange your instructions\b"
       r"|\bnouvelles? instructions?\b|\bnuevas? instrucci"),
    _r("stop_command", 1.5, r"(^|[\s\"'.])(stop|stopp|halt)\b\s*[-:!,]", I),
    # --- role hijack ------------------------------------------------------------
    _r("role_hijack", 2.0,
       r"\b(you are now|you're now|from now on,?\s+you|act as (a|an|my|the)\b|pretend (to be|you|that you)"
       r"|imagine (that )?you are|roleplay|role-play|stell dir vor|tu so,? als|du bist (jetzt|nun|ab jetzt)"
       r"|ab (jetzt|sofort) bist du|haz como si|fais comme si|sei ora|agora você é)"),
    _r("jailbreak_persona", 3.0,
       r"\b(DAN|do anything now|developer mode|jailbreak|jailbroken|unfiltered|no restrictions|"
       r"without (any )?(restrictions|filters|limits))\b"),
    # --- probing the system prompt ---------------------------------------------
    _r("prompt_probe", 2.0,
       r"\b(system prompt|initial prompt|hidden prompt|your (instructions|prompt|rules|guidelines|configuration|directives)"
       r"|(the|all) (text|words|instructions|content) (above|before)|everything (above|before)"
       r"|repeat (the|your|everything|all)|print (your|the) (prompt|instructions|rules)"
       r"|verbatim|deine (anweisungen|instruktionen)|tus instrucciones|vos instructions)\b"),
    _r("secret_seek", 1.0,
       r"\b(password|passwort|secret|access code|api key|credentials?|override code|admin code|"
       r"confidential|contraseña|mot de passe)\b"),
    # --- structure forgery --------------------------------------------------------
    _r("fake_delimiter", 2.0,
       r"(</?\s*(system|instructions?|context|document|untrusted\w*|user|assistant)\s*>"
       r"|\[/?INST\]|<\|im_(start|end)\|>|<\|(system|user|assistant)\|>"
       r"|#{2,}\s*(system|instructions?|new|admin)|\bEND OF (THE )?(DOCUMENT|CONTEXT|INPUT|TEXT|EMAIL)\b"
       r"|\b(system|admin|developer)\s*(message|override|note)\s*:)"),
    _r("addressed_to_ai", 2.0,
       r"\b(ai assistant|ai model|language model|if you are an? (ai|assistant|llm|language model)"
       r"|note to (the )?(ai|assistant|model)|attention,?\s+(ai|assistant|model)|dear (ai|assistant)"
       r"|instructions? for (the )?(ai|assistant|model)|hinweis (für|an) (die )?ki)\b"),
    # --- making the model say or do something specific ------------------------------
    _r("output_command", 1.5,
       r"\b(print|say|write|output|respond (only )?with|reply (only )?with|answer (only )?with|"
       r"just say|antworte (nur )?mit|sag(e|en sie)?|schreib(e|en sie)?|répond(s|ez) avec|responde con)\b"
       r"[^.\n]{0,25}[\"'“”‘’«]"),
    _r("markdown_exfil", 2.5, r"!\[[^\]]*\]\(\s*https?://"),
    _r("send_to_address", 2.0,
       r"\b(send|forward|email|mail|post|upload|transmit|cc|bcc|schick\w*|sende\w*|envía|envoie[zr]?)\b"
       r"[^.\n]{0,80}?[\w.+-]+@[\w-]+\.[\w.]+"),
    _r("url_data_param", 1.5, r"https?://[^\s)]+[?&](d|data|q|payload|secret|token|code)=", I),
    _r("encoding_request", 1.0,
       r"\b(base64|rot13|hexadecimal|in hex|reversed?|backwards|spell (it|out)|letter by letter"
       r"|one character at a time)\b"),
    _r("shouting", 1.0, r"\b(IMPORTANT|URGENT|ACHTUNG|ATTENTION|WICHTIG|NOTE TO SELF)\b", 0),
)

#: Chosen on deepset train (see ``ragprobe security detector-eval --tune``):
#: the smallest threshold whose train F1 is within 0.005 of the best, which keeps
#: recall high on the paraphrased attacks the rules were not written for.
DEFAULT_THRESHOLD = 2.0


class Detector(ABC):
    name: str = "abstract"

    @abstractmethod
    def score(self, text: str) -> Verdict:
        """Score one text. ``flagged`` uses the detector's own threshold."""

    def score_many(self, texts: Sequence[str]) -> List[Verdict]:
        return [self.score(text) for text in texts]


class HeuristicDetector(Detector):
    name = "heuristic"

    def __init__(self, threshold: float = DEFAULT_THRESHOLD, rules: Sequence[Rule] = RULES) -> None:
        self.threshold = threshold
        self.rules = tuple(rules)

    def score(self, text: str) -> Verdict:
        fired = [rule for rule in self.rules if rule.pattern.search(text or "")]
        total = sum(rule.weight for rule in fired)
        return Verdict(flagged=total >= self.threshold, score=total, rules=[r.name for r in fired])


class ProtectAIDetector(Detector):  # pragma: no cover - optional heavy dependency
    """``protectai/deberta-v3-base-prompt-injection-v2`` via ``transformers``.

    Its model card says it is English-only and should not be run on system
    prompts; the benchmark reports it on the same data anyway, because the German
    rows in deepset are exactly where a deployer would be surprised.
    """

    name = "protectai"
    MODEL = "protectai/deberta-v3-base-prompt-injection-v2"

    def __init__(self, threshold: float = 0.5, model: Optional[str] = None) -> None:
        try:
            from transformers import pipeline  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "the protectai detector needs the optional ML extra:\n"
                "    pip install 'ragprobe[ml]'"
            ) from exc
        self.threshold = threshold
        self._classifier = pipeline(
            "text-classification", model=model or self.MODEL, truncation=True, max_length=512
        )

    def _injection_probability(self, result) -> float:  # noqa: ANN001
        label = str(result["label"]).upper()
        score = float(result["score"])
        return score if label in {"INJECTION", "LABEL_1", "1"} else 1.0 - score

    def score(self, text: str) -> Verdict:
        return self.score_many([text])[0]

    def score_many(self, texts: Sequence[str]) -> List[Verdict]:
        results = self._classifier(list(texts), batch_size=16)
        verdicts = []
        for result in results:
            probability = self._injection_probability(result)
            verdicts.append(Verdict(flagged=probability >= self.threshold, score=probability))
        return verdicts


class GroqPromptGuardDetector(Detector):
    """Meta's Llama Prompt Guard 2, hosted on Groq's free tier.

    Groq serves the classifier through the chat-completions API: the message
    content comes back as a single probability in [0, 1] that the input is an
    attack. This gives a real transformer detector with no local install - which
    matters on a low-memory machine - at the cost of a network call per text.
    """

    name = "groq-guard"
    DEFAULT_MODEL = "meta-llama/llama-prompt-guard-2-86m"
    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, threshold: float = 0.5, model: Optional[str] = None, provider=None) -> None:  # noqa: ANN001
        self.threshold = threshold
        self.model = model or self.DEFAULT_MODEL
        if provider is None:
            from ragprobe.providers.openai_compat import OpenAICompatibleProvider
            provider = OpenAICompatibleProvider(model=self.model, base_url=self.BASE_URL)
        self.provider = provider

    def score(self, text: str) -> Verdict:
        raw = self.provider.chat([{"role": "user", "content": text or ""}], max_tokens=10)
        content = (raw.get("content") or "").strip()
        try:
            probability = float(content.split()[0]) if content else 0.0
        except (ValueError, IndexError):
            probability = 0.0
        return Verdict(flagged=probability >= self.threshold, score=probability)


def get_detector(name: str = "heuristic", threshold: Optional[float] = None) -> Detector:
    if name == "heuristic":
        return HeuristicDetector(DEFAULT_THRESHOLD if threshold is None else threshold)
    if name == "protectai":
        return ProtectAIDetector(0.5 if threshold is None else threshold)
    if name == "groq-guard":
        return GroqPromptGuardDetector(0.5 if threshold is None else threshold)
    raise ValueError(f"unknown detector {name!r}; expected 'heuristic', 'protectai' or 'groq-guard'")
