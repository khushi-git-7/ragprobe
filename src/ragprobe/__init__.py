"""RAGProbe - an evaluation and regression-testing harness for RAG pipelines.

The package is deliberately split so that the *system under test* (``ragprobe.pipeline``)
and the *test harness* (``ragprobe.evaluation``, ``ragprobe.regression``) never import
each other's internals. The harness only ever sees the public dataclasses in
``ragprobe.pipeline.rag``, which is what lets you point RAGProbe at a different
pipeline later without rewriting the evaluators.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
