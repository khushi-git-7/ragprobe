"""Import SQuAD 2.0 as a RAGProbe corpus and golden set.

SQuAD 2.0 (Rajpurkar et al., 2018; CC BY-SA 4.0) is the standard reading-
comprehension benchmark: Wikipedia paragraphs, crowd-written questions with the
answer span marked, and - the part that makes it useful here - questions written to
look answerable from a paragraph while not being answerable at all. Those map
directly onto RAGProbe's ``should_refuse`` cases.

The conversion turns each article into one markdown document with one ``##``
section per paragraph, so the chunk id of a paragraph is ``<article>#paragraph-<n>``
and the golden set can name exactly the paragraph the question was written against.
Retrieval over the whole corpus is then a real test: 35 articles, 1,200 paragraphs,
and a question that mentions "France" has several Normandy-adjacent paragraphs to
choose between.

Usage::

    ragprobe import squad --out examples/squad --limit 120 --unanswerable-ratio 0.25

The pure functions here take the parsed JSON; only the CLI touches the network.
"""

from __future__ import annotations

import json
import random
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SPLITS = {
    "dev": "https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v2.0.json",
    "train": "https://rajpurkar.github.io/SQuAD-explorer/dataset/train-v2.0.json",
}

_ID_STRIP_RE = re.compile(r"[^a-z0-9]+")


class ImportError_(ValueError):
    """The input is not a SQuAD 2.0 file or the options make an empty set."""


def doc_id_for(title: str) -> str:
    """``"Normans"`` -> ``normans``; ``"Steam engine"`` -> ``steam_engine``."""
    slug = _ID_STRIP_RE.sub("_", title.strip().lower()).strip("_")
    return slug or "article"


def _shortest_answer(answers: Sequence[Mapping[str, Any]]) -> Optional[str]:
    texts = [str(a.get("text", "")).strip().rstrip(".,;:") for a in answers]
    texts = [t for t in texts if t]
    if not texts:
        return None
    return min(texts, key=len)


def convert(
    data: Mapping[str, Any],
    limit: int = 100,
    unanswerable_ratio: float = 0.25,
    seed: int = 7,
    articles: Optional[int] = None,
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Return ``(documents, cases)``.

    ``documents`` maps a doc id to markdown; ``cases`` are golden-set mappings.
    Questions are sampled deterministically (``seed``) and spread across articles
    round-robin so a small set still covers many topics. ``articles`` caps how
    many articles form the corpus; the default keeps them all so the distractor
    set is as large as the benchmark's.
    """
    if not isinstance(data, Mapping) or not isinstance(data.get("data"), list):
        raise ImportError_("not a SQuAD file: expected a top-level 'data' list")
    if limit <= 0:
        raise ImportError_("limit must be > 0")
    if not 0.0 <= unanswerable_ratio <= 1.0:
        raise ImportError_("unanswerable_ratio must be between 0 and 1")

    rng = random.Random(seed)
    source_articles = list(data["data"])
    if articles is not None:
        source_articles = source_articles[: max(0, articles)]
    if not source_articles:
        raise ImportError_("no articles to import")

    documents: Dict[str, str] = {}
    answerable: Dict[str, List[Dict[str, Any]]] = {}
    unanswerable: Dict[str, List[Dict[str, Any]]] = {}
    for article in source_articles:
        title = str(article.get("title", "Untitled")).replace("_", " ")
        doc_id = doc_id_for(title)
        if doc_id in documents:
            doc_id = f"{doc_id}_{len(documents)}"
        sections = ["# " + title, ""]
        for number, paragraph in enumerate(article.get("paragraphs", []), start=1):
            context = str(paragraph.get("context", "")).strip()
            if not context:
                continue
            sections.append(f"## Paragraph {number}")
            sections.append("")
            sections.append(context)
            sections.append("")
            chunk_id = f"{doc_id}#paragraph-{number}"
            for qa in paragraph.get("qas", []):
                question = str(qa.get("question", "")).strip()
                if not question:
                    continue
                case: Dict[str, Any] = {
                    "id": "squad-" + str(qa.get("id", "")).strip(),
                    "category": doc_id,
                    "question": question,
                    "notes": f"SQuAD 2.0, article '{title}', paragraph {number}.",
                }
                if qa.get("is_impossible"):
                    case["should_refuse"] = True
                    case["notes"] += " Written to look answerable from this paragraph; it is not."
                    unanswerable.setdefault(doc_id, []).append(case)
                else:
                    answer = _shortest_answer(qa.get("answers", []))
                    if not answer:
                        continue
                    case["expected_chunks"] = [chunk_id]
                    case["required_keywords"] = [answer]
                    case["expected_answer"] = str(qa["answers"][0].get("text", "")).strip()
                    answerable.setdefault(doc_id, []).append(case)
        documents[doc_id] = "\n".join(sections).rstrip() + "\n"

    want_refusals = int(round(limit * unanswerable_ratio))
    want_answers = limit - want_refusals
    cases = _round_robin(answerable, want_answers, rng) + _round_robin(unanswerable, want_refusals, rng)
    if not cases:
        raise ImportError_("no questions matched the options")
    # Interleave so a truncated look at the file still shows both kinds.
    rng.shuffle(cases)
    return documents, cases


def _round_robin(pools: Dict[str, List[Dict[str, Any]]], want: int, rng: random.Random) -> List[Dict[str, Any]]:
    """Take up to ``want`` cases, one per article per round, in a seeded order."""
    if want <= 0 or not pools:
        return []
    order = sorted(pools)
    rng.shuffle(order)
    queues = {doc_id: rng.sample(pools[doc_id], len(pools[doc_id])) for doc_id in order}
    picked: List[Dict[str, Any]] = []
    while len(picked) < want and any(queues.values()):
        for doc_id in order:
            if queues[doc_id] and len(picked) < want:
                picked.append(queues[doc_id].pop())
    return picked


# ----------------------------------------------------------------- writing


def _yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_golden_set(cases: Sequence[Mapping[str, Any]], split: str, source: str) -> str:
    """Render cases as the YAML the dataset loader reads. Strings are JSON-quoted,
    which is valid YAML and sidesteps every quoting edge case in crowd-written text."""
    lines = [
        "# Golden set imported from SQuAD 2.0 (%s split)." % split,
        "# Source: %s" % source,
        "# License: CC BY-SA 4.0 - https://rajpurkar.github.io/SQuAD-explorer/",
        "#",
        "# expected_chunks names the exact paragraph each question was written against;",
        "# should_refuse cases were written to look answerable from a paragraph and are not.",
        "",
        "cases:",
    ]
    for case in cases:
        lines.append("  - id: " + _yaml_str(case["id"]))
        lines.append("    category: " + _yaml_str(case["category"]))
        lines.append("    question: " + _yaml_str(case["question"]))
        if case.get("should_refuse"):
            lines.append("    should_refuse: true")
        if case.get("expected_chunks"):
            lines.append("    expected_chunks: [" + ", ".join(_yaml_str(c) for c in case["expected_chunks"]) + "]")
        if case.get("required_keywords"):
            lines.append("    required_keywords: [" + ", ".join(_yaml_str(k) for k in case["required_keywords"]) + "]")
        if case.get("expected_answer"):
            lines.append("    expected_answer: " + _yaml_str(case["expected_answer"]))
        if case.get("notes"):
            lines.append("    notes: " + _yaml_str(case["notes"]))
        lines.append("")
    return "\n".join(lines)


CONFIG_TEMPLATE = """# RAGProbe configuration for the SQuAD 2.0 import. Run from this directory:
#
#   ragprobe run --config ragprobe.yaml --html
#
# Paragraphs are the retrieval unit, so max_words is set high enough to keep most
# of them whole; split parts still count for the section they belong to.

corpus_dir: corpus
dataset_path: golden_set.yaml

chunk:
  strategy: heading
  max_words: 400
  overlap_words: 40
  min_words: 5

retrieval:
  embedder: tfidf
  dim: 4096
  top_k: 3
  min_score: 0.0

generation:
  provider: stub
  prompt_version: v1
  max_sentences: 2
  include_citations: true
  refusal_threshold: 0.10
  max_tokens: 1024

evaluation:
  fuzzy_threshold: 0.60
  grounding_threshold: 0.55
  claim_support_threshold: 0.50
  judge_enabled: true
  required_checks:
    - keyword_presence
    - forbidden_absent
    - refusal_behaviour
    - citation_present
    - grounding
"""

NOTICE = """# Source and license

The documents under `corpus/` and the questions in `golden_set.yaml` are derived from
the SQuAD 2.0 {split} split (Rajpurkar, Jia and Liang, 2018), obtained from
{source} and redistributed under the Creative Commons Attribution-ShareAlike 4.0
license. Each article became one markdown file with one section per paragraph;
questions were sampled by `ragprobe import squad` (seed {seed}, limit {limit},
unanswerable ratio {ratio}).
"""


def write_example(
    out_dir: Path,
    documents: Mapping[str, str],
    cases: Sequence[Mapping[str, Any]],
    split: str,
    source: str,
    seed: int,
    limit: int,
    unanswerable_ratio: float,
) -> Path:
    out_dir = Path(out_dir)
    corpus = out_dir / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    for doc_id, text in documents.items():
        (corpus / (doc_id + ".md")).write_text(text, encoding="utf-8")
    (out_dir / "golden_set.yaml").write_text(render_golden_set(cases, split, source), encoding="utf-8")
    (out_dir / "ragprobe.yaml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    (out_dir / "NOTICE.md").write_text(
        NOTICE.format(split=split, source=source, seed=seed, limit=limit, ratio=unanswerable_ratio),
        encoding="utf-8",
    )
    return out_dir


def load_source(path: Optional[Path], split: str) -> Tuple[Mapping[str, Any], str]:
    """Read a local file, or download the named split. Returns ``(data, source)``."""
    if split not in SPLITS:
        raise ImportError_(f"unknown split {split!r}; expected one of {', '.join(sorted(SPLITS))}")
    url = SPLITS[split]
    if path is not None:
        # The recorded source is the canonical URL, not a local path: the NOTICE
        # and golden set are committed and must not leak a machine's directory layout.
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle), url
    request = urllib.request.Request(url, headers={"User-Agent": "ragprobe-import"})
    with urllib.request.urlopen(request, timeout=300) as response:  # pragma: no cover - network
        return json.loads(response.read().decode("utf-8")), url
