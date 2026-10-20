"""A tiny, transparent language guesser for English / German / Spanish.

Why not a library: the point of the per-language breakdown is to explain *why* a
detector's recall is what it is, and that argument is only as trustworthy as the
language labels behind it. A black-box model would move the question rather than
answer it. This classifier is a few dozen stopwords and a diacritic check - small
enough to read, audit and defend in an interview, and the suite prints a labelled
sample so the labels can be eyeballed.

It covers the languages actually present in deepset/prompt-injections (English and
German, with a little Spanish) and returns ``"other"`` when it cannot tell. It is
deliberately not a general language detector.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Sequence

# Function words are the signal: they are frequent, short, and rarely shared across
# these three languages. Content words (which an attack might borrow in English)
# are avoided on purpose.
STOPWORDS: Dict[str, set] = {
    "de": set("der die das und ich sie nicht ist wie auf eine einen vergiss alle alles "
              "vorherigen bisherigen anweisungen angaben aufgaben deutschland wird haben sind "
              "was wenn für über ihre diese dass mich mir du dir wir sollte nun jetzt noch "
              "schreibe sagen hören nicht obigen gemacht kommt neue".split()),
    "en": set("the and you your ignore instructions what how is are was for with this that "
              "all please write say previous above me now do can forget everything before "
              "respond answer tell would act as new".split()),
    "es": set("el la los las de que no sí dime dices digo olvida olvide todo todos como "
              "una uno para por con tu yo".split()),
}

_DIACRITICS = {"de": "äöüß", "es": "áéíóúñ¿¡"}
_WORD_RE = re.compile(r"[a-zA-ZäöüßÄÖÜáéíóúñ]+")

LANGUAGE_NAMES = {"en": "English", "de": "German", "es": "Spanish", "other": "other"}


def classify(text: str) -> str:
    """Best guess among ``en``/``de``/``es``, or ``other`` when the signal is weak."""
    if not text:
        return "other"
    lowered = text.lower()
    tokens = [t for t in _WORD_RE.findall(lowered)]
    if not tokens:
        return "other"

    scores: Counter = Counter()
    for language, words in STOPWORDS.items():
        scores[language] = sum(1 for token in tokens if token in words)
    # Diacritics are a strong tiebreaker (and the only German signal in a short line).
    for language, marks in _DIACRITICS.items():
        if any(ch in lowered for ch in marks):
            scores[language] += 2

    best, hits = scores.most_common(1)[0]
    if hits == 0:
        return "other"
    # Require a clear win: a one-word margin over the runner-up, else "other".
    ranked = scores.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return "other"
    return best


def label_rows(rows: Sequence[Dict]) -> List[str]:
    return [classify(r.get("text", "")) for r in rows]


def distribution(rows: Sequence[Dict]) -> Dict[str, int]:
    return dict(Counter(label_rows(rows)))
