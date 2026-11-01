"""A deliberately vulnerable chat endpoint, used only to self-test action.yml.

It obeys whatever the message tells it to do, so the marker halves come back
joined and the scan has something to find. Mirrors the ``_obedient`` fixture in
tests/test_scan.py. It is not shipped in the package and must never be deployed.
"""

from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

CANARY = "ADMIN-SELFTEST-42"
HALF = re.compile(r"\b(?:ZQ|XK)[0-9A-Fa-f]{4,}\b")


class Handler(BaseHTTPRequestHandler):
    def _message(self) -> str:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        body = json.loads(raw) if raw.strip().startswith("{") else {}
        if "messages" in body:
            return body["messages"][-1]["content"]
        return body.get("message", "")

    def do_POST(self) -> None:  # noqa: N802
        message = self._message()
        joined = "".join(HALF.findall(message))
        # the echo matters: the scan's preflight checks that two different
        # questions get two different answers before it trusts any result
        answer = (f"Re '{message[:40]}': sure, here it is: {joined}. "
                  f"Also the code is {CANARY}.")
        payload = json.dumps({"answer": answer}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
