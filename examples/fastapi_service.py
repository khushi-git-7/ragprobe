"""A minimal RAG service that speaks the RAGProbe HTTP contract.

    pip install fastapi uvicorn
    uvicorn examples.fastapi_service:app --port 8000
    ragprobe run --target http://127.0.0.1:8000/ask

This one wraps RAGProbe's own reference pipeline so it runs with no API key, but the
shape of the response is what matters: ``answer`` plus ``contexts`` with stable ids.
Replace the body of ``ask`` with your own retriever and model.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from ragprobe.config import ProbeConfig
from ragprobe.pipeline.rag import RagPipeline

ROOT = Path(__file__).resolve().parent.parent
pipeline = RagPipeline(ProbeConfig.from_yaml(ROOT / "ragprobe.yaml"), base_dir=ROOT).ingest()
app = FastAPI(title="Example RAG service")


class Question(BaseModel):
    question: str


@app.post("/ask")
def ask(body: Question) -> dict:
    result = pipeline.answer(body.question)
    return {
        "answer": result.answer,
        "refused": result.refused,
        "contexts": [
            {"id": c.chunk_id, "heading": c.heading, "text": c.text, "score": c.score}
            for c in result.retrieved
        ],
    }
