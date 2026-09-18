"""Document chunking.

Chunk IDs are *semantic*, not positional: ``security_policy#data-retention`` rather
than ``security_policy#7``. This matters for a golden dataset. Positional IDs shift
every time you re-tune ``max_words``, which silently invalidates every expected-chunk
assertion in the dataset and produces a wall of false regressions. Heading anchors
survive re-chunking, so the dataset stays meaningful across config changes.

When a section is too long it is split into overlapping parts, and the continuation
parts get a ``~2``, ``~3`` suffix. The first part keeps the bare anchor, so a dataset
that expects ``doc#section`` still matches the head of a split section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from ragprobe.config import ChunkConfig

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit of text."""

    chunk_id: str
    doc_id: str
    doc_title: str
    heading: str
    text: str
    order: int

    @property
    def anchor(self) -> str:
        """The chunk ID without any ``~N`` split suffix."""
        return self.chunk_id.split("~", 1)[0]

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "heading": self.heading,
            "text": self.text,
            "order": self.order,
        }


def slugify(text: str) -> str:
    """Lowercase, hyphen-separated, ASCII-only slug. Empty input yields ``section``."""
    slug = _SLUG_STRIP_RE.sub("-", text.strip().lower()).strip("-")
    return slug or "section"


def _words(text: str) -> List[str]:
    return text.split()


def _split_long(text: str, max_words: int, overlap_words: int) -> List[str]:
    """Split text into overlapping word windows.

    The final window is merged backwards if it would be a sliver, which avoids
    emitting a 3-word chunk that matches nothing and pollutes precision.
    """
    words = _words(text)
    if len(words) <= max_words:
        return [text.strip()]
    step = max_words - overlap_words
    parts: List[str] = []
    start = 0
    while start < len(words):
        window = words[start : start + max_words]
        parts.append(" ".join(window))
        if start + max_words >= len(words):
            break
        start += step
    if len(parts) > 1 and len(_words(parts[-1])) < max(overlap_words, 1):
        tail = parts.pop()
        parts[-1] = parts[-1] + " " + " ".join(_words(tail)[overlap_words:])
    return parts


def _normalize_whitespace(text: str) -> str:
    """Collapse source line-wrapping into single spaces.

    Markdown hard-wraps at ~80 columns, which is invisible when rendered but very
    visible once a chunk is quoted into an answer or a report cell. Collapsing here
    - at ingest, before anything is embedded or stored - also means the embedder,
    the grounding checker and the report all see identical text.
    """
    return _WS_RE.sub(" ", text).strip()


def _emit(
    chunks: List[Chunk],
    doc_id: str,
    doc_title: str,
    heading: str,
    anchor: str,
    body: str,
    cfg: ChunkConfig,
) -> None:
    body = _normalize_whitespace(body)
    if not body or len(_words(body)) < cfg.min_words:
        return
    for index, part in enumerate(_split_long(body, cfg.max_words, cfg.overlap_words)):
        chunk_id = anchor if index == 0 else f"{anchor}~{index + 1}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                doc_title=doc_title,
                heading=heading,
                text=part,
                order=len(chunks),
            )
        )


def chunk_document(
    doc_id: str,
    text: str,
    cfg: Optional[ChunkConfig] = None,
) -> List[Chunk]:
    """Split one markdown document into chunks according to ``cfg``."""
    cfg = cfg or ChunkConfig()
    cfg.validate()
    if cfg.strategy == "fixed":
        return _chunk_fixed(doc_id, text, cfg)
    return _chunk_by_heading(doc_id, text, cfg)


def _document_title(lines: Sequence[str]) -> str:
    for line in lines:
        match = _HEADING_RE.match(line)
        if match and len(match.group(1)) == 1:
            return match.group(2)
    return ""


def _chunk_by_heading(doc_id: str, text: str, cfg: ChunkConfig) -> List[Chunk]:
    lines = text.splitlines()
    doc_title = _document_title(lines)

    chunks: List[Chunk] = []
    current_heading = doc_title or doc_id
    current_anchor = f"{doc_id}#intro"
    buffer: List[str] = []
    seen_anchors: dict[str, int] = {}

    def flush() -> None:
        _emit(chunks, doc_id, doc_title, current_heading, current_anchor, "\n".join(buffer), cfg)
        buffer.clear()

    for line in lines:
        match = _HEADING_RE.match(line)
        # Only H2+ starts a new chunk. The H1 is the document title, not a section.
        if match and len(match.group(1)) >= 2:
            flush()
            current_heading = match.group(2)
            base = f"{doc_id}#{slugify(current_heading)}"
            # Duplicate headings within one document would otherwise collide.
            count = seen_anchors.get(base, 0)
            seen_anchors[base] = count + 1
            current_anchor = base if count == 0 else f"{base}-{count + 1}"
        elif match and len(match.group(1)) == 1:
            continue  # drop the H1 line itself; it is captured as doc_title
        else:
            buffer.append(line)
    flush()
    return chunks


def _chunk_fixed(doc_id: str, text: str, cfg: ChunkConfig) -> List[Chunk]:
    """Naive fixed-window chunking, kept as a contrast case.

    Useful for demonstrating in the report what happens to retrieval metrics when
    chunk boundaries stop respecting document structure.
    """
    lines = text.splitlines()
    doc_title = _document_title(lines)
    body = "\n".join(line for line in lines if not _HEADING_RE.match(line)).strip()
    chunks: List[Chunk] = []
    for index, part in enumerate(_split_long(body, cfg.max_words, cfg.overlap_words)):
        if len(_words(part)) < cfg.min_words:
            continue
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}#w{index + 1}",
                doc_id=doc_id,
                doc_title=doc_title,
                heading=doc_title,
                text=part,
                order=len(chunks),
            )
        )
    return chunks
