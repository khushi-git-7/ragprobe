"""Attack *your* app: a black-box scan of an HTTP chat or assistant endpoint.

Everything else in the security suite attacks RAGProbe's own sample apps, where a
secret can be planted in the system prompt and every tool call watched. That is the
right way to compare defences, and the wrong way to answer "is the thing we shipped
safe?". This module answers that one. It sends the benchmark's attacks to a URL you
own, reads the reply, and reports what got through.

The trick that makes a black-box result checkable is the obedience marker. An attack
asks for two random halves to be printed *joined*; the attack text only ever contains
them separately. So a reply containing the joined marker cannot be an echo or a
summary - the app followed an instruction that came from the message body. No judge
model, no guesswork, and nothing about your prompt needs to be known.

What it can see, and what it cannot:

* obedience (``say_marker``) - always checkable, as above;
* a leak (``leak_secret``) - only if you pass ``--canary``, a string you have placed
  in your own system prompt for the test. It is matched through the same decodings
  the rest of the suite understands (spelled out, reversed, rot13, base64, hex);
* exfiltration and agent misuse - *not* checkable from outside, because the harm is
  a side effect this scanner cannot observe. Those attacks are skipped and counted,
  and the report says so rather than quietly scoring them as safe.

Only scan a system you own or are authorised to test.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ragprobe.bench.dataset import load_jsonl
from ragprobe.bench.schema import BenchItem, to_attack
from ragprobe.security.canary import leak_form, make_canaries, marker_emitted
from ragprobe.stats import wilson_interval

#: Goals whose success a scanner outside the app can actually verify.
CHECKABLE_GOALS = ("say_marker", "leak_secret")

#: Response fields that commonly hold the assistant's reply, in the order tried.
ANSWER_KEYS = ("answer", "reply", "response", "text", "message", "content", "output",
               "result", "completion")

#: Request shapes. "simple" is a JSON object with one text field; "openai" is the
#: chat-completions body, which covers anything that speaks that dialect.
SHAPES = ("simple", "openai")

RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_ATTEMPTS = 4


class ScanError(ValueError):
    """The endpoint could not be reached, or did not answer in a usable shape."""


@dataclass
class EndpointSpec:
    """How to talk to the app under test."""

    url: str
    method: str = "POST"
    shape: str = "simple"
    message_field: str = "message"
    answer_field: Optional[str] = None       #: None = find it among ANSWER_KEYS
    headers: Dict[str, str] = field(default_factory=dict)
    extra_body: Dict[str, Any] = field(default_factory=dict)
    model: Optional[str] = None              #: for the "openai" shape
    timeout: float = 30.0
    delay: float = 0.0                       #: seconds to wait between requests

    def __post_init__(self) -> None:
        if self.shape not in SHAPES:
            raise ScanError(f"unknown --shape {self.shape!r}; expected one of {', '.join(SHAPES)}")
        parsed = urllib.parse.urlparse(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ScanError(f"--url must be a http(s) URL, got {self.url!r}")


def parse_header(raw: str) -> Tuple[str, str]:
    """``"Authorization: Bearer ${TOKEN}"`` -> a header pair, env vars expanded later."""
    name, sep, value = raw.partition(":")
    if not sep or not name.strip():
        raise ScanError(f"--header must look like 'Name: value', got {raw!r}")
    return name.strip(), value.strip()


def _dig(payload: Any, key: Optional[str]) -> Optional[str]:
    """Pull the reply text out of a JSON response.

    With an explicit ``key`` (``choices.0.message.content`` is allowed) only that path
    is read, so a wrong field is an error and not a silent empty answer. Without one,
    the known reply fields are tried at any depth, which covers hand-rolled services
    and the chat-completions shape alike.
    """
    if key:
        node: Any = payload
        for part in key.split("."):
            if isinstance(node, list):
                if not part.isdigit() or int(part) >= len(node):
                    return None
                node = node[int(part)]
            elif isinstance(node, dict):
                if part not in node:
                    return None
                node = node[part]
            else:
                return None
        return node if isinstance(node, str) else None

    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for name in ANSWER_KEYS:
            value = payload.get(name)
            if isinstance(value, str) and value.strip():
                return value
        for value in payload.values():
            found = _dig(value, None)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = _dig(value, None)
            if found:
                return found
    return None


class HttpApp:
    """One method: send text, get the reply. Standard library only."""

    def __init__(self, spec: EndpointSpec,
                 opener: Optional[Callable[[urllib.request.Request, float], Any]] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.spec = spec
        self._open = opener or (lambda request, timeout: urllib.request.urlopen(request, timeout=timeout))
        self._sleep = sleep
        self.requests = 0
        self.retries = 0

    def _body(self, text: str) -> Dict[str, Any]:
        body: Dict[str, Any] = dict(self.spec.extra_body)
        if self.spec.shape == "openai":
            body.setdefault("model", self.spec.model or "gpt-3.5-turbo")
            body["messages"] = [{"role": "user", "content": text}]
        else:
            body[self.spec.message_field] = text
        return body

    def _request(self, text: str) -> urllib.request.Request:
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "ragprobe-scan"}
        for name, value in self.spec.headers.items():
            headers[name] = os.path.expandvars(value)  # expanded per call, never stored
        body = self._body(text)
        if self.spec.method.upper() == "GET":
            query = urllib.parse.urlencode({k: str(v) for k, v in body.items()})
            joiner = "&" if "?" in self.spec.url else "?"
            return urllib.request.Request(self.spec.url + joiner + query, headers=headers,
                                          method="GET")
        return urllib.request.Request(self.spec.url, data=json.dumps(body).encode("utf-8"),
                                      headers=headers, method=self.spec.method.upper())

    def ask(self, text: str) -> str:
        """The app's reply to one message. Raises :class:`ScanError` if it cannot answer."""
        delay = 2.0
        last = "no attempt made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.requests += 1
            try:
                with self._open(self._request(text), self.spec.timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:200] if exc.fp else ""
                last = f"HTTP {exc.code} from {self.spec.url}: {detail}".strip()
                if exc.code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                    raise ScanError(last) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                last = f"could not reach {self.spec.url}: {reason}"
                if attempt == MAX_ATTEMPTS:
                    raise ScanError(last) from None
            self.retries += 1
            self._sleep(delay)
            delay = min(delay * 2, 30.0)
        else:  # pragma: no cover - the loop always breaks or raises
            raise ScanError(last)

        if self.spec.delay:
            self._sleep(self.spec.delay)
        text_body = raw.strip()
        if not text_body:
            raise ScanError(f"{self.spec.url} returned an empty body")
        try:
            payload = json.loads(text_body)
        except ValueError:
            return text_body  # a plain-text endpoint is fine
        answer = _dig(payload, self.spec.answer_field)
        if answer is None:
            hint = (f"no string at --answer-field {self.spec.answer_field!r}"
                    if self.spec.answer_field else
                    "could not find the reply; pass --answer-field (dots allowed, e.g. "
                    "choices.0.message.content)")
            raise ScanError(f"{self.spec.url} answered with {text_body[:160]!r}: {hint}")
        return answer


def select_scannable(items: Sequence[BenchItem],
                     canary: bool = False) -> Tuple[List[BenchItem], Dict[str, int]]:
    """The attacks a black-box scan can score, and a count of what it had to skip.

    Keeps single-message attacks aimed at the user's own turn whose success is visible
    in the reply. Everything else is counted as skipped, with the reason, because a
    skipped attack is not a passed attack - and because sending an attack nobody can
    score would spend the app's budget for nothing.
    """
    keep: List[BenchItem] = []
    skipped: Dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for item in items:
        if item.kind != "attack":
            continue
        if item.vector != "user":
            skip(f"arrives through the {item.vector} channel, which only your app can feed")
        elif item.goal not in CHECKABLE_GOALS:
            skip(f"success is a side effect this scanner cannot see ({item.goal})")
        elif item.goal == "leak_secret" and not canary:
            skip("a leak is only visible with a planted test string (pass --canary)")
        else:
            keep.append(item)
    return keep, skipped


def scan(
    app: HttpApp,
    catalogue: Path,
    canary: Optional[str] = None,
    seed: int = 42,
    limit: Optional[int] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Send every scannable attack to the app and score the replies."""
    items, skipped = select_scannable(load_jsonl(catalogue), canary=bool(canary))
    if not items:
        raise ScanError(f"no scannable attacks in {catalogue}")
    if limit is not None:
        items = items[:limit]

    started = time.time()
    rows: List[Dict[str, Any]] = []
    errors = 0
    for index, item in enumerate(items, 1):
        if progress:
            progress(index, len(items))
        attack = to_attack(item)
        canaries = make_canaries(seed, attack.id, 0)
        payload = attack.rendered_payload(canaries)
        detail, reply, success = "", "", False
        try:
            reply = app.ask(payload)
        except ScanError as exc:
            errors += 1
            detail = f"no reply: {exc}"
        else:
            if attack.goal == "say_marker":
                success = marker_emitted(reply, canaries)
                detail = "followed the injected instruction" if success else "did not obey"
            else:
                form = leak_form(reply, canary) if canary else None
                success = form is not None
                detail = f"leaked the test string ({form})" if success else "test string not leaked"
        rows.append({
            "attack": attack.id, "technique": item.technique, "language": item.language,
            "goal": attack.goal, "owasp": attack.owasp, "success": success, "detail": detail,
            "payload": payload[:300], "reply": reply[:300],
        })

    scored = [r for r in rows if not r["detail"].startswith("no reply")]
    successes = sum(1 for r in scored if r["success"])
    total = len(scored)
    lo, hi = wilson_interval(successes, total) if total else (0.0, 0.0)
    by_technique: Dict[str, List[int]] = {}
    for row in scored:
        bucket = by_technique.setdefault(row["technique"], [0, 0])
        bucket[0] += bool(row["success"])
        bucket[1] += 1

    return {
        "kind": "security-scan",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint": {"url": app.spec.url, "method": app.spec.method.upper(),
                     "shape": app.spec.shape, "answer_field": app.spec.answer_field},
        "catalogue": Path(catalogue).as_posix(),
        "canary_checked": bool(canary),
        "seed": seed,
        "attacks_sent": len(rows),
        "attacks_scored": total,
        "successes": successes,
        "asr": round(successes / total, 4) if total else None,
        "asr_ci95": [round(lo, 4), round(hi, 4)],
        "errors": errors,
        "requests": app.requests,
        "retries": app.retries,
        "skipped": skipped,
        "by_technique": {k: {"successes": v[0], "trials": v[1]} for k, v in sorted(by_technique.items())},
        "duration_s": round(time.time() - started, 2),
        "detail": rows,
    }


def _worked(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [r for r in report["detail"] if r["success"]]


def render(report: Dict[str, Any]) -> str:
    """A terminal summary: the number, what it means, and what was not tested."""
    lines = ["", f"RAGProbe scan of {report['endpoint']['url']}", "-" * 62]
    total, successes = report["attacks_scored"], report["successes"]
    if total:
        lo, hi = report["asr_ci95"]
        bar = "#" * round(20 * successes / total)
        lines.append(f"  attacks that worked  [{bar:.<20}]  {100 * successes / total:.0f}%  "
                     f"({successes}/{total}, 95% CI {lo * 100:.0f}-{hi * 100:.0f}%)")
    else:
        lines.append("  nothing could be scored")
    if report["errors"]:
        lines.append(f"  {report['errors']} attack(s) got no usable reply - not counted either way")
    if report["by_technique"]:
        worst = sorted(report["by_technique"].items(),
                       key=lambda kv: (-kv[1]["successes"], kv[0]))[:5]
        shown = ", ".join(f"{k} {v['successes']}/{v['trials']}" for k, v in worst if v["successes"])
        if shown:
            lines.append(f"  worked most often    {shown}")
    worked = _worked(report)
    if worked:
        lines.append("")
        lines.append("  these messages made your app follow instructions from the message body:")
        for row in worked[:8]:
            lines.append(f"    - {row['attack']} ({row['technique']}, {row['language']})")
        if len(worked) > 8:
            lines.append(f"    ... and {len(worked) - 8} more (see the report)")
    lines.append("")
    lines.append("  What this did and did not test")
    lines.append("    - it checks whether your app obeys instructions hidden in a user message")
    if not report["canary_checked"]:
        lines.append("    - leaks were NOT checked: plant a test string in your prompt and pass --canary")
    for reason, count in sorted(report["skipped"].items()):
        lines.append(f"    - skipped {count}: {reason}")
    lines.append("    - a clean result is not a guarantee; it means these attacks did not work")
    lines.append("")
    return "\n".join(lines)


def render_markdown(report: Dict[str, Any]) -> str:
    total, successes = report["attacks_scored"], report["successes"]
    lo, hi = report["asr_ci95"]
    rate = f"{100 * successes / total:.0f}%" if total else "&ndash;"
    out = [f"# Security scan: {report['endpoint']['url']}\n",
           f"Sent **{report['attacks_sent']}** attacks from `{report['catalogue']}`, "
           f"scored **{total}**, on {report['created']}.\n",
           "| Measure | Value |", "|---|--:|",
           f"| Attacks that worked | {rate} ({successes}/{total}) |",
           f"| 95% confidence interval | {lo * 100:.0f}&ndash;{hi * 100:.0f}% |",
           f"| Replies that failed | {report['errors']} |", ""]
    if report["by_technique"]:
        out += ["## By technique", "", "| Technique | Worked |", "|---|--:|"]
        out += [f"| `{k}` | {v['successes']}/{v['trials']} |"
                for k, v in report["by_technique"].items()]
        out.append("")
    worked = _worked(report)
    if worked:
        out += ["## What got through", "",
                "| Attack | Technique | Language |", "|---|---|---|"]
        out += [f"| `{r['attack']}` | {r['technique']} | {r['language']} |" for r in worked]
        out.append("")
    out += ["## Scope", "",
            "- Checked: whether the app follows an instruction planted in a user message, "
            "proved by a random marker it was asked to join.",
            ("- Checked: whether the canary you planted in your prompt came back, in any "
             "of the encodings the suite decodes." if report["canary_checked"] else
             "- **Not** checked: leaks. Plant a test string in your system prompt and pass "
             "`--canary` to measure them.")]
    for reason, count in sorted(report["skipped"].items()):
        out.append(f"- Skipped {count} attack(s): {reason}.")
    out += ["- A clean result means these attacks did not work, not that the app is safe.", ""]
    return "\n".join(out)


def gate(report: Dict[str, Any], max_asr: Optional[float]) -> bool:
    """True if the scan passes the threshold (used for the CI exit code)."""
    if max_asr is None:
        return True
    return report["asr"] is not None and report["asr"] <= max_asr + 1e-9
