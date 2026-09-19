"""Targets: pointing the harness at a RAG that is not the built-in pipeline.

The HTTP target is exercised against a real (local, stdlib) server so the request
body, headers, error handling and response mapping are all tested for real rather
than through a mock of ``urlopen``.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ragprobe.cli import EXIT_OK, EXIT_USAGE, main
from ragprobe.config import ConfigError, ProbeConfig
from ragprobe.evaluation.dataset import load_dataset
from ragprobe.evaluation.runner import run_suite
from ragprobe.pipeline.rag import RagResult, RetrievedChunk
from ragprobe.providers.base import REFUSAL_TEXT
from ragprobe.targets import TargetError, get_target, parse_target_spec
from ragprobe.targets.base import dig, normalise_chunks, result_from_payload
from ragprobe.targets.http_target import HttpTarget
from ragprobe.targets.python_target import PythonTarget

# ------------------------------------------------------------------ fixtures


class _RecordingHandler(BaseHTTPRequestHandler):
    """Answers every question with a canned payload and records what it received."""

    received: List[Dict[str, Any]] = []
    responder = staticmethod(lambda body: {"answer": "canned"})
    status = 200

    def log_message(self, *args):  # noqa: D401 - silence the server
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.received.append({"body": body, "headers": dict(self.headers), "path": self.path})
        payload = self.responder(body)
        self._send(payload)

    def do_GET(self):
        self.received.append({"body": {}, "headers": dict(self.headers), "path": self.path})
        self._send(self.responder({}))

    def _send(self, payload):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def server():
    """A live local HTTP server; yields (url, handler class) and shuts down after."""
    _RecordingHandler.received = []
    _RecordingHandler.status = 200
    _RecordingHandler.responder = staticmethod(lambda body: {"answer": "canned"})
    httpd = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/ask" % httpd.server_address[1], _RecordingHandler
    finally:
        httpd.shutdown()
        httpd.server_close()


def _config(**target) -> ProbeConfig:
    return ProbeConfig.from_dict({"target": target, "evaluation": {"judge_enabled": False}})


# ------------------------------------------------------------ config + spec


class TestTargetConfig:
    def test_default_is_builtin(self):
        assert ProbeConfig().target.kind == "builtin"

    def test_http_requires_url(self):
        with pytest.raises(ConfigError, match="target.url"):
            ProbeConfig.from_dict({"target": {"kind": "http"}})

    def test_python_requires_module_colon_name(self):
        with pytest.raises(ConfigError, match="package.module:callable"):
            ProbeConfig.from_dict({"target": {"kind": "python", "entry": "nocolon"}})

    def test_unknown_kind_rejected(self):
        with pytest.raises(ConfigError, match="target.kind"):
            ProbeConfig.from_dict({"target": {"kind": "grpc"}})

    def test_unknown_key_rejected(self):
        with pytest.raises(ConfigError, match="unknown key"):
            ProbeConfig.from_dict({"target": {"kind": "builtin", "urll": "x"}})

    def test_target_is_part_of_fingerprint(self):
        a = ProbeConfig.from_dict({"target": {"kind": "http", "url": "http://a/ask"}})
        b = ProbeConfig.from_dict({"target": {"kind": "http", "url": "http://b/ask"}})
        assert a.fingerprint() != b.fingerprint()

    def test_round_trips_through_overrides(self):
        cfg = ProbeConfig.from_dict({"target": {"kind": "http", "url": "http://a/ask"}})
        again = cfg.apply_overrides({"retrieval.top_k": 5})
        assert again.target.url == "http://a/ask"
        assert again.retrieval.top_k == 5


class TestParseTargetSpec:
    @pytest.mark.parametrize(
        "spec, expected",
        [
            ("builtin", {"kind": "builtin"}),
            ("", {"kind": "builtin"}),
            ("http://localhost:8000/ask", {"kind": "http", "url": "http://localhost:8000/ask"}),
            ("https://rag.example.com/v1/answer", {"kind": "http", "url": "https://rag.example.com/v1/answer"}),
            ("myapp.rag:answer", {"kind": "python", "entry": "myapp.rag:answer"}),
        ],
    )
    def test_recognised_forms(self, spec, expected):
        assert parse_target_spec(spec) == expected

    def test_unrecognised_form_is_an_error(self):
        with pytest.raises(TargetError):
            parse_target_spec("C:/some/path.py")


class TestGetTarget:
    def test_builtin_is_the_pipeline(self, config, project_root):
        target = get_target(config, base_dir=project_root)
        assert target.kind == "builtin"
        assert target.provider_name == "stub"
        assert target.deterministic is True

    def test_http_and_python_adapters(self):
        assert isinstance(get_target(_config(kind="http", url="http://x/ask")), HttpTarget)
        assert isinstance(get_target(_config(kind="python", entry="a.b:c")), PythonTarget)


# ------------------------------------------------------- payload mapping


class TestPayloadMapping:
    def test_dig_follows_dotted_paths_and_indexes(self):
        payload = {"data": {"choices": [{"text": "hi"}]}}
        assert dig(payload, "data.choices.0.text") == "hi"
        assert dig(payload, "data.missing", "d") == "d"
        assert dig(payload, "data.choices.9.text", None) is None
        assert dig(payload, "") is payload

    def test_chunks_accept_common_key_spellings(self):
        raw = [
            {"chunk_id": "a#1", "text": "one", "score": 0.9, "heading": "One"},
            {"id": "b#2", "content": "two", "similarity": "0.5"},
            {"page_content": "three", "metadata": {"source": "c.md", "score": 0.1}},
            "four",
        ]
        chunks = normalise_chunks(raw)
        assert [c.chunk_id for c in chunks] == ["a#1", "b#2", "c.md", "ctx-4"]
        assert [c.rank for c in chunks] == [1, 2, 3, 4]
        assert chunks[1].score == 0.5
        assert chunks[2].doc_id == "c.md"
        assert chunks[3].text == "four"

    def test_chunks_reject_non_list(self):
        with pytest.raises(TargetError):
            normalise_chunks({"text": "not a list"})
        with pytest.raises(TargetError):
            normalise_chunks([42])

    def test_none_contexts_means_no_retrieval(self):
        assert normalise_chunks(None) == []

    def test_string_payload_is_answer_only(self):
        result = result_from_payload("q", "just text")
        assert result.answer == "just text" and result.retrieved == [] and not result.refused

    def test_mapping_payload_with_custom_fields(self):
        payload = {"data": {"reply": "yes", "docs": [{"id": "x", "text": "t"}], "no_answer": True}, "model": "m"}
        result = result_from_payload(
            "q", payload, answer_field="data.reply", contexts_field="data.docs", refused_field="data.no_answer"
        )
        assert result.answer == "yes"
        assert result.retrieved_ids == ["x"]
        assert result.refused is True
        assert result.model == "m"

    def test_missing_answer_field_is_descriptive(self):
        with pytest.raises(TargetError, match="no 'answer' field; keys present: reply"):
            result_from_payload("q", {"reply": "x"})

    def test_rag_result_passes_through(self):
        original = RagResult(question="q", answer="a", refused=False)
        assert result_from_payload("q", original) is original


# ------------------------------------------------------------- http target


class TestHttpTarget:
    def test_posts_question_and_maps_response(self, server):
        url, handler = server
        handler.responder = staticmethod(
            lambda body: {
                "answer": "You get 20 days.",
                "contexts": [{"id": "employee_handbook#paid-time-off", "text": "20 days", "score": 0.8}],
            }
        )
        target = HttpTarget(_config(kind="http", url=url))
        result = target.ingest().answer("How many PTO days?")
        assert handler.received[0]["body"] == {"question": "How many PTO days?"}
        assert handler.received[0]["headers"]["Content-Type"] == "application/json"
        assert result.answer == "You get 20 days."
        assert result.retrieved_ids == ["employee_handbook#paid-time-off"]
        assert result.provider == "http"

    def test_extra_body_and_custom_question_field(self, server):
        url, handler = server
        target = HttpTarget(_config(kind="http", url=url, question_field="query", extra_body={"top_k": 5}))
        target.answer("q")
        assert handler.received[0]["body"] == {"query": "q", "top_k": 5}

    def test_headers_expand_env_vars_at_request_time(self, server, monkeypatch):
        url, handler = server
        monkeypatch.setenv("RAG_TOKEN", "s3cret")
        cfg = _config(kind="http", url=url, headers={"Authorization": "Bearer ${RAG_TOKEN}"})
        HttpTarget(cfg).answer("q")
        assert handler.received[0]["headers"]["Authorization"] == "Bearer s3cret"
        # The secret never reaches the results file: the config keeps the placeholder.
        assert cfg.to_dict()["target"]["headers"]["Authorization"] == "Bearer ${RAG_TOKEN}"

    def test_get_method_sends_query_string(self, server):
        url, handler = server
        HttpTarget(_config(kind="http", url=url, method="GET")).answer("what is it?")
        assert handler.received[0]["path"] == "/ask?question=what+is+it%3F"

    def test_http_error_is_a_target_error(self, server):
        url, handler = server
        handler.status = 503
        with pytest.raises(TargetError, match="HTTP 503"):
            HttpTarget(_config(kind="http", url=url)).answer("q")

    def test_non_json_response_is_a_target_error(self, server):
        url, handler = server
        handler.responder = staticmethod(lambda body: b"<html>oops</html>")
        with pytest.raises(TargetError, match="did not return JSON"):
            HttpTarget(_config(kind="http", url=url)).answer("q")

    def test_unreachable_host_is_a_target_error(self):
        target = HttpTarget(_config(kind="http", url="http://127.0.0.1:9/ask", timeout=2))
        with pytest.raises(TargetError, match="could not reach"):
            target.answer("q")

    def test_stats_describe_the_endpoint_without_secrets(self, server):
        url, _ = server
        stats = HttpTarget(_config(kind="http", url=url, headers={"X-Key": "abc"})).stats()
        assert stats["target"] == "http" and stats["url"] == url
        assert "abc" not in json.dumps(stats)


# ----------------------------------------------------------- python target


def _write_module(root: Path, name: str, source: str) -> None:
    (root / (name + ".py")).write_text(source, encoding="utf-8")


class TestPythonTarget:
    def test_plain_function_returning_dict(self, tmp_path):
        _write_module(
            tmp_path,
            "fn_target",
            "def answer(q):\n    return {'answer': 'A:' + q, 'contexts': [{'id': 'd#1', 'text': 'x'}]}\n",
        )
        target = PythonTarget(_config(kind="python", entry="fn_target:answer"), base_dir=tmp_path)
        result = target.ingest().answer("hello")
        assert result.answer == "A:hello" and result.retrieved_ids == ["d#1"]
        assert result.provider == "python"

    def test_class_with_setup_and_answer(self, tmp_path):
        _write_module(
            tmp_path,
            "cls_target",
            "class Bot:\n"
            "    def __init__(self):\n        self.ready = False\n"
            "    def ingest(self):\n        self.ready = True\n"
            "    def query(self, q):\n        assert self.ready\n        return 'ok ' + q\n",
        )
        target = PythonTarget(_config(kind="python", entry="cls_target:Bot"), base_dir=tmp_path)
        assert target.ingest().answer("x").answer == "ok x"

    def test_callable_returning_rag_result(self, tmp_path):
        _write_module(
            tmp_path,
            "rr_target",
            "from ragprobe.pipeline.rag import RagResult\n"
            "def go(q):\n    return RagResult(question=q, answer='r', refused=False)\n",
        )
        target = PythonTarget(_config(kind="python", entry="rr_target:go"), base_dir=tmp_path)
        assert target.answer("q").answer == "r"

    def test_import_failure_is_descriptive(self, tmp_path):
        target = PythonTarget(_config(kind="python", entry="does_not_exist_mod:fn"), base_dir=tmp_path)
        with pytest.raises(TargetError, match="cannot import 'does_not_exist_mod'"):
            target.ingest()

    def test_missing_attribute_is_descriptive(self, tmp_path):
        _write_module(tmp_path, "attr_target", "x = 1\n")
        target = PythonTarget(_config(kind="python", entry="attr_target:nope"), base_dir=tmp_path)
        with pytest.raises(TargetError, match="has no attribute 'nope'"):
            target.ingest()

    def test_exception_inside_target_is_wrapped(self, tmp_path):
        _write_module(tmp_path, "boom_target", "def answer(q):\n    raise ValueError('kaboom')\n")
        target = PythonTarget(_config(kind="python", entry="boom_target:answer"), base_dir=tmp_path)
        with pytest.raises(TargetError, match="raised ValueError: kaboom"):
            target.answer("q")


# ------------------------------------------------------- through the runner


class TestRunSuiteWithExternalTarget:
    def test_metrics_and_evaluators_apply_to_an_http_target(self, server, project_root):
        """The whole point: the same golden set, evaluators and metrics, on someone else's RAG."""
        url, handler = server

        def respond(body):
            question = body["question"].lower()
            if "paid time off" in question:
                return {
                    "answer": "Full-time employees get 20 days of paid time off per year [employee_handbook#paid-time-off].",
                    "contexts": [
                        {"id": "employee_handbook#paid-time-off", "text": "Full-time employees accrue 20 days of paid time off per calendar year."},
                    ],
                }
            return {"answer": REFUSAL_TEXT, "contexts": []}

        handler.responder = staticmethod(respond)
        cases = [c for c in load_dataset(project_root / "datasets" / "golden_set.yaml") if c.id == "pto-annual-allowance"]
        cfg = ProbeConfig.from_dict({"target": {"kind": "http", "url": url}, "evaluation": {"judge_enabled": False}})
        run = run_suite(cases, cfg, base_dir=project_root)
        assert run.provider == "http"
        assert run.deterministic is False
        assert run.pipeline_stats["target"] == "http"
        case = run.cases[0]
        assert case.retrieval["hit_rate@3"] == 1.0
        assert case.retrieval["reciprocal_rank"] == 1.0
        assert case.passed, case.failed_checks()

    def test_a_dead_endpoint_fails_cases_not_the_run(self, project_root):
        cases = load_dataset(project_root / "datasets" / "golden_set.yaml")[:2]
        cfg = ProbeConfig.from_dict({
            "target": {"kind": "http", "url": "http://127.0.0.1:9/ask", "timeout": 2},
            "evaluation": {"judge_enabled": False},
        })
        run = run_suite(cases, cfg, base_dir=project_root)
        assert run.total == 2 and run.failed == 2
        assert all("TargetError" in (c.error or "") for c in run.cases)


# --------------------------------------------------------------------- cli


@pytest.fixture
def workspace(tmp_path: Path, project_root: Path) -> Path:
    shutil.copytree(project_root / "datasets", tmp_path / "datasets")
    shutil.copy(project_root / "ragprobe.yaml", tmp_path / "ragprobe.yaml")
    return tmp_path


class TestCliTarget:
    def test_run_against_python_target(self, workspace, tmp_path):
        _write_module(workspace, "my_rag", "def answer(q):\n    return {'answer': 'no idea', 'contexts': []}\n")
        out = tmp_path / "results.json"
        code = main([
            "run", "--root", str(workspace), "--config", str(workspace / "ragprobe.yaml"),
            "--target", "my_rag:answer", "--no-judge", "--no-history", "--quiet", "--out", str(out),
        ])
        assert code == EXIT_OK
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["provider"] == "python"
        assert payload["config"]["target"] == {
            **ProbeConfig().to_dict()["target"], "kind": "python", "entry": "my_rag:answer",
        }

    def test_bad_target_spec_is_a_usage_error(self, workspace, tmp_path, capsys):
        code = main([
            "run", "--root", str(workspace), "--config", str(workspace / "ragprobe.yaml"),
            "--target", "C:/nope.py", "--quiet", "--out", str(tmp_path / "r.json"),
        ])
        assert code == EXIT_USAGE
        assert "cannot tell what" in capsys.readouterr().err

    def test_target_block_in_config_file(self, workspace, tmp_path):
        _write_module(workspace, "cfg_rag", "def answer(q):\n    return 'x'\n")
        (workspace / "ragprobe.yaml").write_text(
            "target:\n  kind: python\n  entry: cfg_rag:answer\nevaluation:\n  judge_enabled: false\n",
            encoding="utf-8",
        )
        out = tmp_path / "results.json"
        code = main([
            "run", "--root", str(workspace), "--config", str(workspace / "ragprobe.yaml"),
            "--no-history", "--quiet", "--out", str(out),
        ])
        assert code == EXIT_OK
        assert json.loads(out.read_text(encoding="utf-8"))["pipeline"]["entry"] == "cfg_rag:answer"

    def test_cli_help_mentions_target(self, capsys):
        with pytest.raises(SystemExit):
            main(["run", "--help"])
        assert "--target" in capsys.readouterr().out


def test_no_env_leaks_between_tests():
    assert "RAG_TOKEN" not in os.environ
