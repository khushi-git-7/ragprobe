"""A LlamaIndex query engine as a RAGProbe target.

    pip install llama-index
    ragprobe run --root examples --target llamaindex_target:answer

A module-level function is enough: RAGProbe calls ``answer(question)`` per case. The
index is built lazily on the first call and reused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

DOCS_DIR = Path(__file__).resolve().parent.parent / "datasets" / "docs"
_engine: Optional[Any] = None


def _engine_or_build():
    global _engine
    if _engine is None:
        from llama_index.core import SimpleDirectoryReader, VectorStoreIndex

        documents = SimpleDirectoryReader(str(DOCS_DIR)).load_data()
        _engine = VectorStoreIndex.from_documents(documents).as_query_engine(similarity_top_k=3)
    return _engine


def answer(question: str) -> Dict[str, Any]:
    response = _engine_or_build().query(question)
    return {
        "answer": str(response),
        "contexts": [
            {
                # LlamaIndex nodes carry the file name; append the section so the id is stable.
                "id": Path(node.metadata.get("file_name", "doc")).stem
                + "#"
                + str(node.metadata.get("section", node.node_id[:8])),
                "text": node.get_content(),
                "score": node.score,
            }
            for node in response.source_nodes
        ],
    }
