# RAGProbe roadmap

Where the project is and where it's going. RAGProbe is an open-source AI security
testing platform: it attacks your LLM / RAG / agent app the way real attackers do,
measures which defences actually work, and blocks releases that make security worse.
The goal is research-grade evidence with a polished product experience.

Legend: ✅ done · ⏳ next · 🧊 later · ⛔ decided against

## Shipped

**The harness**
- ✅ Evaluation + regression harness: retrieval metrics, grounding and faithfulness,
  optional LLM judge, baseline + diff, CI gate, offline stub provider.
- ✅ Your own system under test: HTTP service or Python entry point, same golden set,
  metrics and gate.

**Security**
- ✅ Security suite across 8 OWASP LLM risks: canary oracles (success is a string
  check, never a judge), simulated and live victims, 8 defences plus `layered`,
  chat / RAG / agent scenarios, A–F scorecard, Wilson intervals.
- ✅ Benign set with a false-block rate per defence, and a 26-question utility
  check, so a defence that "works" by refusing everything is visible.
- ✅ MCP and tool poisoning (description poison, rug-pull, cross-tool).
- ✅ Multi-turn and crescendo chains.
- ✅ Obfuscated injections (zero-width, homoglyph, spacing, HTML, leetspeak) and a
  normalizer the default detector screens through.
- ✅ Package-hallucination audit.
- ✅ **Scan your own app**: `ragprobe security scan --url` sends the benchmark at an
  endpoint you own and reports what got through, with a CI gate.

**Evidence**
- ✅ Bench v1 — frozen, versioned, 744 items (82 scoreable attacks), tagged with
  OWASP risk, technique, language, source and licence, split train/dev/test, with a
  datasheet and a NOTICE.
- ✅ Bench v2 — v1 unchanged plus seven more attack families: 138 scoreable attacks.
- ✅ `ragprobe bench run` with a full manifest (version, commit, model, seed,
  catalogue fingerprint) and an on-disk response cache, so a number repeats exactly.
- ✅ Model leaderboard with paired McNemar tests.
- ✅ Statistics: Wilson intervals, McNemar, bootstrap, effect sizes
  ([`docs/methodology.md`](docs/methodology.md)).
- ✅ Detector benchmark on deepset/prompt-injections with per-language recall — the
  German blind spot finding.
- ✅ Real-model results for four models with intervals and significance
  ([`docs/results.md`](docs/results.md)) and an honest
  [limitations page](docs/limitations.md).

**Product**
- ✅ Self-contained HTML site (landing, security report, attack lab, quality
  dashboard, run report), one dark theme, published to GitHub Pages on every push.
- ✅ `ragprobe demo` end-to-end story and `ragprobe doctor` install check.
- ✅ Data ships inside the package: `pip install` is enough, from any directory.
- ✅ CI: unit tests on 3.9 and 3.12, security gate, regression gate, Pages publish.

## Next
- ⏳ Indirect injection through real content types (PDF, HTML, CSV, email bodies).
- ⏳ A defence that reads the whole conversation, to close the multi-turn gap the
  attack lab reports.
- ⏳ More languages for the detector gap, with a back-translation check.

## Later
- 🧊 Automated red-teaming with an attacker model, reviewed before anything is
  promoted into the frozen benchmark.
- 🧊 MkDocs documentation site.
- 🧊 Technical report in `paper/`.

## Decided against, for now
- ⛔ **PyPI release.** Installing from GitHub works and is tested; publishing a name
  and a version contract adds maintenance this project does not need yet.
- ⛔ **A GitHub Marketplace action.** [`docs/scan.md`](docs/scan.md) has a
  copy-paste CI snippet, which is the same benefit without a second thing to keep
  working.

## Notes / decisions
- Free tiers and open source only; no company data; attacks target our own simulated
  or local victims, or a system the operator owns.
- Branches off `main`, one feature per PR; **Khushi merges, Claude never does**.
- Live free-tier runs are spaced, cached and resumable; code ships tested offline and
  live numbers are marked pending until a run fills them.
- Numbers from a simulated victim are labelled as such everywhere they appear.
