"""Fetch the Playwright documentation used by the real-world example.

The example at ``examples/playwright-docs/`` evaluates a documentation assistant over
Playwright's own guides. Those guides are real, public and Apache-2.0 licensed
(https://github.com/microsoft/playwright), which makes them a far more honest test
corpus than anything invented for the purpose.

This script downloads a pinned revision of the guide pages and normalises them into
plain markdown the chunker understands:

* the Docusaurus front matter (``id`` / ``title``) becomes the H1
* ``:::note`` style admonition fences are removed (their content is kept)
* code samples for languages other than JavaScript/TypeScript are dropped, so each
  concept is stated once rather than four times
* ``[`method: Page.getByRole`]`` cross-reference syntax becomes ``page.getByRole()``

The output is committed, so the example and CI run without network access. Re-run
this script to refresh it; bump ``REVISION`` deliberately, because a corpus change
changes the expected chunk ids in the golden set.

Usage::

    python scripts/fetch_playwright_docs.py [--out examples/playwright-docs/corpus]
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path
from typing import List

REVISION = "07f1a6154795f055f341b8972086533e8e48b36f"  # microsoft/playwright main, 2026-09-19
RAW_BASE = "https://raw.githubusercontent.com/microsoft/playwright/%s/docs/src/" % REVISION

#: The guide pages a QA engineer actually reads. API reference pages are generated
#: and excluded; language-specific duplicates of the same guide are excluded.
PAGES: List[str] = [
    "accessibility-testing-js.md",
    "actionability.md",
    "api-testing-js.md",
    "aria-snapshots.md",
    "auth.md",
    "best-practices-js.md",
    "browser-contexts.md",
    "browsers.md",
    "ci-intro.md",
    "ci.md",
    "clock.md",
    "codegen-intro.md",
    "codegen.md",
    "debug.md",
    "dialogs.md",
    "docker.md",
    "downloads.md",
    "emulation.md",
    "evaluating.md",
    "events.md",
    "frames.md",
    "getting-started-vscode-js.md",
    "handles.md",
    "input.md",
    "intro-js.md",
    "library-js.md",
    "locators.md",
    "mock.md",
    "mock-browser-js.md",
    "navigations.md",
    "network.md",
    "other-locators.md",
    "pages.md",
    "pom.md",
    "running-tests-js.md",
    "screenshots.md",
    "test-annotations-js.md",
    "test-assertions-js.md",
    "test-cli-js.md",
    "test-configuration-js.md",
    "test-fixtures-js.md",
    "test-global-setup-teardown-js.md",
    "test-parallel-js.md",
    "test-parameterize-js.md",
    "test-projects-js.md",
    "test-reporters-js.md",
    "test-retries-js.md",
    "test-sharding-js.md",
    "test-snapshots-js.md",
    "test-timeouts-js.md",
    "test-typescript-js.md",
    "test-ui-mode-js.md",
    "test-use-options-js.md",
    "test-webserver-js.md",
    "touch-events.md",
    "trace-viewer.md",
    "trace-viewer-intro-js.md",
    "videos.md",
    "writing-tests-js.md",
]

KEEP_CODE_LANGS = {"js", "ts", "javascript", "typescript", "html", "bash", "sh", "shell",
                   "txt", "text", "yaml", "yml", "json", "css", "ini", "diff", "xml", ""}

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_FENCE_RE = re.compile(r"^```(\S*)(.*)$")
_ADMONITION_RE = re.compile(r"^:::\w*(\[.*\])?\s*$")
_ADMONITION_END_RE = re.compile(r"^:::\s*$")
_LANGS_RE = re.compile(r"^\* langs:.*$")
_XREF_RE = re.compile(r"\[`(method|property|event|option|param): ([^`\]]+)`\](\([^)]*\))?")
_CLASS_LINK_RE = re.compile(r"\[([A-Z][A-Za-z]+)\](?!\()")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _xref(match: re.Match) -> str:
    kind, target = match.group(1), match.group(2)
    cls, _, member = target.partition(".")
    owner = cls[:1].lower() + cls[1:]
    if kind == "method":
        return "%s.%s()" % (owner, member)
    if kind == "event":
        return "the '%s' event" % member
    return "%s.%s" % (owner, member)


def normalise(raw: str, fallback_title: str) -> str:
    """Turn a docs/src page into plain markdown with an H1 title."""
    title = fallback_title
    front = _FRONT_MATTER_RE.match(raw)
    body = raw
    if front:
        body = raw[front.end():]
        for line in front.group(1).splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "title":
                title = value.strip().strip('"').strip("'")

    body = _HTML_COMMENT_RE.sub("", body)
    out: List[str] = ["# " + title, ""]
    in_code = False
    drop_code = False
    for line in body.splitlines():
        fence = _FENCE_RE.match(line)
        if fence:
            if not in_code:
                lang = fence.group(1).strip().lower()
                in_code = True
                drop_code = lang not in KEEP_CODE_LANGS
                if not drop_code:
                    out.append("```" + lang)
            else:
                in_code = False
                if not drop_code:
                    out.append("```")
                drop_code = False
            continue
        if in_code:
            if not drop_code:
                out.append(line)
            continue
        if _ADMONITION_RE.match(line) or _ADMONITION_END_RE.match(line) or _LANGS_RE.match(line):
            continue
        line = _XREF_RE.sub(_xref, line)
        line = _CLASS_LINK_RE.sub(r"\1", line)
        out.append(line)
    text = "\n".join(out).rstrip() + "\n"
    return re.sub(r"\n{3,}", "\n\n", text)


def fetch(name: str) -> str:
    request = urllib.request.Request(RAW_BASE + name, headers={"User-Agent": "ragprobe-corpus-fetch"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="examples/playwright-docs/corpus", help="output directory")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    total = 0
    for name in PAGES:
        stem = name[:-3]
        if stem.endswith("-js"):
            stem = stem[:-3]
        doc_id = stem.replace("-", "_")
        text = normalise(fetch(name), fallback_title=stem.replace("-", " ").title())
        (out / (doc_id + ".md")).write_text(text, encoding="utf-8")
        total += len(text)
        print("  %-40s %6d chars" % (doc_id + ".md", len(text)), file=sys.stderr)
    # Next to the corpus, not inside it: the loader ingests every .md under --out.
    (out.parent / "NOTICE.md").write_text(
        "# Source and license\n\n"
        "These pages are the Playwright guides from https://github.com/microsoft/playwright "
        "(`docs/src/`, revision `%s`), redistributed under the Apache License 2.0. "
        "They were reformatted by `scripts/fetch_playwright_docs.py`: front matter became the "
        "title, admonition fences and non-JavaScript code samples were removed, and "
        "cross-reference markup was flattened. Copyright (c) Microsoft Corporation.\n" % REVISION,
        encoding="utf-8",
    )
    print("wrote %d pages, %d KB, to %s" % (len(PAGES), total // 1024, out), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
