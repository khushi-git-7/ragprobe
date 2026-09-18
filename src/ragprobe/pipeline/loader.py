"""Corpus loading.

Markdown and plain text are handled natively. PDFs are read with ``pypdf`` if it is
installed; it is an optional extra so that the base install stays light.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | PDF_SUFFIXES


class CorpusError(RuntimeError):
    """Raised when the corpus directory is missing or empty."""


def _read_pdf(path: Path) -> str:  # pragma: no cover - optional dependency path
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ImportError(
            f"Reading {path.name} requires the optional PDF extra:\n"
            "    pip install 'ragprobe[pdf]'"
        ) from exc
    reader = PdfReader(str(path))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def load_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return _read_pdf(path)
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")
    raise ValueError(f"unsupported document type: {path.suffix} ({path})")


def load_corpus(corpus_dir: Path) -> Dict[str, str]:
    """Load every supported document under ``corpus_dir``, keyed by document ID.

    The document ID is the file stem, so ``datasets/docs/security_policy.md`` becomes
    ``security_policy`` and its chunks are ``security_policy#<anchor>``.
    """
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.exists():
        raise CorpusError(f"corpus directory not found: {corpus_dir}")
    if not corpus_dir.is_dir():
        raise CorpusError(f"corpus path is not a directory: {corpus_dir}")

    paths: List[Path] = sorted(
        path
        for path in corpus_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not paths:
        raise CorpusError(
            f"no supported documents in {corpus_dir} "
            f"(looked for {', '.join(sorted(SUPPORTED_SUFFIXES))})"
        )

    documents: Dict[str, str] = {}
    for path in paths:
        doc_id = path.stem
        if doc_id in documents:
            raise CorpusError(
                f"duplicate document id {doc_id!r}: two files share the stem {path.stem!r}"
            )
        documents[doc_id] = load_document(path)
    return documents
