"""A LangChain RAG chain as a RAGProbe target.

    pip install langchain langchain-community langchain-openai   # or your providers
    ragprobe run --root examples --target langchain_target:DocsAssistant

RAGProbe instantiates ``DocsAssistant`` once, calls ``ingest()`` before the suite and
``answer(question)`` per case. The returned mapping uses LangChain's own field names
(``page_content``, ``metadata.source``), which RAGProbe understands without mapping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

DOCS_DIR = Path(__file__).resolve().parent.parent / "datasets" / "docs"


class DocsAssistant:
    def __init__(self) -> None:
        self.retriever = None
        self.llm = None

    def ingest(self) -> None:
        from langchain_community.document_loaders import DirectoryLoader, TextLoader
        from langchain_community.vectorstores import FAISS
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from langchain_text_splitters import MarkdownHeaderTextSplitter

        docs = DirectoryLoader(str(DOCS_DIR), glob="*.md", loader_cls=TextLoader).load()
        splitter = MarkdownHeaderTextSplitter([("#", "h1"), ("##", "h2")])
        chunks = []
        for doc in docs:
            stem = Path(doc.metadata["source"]).stem
            for piece in splitter.split_text(doc.page_content):
                heading = piece.metadata.get("h2") or piece.metadata.get("h1") or "intro"
                # Stable id = the same doc#slug scheme the golden set uses.
                piece.metadata["source"] = stem + "#" + heading.lower().replace(" ", "-")
                chunks.append(piece)
        self.retriever = FAISS.from_documents(chunks, OpenAIEmbeddings()).as_retriever(
            search_kwargs={"k": 3}
        )
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    def answer(self, question: str) -> Dict[str, Any]:
        assert self.retriever is not None and self.llm is not None
        contexts = self.retriever.invoke(question)
        prompt = (
            "Answer only from the documents below. If they do not contain the answer, say "
            "'I do not have enough information in the provided documents to answer that.' "
            "Cite the document id in square brackets.\n\n"
            + "\n\n".join("[" + c.metadata["source"] + "] " + c.page_content for c in contexts)
            + "\n\nQuestion: " + question
        )
        reply = self.llm.invoke(prompt)
        return {
            "answer": reply.content,
            "contexts": [{"page_content": c.page_content, "metadata": c.metadata} for c in contexts],
            "model": getattr(reply, "response_metadata", {}).get("model_name"),
        }
