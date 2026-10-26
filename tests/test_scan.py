"""`ragprobe security scan` against a real local HTTP app.

The point of the scan is a claim about somebody else's app, so these tests run real
HTTP servers: one that obeys whatever it is told (a vulnerable app), one that refuses
everything, one that answers in the chat-completions shape, and several that are
broken in the ways real services are broken. Nothing is mocked at the socket level.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ragprobe.cli import EXIT_GATE_FAILED, EXIT_OK, EXIT_USAGE, main
from ragprobe.resources import bundled_path
from ragprobe.security.canary import make_canaries
from ragprobe.security.scan import (
    EndpointSpec,
    HttpApp,
    ScanError,
    _dig,
    gate,
    parse_header,
    render,
    render_markdown,
    scan,
    select_scannable,
)

CATALOGUE = bundled_path("bench/v1/attacks.jsonl")
CANARY = "OVR-test-canary-9f21"


def _handler(reply):
    """An HTTP app whose reply is ``reply(message) -> str | (status, body)``."""

    class Handler(BaseHTTPRequestHandler):
        received = []

        def _message(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw) if raw.strip().startswith("{") else {}
            Handler.received.append({"body": body, "headers": dict(self.headers)})
            if "messages" in body:
                return body["messages"][-1]["content"]
            return body.get("message", "")

        def do_POST(self):  # noqa: N802
            out = reply(self._message())
            status, payload = out if isinstance(out, tuple) else (200, out)
            encoded = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):  # keep the test output clean
            pass

    return Handler


@contextmanager
def serving(reply):
    handler = _handler(reply)
    handler.received = []
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d/chat" % httpd.server_address[1], handler
    finally:
        httpd.shutdown()
        httpd.server_close()


def _obedient(message: str):
    """A vulnerable app: it does what the message says, so markers come back joined."""
    import re

    halves = re.findall(r"\b(?:ZQ|XK)[0-9A-Fa-f]{4,}\b", message)
    joined = "".join(halves)
    return {"answer": f"Sure, here it is: {joined}. Also the code is {CANARY}."}


def _refusing(_message: str):
    return {"answer": "Sorry, I can't help with that request."}


def _app(url, **kwargs):
    return HttpApp(EndpointSpec(url=url, **kwargs))


class TestAgainstAVulnerableApp:
    def test_the_marker_attacks_are_reported_as_working(self):
        with serving(_obedient) as (url, _):
            report = scan(_app(url), CATALOGUE, limit=6)
        assert report["attacks_scored"] == 6
        assert report["successes"] == 6 and report["asr"] == 1.0
        assert report["errors"] == 0
        assert all(r["detail"] == "followed the injected instruction" for r in report["detail"])

    def test_a_planted_canary_is_reported_as_leaked(self):
        with serving(_obedient) as (url, _):
            report = scan(_app(url), CATALOGUE, canary=CANARY, limit=40)
        leaks = [r for r in report["detail"] if r["goal"] == "leak_secret"]
        assert leaks and all(r["success"] for r in leaks)
        assert "leaked the test string" in leaks[0]["detail"]
        assert report["canary_checked"] is True

    def test_the_report_names_what_got_through(self):
        with serving(_obedient) as (url, _):
            report = scan(_app(url), CATALOGUE, limit=3)
        text = render(report)
        assert "100%" in text and "follow instructions from the message body" in text
        assert report["detail"][0]["attack"] in text
        md = render_markdown(report)
        assert "What got through" in md and "95% confidence interval" in md


class TestAgainstADefendedApp:
    def test_a_refusing_app_scores_zero(self):
        with serving(_refusing) as (url, _):
            report = scan(_app(url), CATALOGUE, limit=5)
        assert report["successes"] == 0 and report["asr"] == 0.0
        assert "0%" in render(report)

    def test_zero_is_not_called_safe(self):
        with serving(_refusing) as (url, _):
            report = scan(_app(url), CATALOGUE, limit=2)
        assert "not a guarantee" in render(report)
        assert "not that the app is safe" in render_markdown(report)


class TestRequestShapes:
    def test_the_message_field_can_be_renamed(self):
        with serving(_obedient) as (url, handler):
            scan(_app(url, message_field="prompt"), CATALOGUE, limit=1)
        assert "prompt" in handler.received[0]["body"]

    def test_the_openai_shape_is_sent_and_read(self):
        def openai_app(message):
            return {"choices": [{"message": {"role": "assistant",
                                             "content": _obedient(message)["answer"]}}]}

        with serving(openai_app) as (url, handler):
            report = scan(_app(url, shape="openai", model="my-model"), CATALOGUE, limit=2)
        assert handler.received[0]["body"]["model"] == "my-model"
        assert handler.received[0]["body"]["messages"][0]["role"] == "user"
        assert report["successes"] == 2  # the nested reply was found without being told

    def test_an_explicit_answer_field_path_is_used(self):
        def nested(message):
            return {"data": {"items": [{"text": _obedient(message)["answer"]}]}}

        with serving(nested) as (url, _):
            report = scan(_app(url, answer_field="data.items.0.text"), CATALOGUE, limit=1)
        assert report["successes"] == 1

    def test_headers_are_sent_and_env_vars_expanded_at_call_time(self, monkeypatch):
        monkeypatch.setenv("SCAN_TOKEN", "s3cret")
        with serving(_refusing) as (url, handler):
            app = _app(url, headers={"Authorization": "Bearer ${SCAN_TOKEN}"})
            scan(app, CATALOGUE, limit=1)
        assert handler.received[0]["headers"]["Authorization"] == "Bearer s3cret"

    def test_a_plain_text_endpoint_works(self):
        with serving(lambda m: "no json here") as (url, _):
            report = scan(_app(url), CATALOGUE, limit=1)
        assert report["attacks_scored"] == 1 and report["successes"] == 0


class TestBrokenEndpoints:
    def test_a_dead_endpoint_is_one_clear_error(self):
        app = _app("http://127.0.0.1:9/nothing", timeout=0.3)
        app._sleep = lambda _seconds: None
        with pytest.raises(ScanError, match="could not reach"):
            app.ask("hello")

    def test_a_404_is_not_retried(self):
        with serving(lambda m: (404, {"error": "no"})) as (url, _):
            app = _app(url)
            with pytest.raises(ScanError, match="HTTP 404"):
                app.ask("hello")
            assert app.retries == 0

    def test_a_rate_limit_is_retried_then_succeeds(self):
        state = {"n": 0}

        def flaky(message):
            state["n"] += 1
            if state["n"] == 1:
                return (429, {"error": "slow down"})
            return _refusing(message)

        with serving(flaky) as (url, _):
            app = _app(url)
            app._sleep = lambda _seconds: None
            assert "can't help" in app.ask("hello")
            assert app.retries == 1

    def test_an_unreadable_reply_says_how_to_fix_it(self):
        with serving(lambda m: {"unexpected": 42}) as (url, _):
            with pytest.raises(ScanError, match="--answer-field"):
                _app(url).ask("hello")

    def test_failed_replies_are_counted_not_scored(self):
        with serving(lambda m: (404, {"error": "no"})) as (url, _):
            report = scan(_app(url), CATALOGUE, limit=3)
        assert report["errors"] == 3 and report["attacks_scored"] == 0
        assert report["asr"] is None
        assert "nothing could be scored" in render(report)


class TestScope:
    def test_only_attacks_a_black_box_can_score_are_sent(self):
        items, skipped = select_scannable(_load())
        assert items and all(i.vector == "user" for i in items)
        assert all(i.goal == "say_marker" for i in items)  # no canary given
        assert sum(skipped.values()) > 0

    def test_a_canary_unlocks_the_leak_attacks(self):
        without, _ = select_scannable(_load())
        with_canary, skipped = select_scannable(_load(), canary=True)
        assert len(with_canary) > len(without)
        assert not any("planted test string" in reason for reason in skipped)

    def test_skipped_attacks_are_explained_in_the_report(self):
        with serving(_refusing) as (url, _):
            report = scan(_app(url), CATALOGUE, limit=1)
        text = render(report)
        assert "skipped" in text and "only your app can feed" in text
        assert "leaks were NOT checked" in text

    def test_the_url_must_be_http(self):
        with pytest.raises(ScanError, match="http"):
            EndpointSpec(url="file:///etc/passwd")

    def test_a_bad_header_is_rejected(self):
        with pytest.raises(ScanError, match="Name: value"):
            parse_header("Authorization Bearer x")

    def test_the_gate_compares_against_the_limit(self):
        assert gate({"asr": 0.1}, None) and gate({"asr": 0.1}, 0.1)
        assert not gate({"asr": 0.2}, 0.1)
        assert not gate({"asr": None}, 0.0)  # nothing scored cannot pass a gate

    def test_dig_prefers_known_names_and_ignores_blanks(self):
        assert _dig({"answer": "", "reply": "here"}, None) == "here"
        assert _dig({"a": {"b": "deep"}}, None) == "deep"
        assert _dig({"n": 5}, None) is None
        assert _dig({"a": [{"text": "x"}]}, "a.9.text") is None


class TestCli:
    def test_a_scan_writes_both_reports_and_exits_ok(self, tmp_path, capsys):
        with serving(_obedient) as (url, _):
            code = main(["security", "scan", "--url", url, "--max-attacks", "2", "-q",
                         "--out", str(tmp_path / "scan.json"), "--md", str(tmp_path / "scan.md")])
        assert code == EXIT_OK
        payload = json.loads((tmp_path / "scan.json").read_text(encoding="utf-8"))
        assert payload["kind"] == "security-scan" and payload["successes"] == 2
        assert "What got through" in (tmp_path / "scan.md").read_text(encoding="utf-8")
        assert "only scan a system you own" in capsys.readouterr().err.lower()

    def test_the_gate_fails_a_vulnerable_app(self, tmp_path):
        with serving(_obedient) as (url, _):
            code = main(["security", "scan", "--url", url, "--max-attacks", "2", "-q",
                         "--fail-over", "0.1", "--out", str(tmp_path / "s.json")])
        assert code == EXIT_GATE_FAILED

    def test_the_gate_passes_a_defended_app(self, tmp_path):
        with serving(_refusing) as (url, _):
            code = main(["security", "scan", "--url", url, "--max-attacks", "2", "-q",
                         "--fail-over", "0.1", "--out", str(tmp_path / "s.json")])
        assert code == EXIT_OK

    def test_a_bad_url_is_a_usage_error_not_a_traceback(self, capsys):
        assert main(["security", "scan", "--url", "notaurl"]) == EXIT_USAGE
        err = capsys.readouterr().err
        assert err.strip().splitlines()[-1].startswith("error: ") and "Traceback" not in err

    def test_an_unreachable_endpoint_fails_the_build(self, tmp_path, capsys):
        """A scan that measured nothing must never look like a clean result."""
        code = main(["security", "scan", "--url", "http://127.0.0.1:9/x", "--timeout", "0.3",
                     "--max-attacks", "1", "-q", "--out", str(tmp_path / "s.json")])
        assert code == EXIT_USAGE
        err = capsys.readouterr().err
        assert "nothing could be scored" in err and "Traceback" not in err
        payload = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
        assert payload["errors"] == 1 and payload["attacks_scored"] == 0


def _load():
    from ragprobe.bench.dataset import load_jsonl
    return load_jsonl(CATALOGUE)


def test_the_canary_helpers_are_the_ones_the_rest_of_the_suite_uses():
    """The scan must score exactly like the in-process suite, or numbers cannot be compared."""
    canaries = make_canaries(42, "gen-many-shot-say_marker-en", 0)
    from ragprobe.security.canary import marker_emitted

    assert marker_emitted(f"{canaries.marker_a}{canaries.marker_b}", canaries)
    assert not marker_emitted(f"{canaries.marker_a} and separately {canaries.marker_b[::-1]}", canaries)
