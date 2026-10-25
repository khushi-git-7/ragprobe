# Changelog

All notable changes to RAGProbe are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Bench v2** - v1 kept exactly as it was, plus 56 attacks from seven new families
  (hypothetical framing, completion prefix, emotional pressure, delimiter injection,
  authorised-test claims, format hijacking, task deflection): 138 runnable attacks.
- **Utility check** (`ragprobe security utility`) - 26 ordinary questions through each
  defence, so a defence that "works" by refusing everything is visible.
- **Real-model results** (`docs/results.md`, `results/live-models.json`, and a section on
  the landing page) for Qwen, gpt-oss 20B/120B and Gemini Flash-Lite, with intervals and
  paired tests; `docs/limitations.md` says what the numbers do not show.
- Bench runs can be limited to some attack types (`--vectors`), and the manifest records it.
- Leetspeak is read by the normalizer, and the default detector screens through it.
- **LLM security suite** covering 8 of the OWASP Top 10 for LLM Applications:
  canary-checked oracles, simulated and live (Groq / Gemini) victims, eight
  defences plus a `layered` preset, chat / RAG / agent scenarios, an A-F
  scorecard, and a CI security gate.
- **Detector benchmark** on the deepset/prompt-injections test split, with
  per-language recall and bootstrap intervals.
- **Bench v1** - a frozen, versioned attack benchmark (744 items: 82 verifiable
  attacks plus 662 detection probes), every item tagged with OWASP risk,
  technique, language, source and licence, with train/dev/test splits, a
  datasheet, and `ragprobe bench build` / `bench stats`.
- **Reproducible benchmark runner** (`ragprobe bench run`) with a full manifest
  (version, git SHA, victim, seed, catalogue fingerprint) and an on-disk response
  cache so reruns are free and exact; a committed baseline run under `results/`.
- **Model leaderboard** (`ragprobe bench leaderboard`) ranking models on the test
  split with Wilson intervals and a paired McNemar test against the leader.
- **Benign false-block rate** (`ragprobe security benign`, and a `--benign`
  column in `security run`) so a defence is judged on stopping attacks *and*
  leaving real users alone.
- **Statistics module** - Wilson intervals, McNemar's paired test, percentile
  bootstrap, and effect sizes (risk difference, odds ratio, Cohen's h), with
  `docs/methodology.md`.
- **Self-contained web experience** - a dark, animated landing page, security
  scorecard, dashboard and quality report sharing one shell, with a guided
  "next step" flow between them. No external scripts, styles or fonts.

- **`ragprobe demo`** - a guided, offline walkthrough on a fictional, deliberately
  vulnerable app (Acme Helpdesk): scan it (grade F), add defences step by step,
  rescan (grade A), and check the false-block rate. Plus `docs/quickstart.md`.

- **Attack lab page** (`ragprobe security lab`) - the demo, poisoned tools, multi-turn
  attacks and hidden injections on one page of the site, built from real runs and
  reporting where the defences fall short. Added to the top menu and the guided tour.

### Fixed

- The live landing page's main button said "See a live security scan" but opened the
  dashboard, its menu had no links into the product pages, and the whole menu vanished
  on a phone. Cause: CI built the landing page before the pages it links to existed.
  The pages are now built first, the button label follows its target, and the product
  links stay visible on small screens.

### Project

- `SECURITY.md`, `CONTRIBUTING.md`, this changelog, and a roadmap (`ROADMAP.md`).
- Free and offline by default; the only runtime dependency is PyYAML.

## [0.1.0]

- Initial evaluation and regression-testing harness for RAG pipelines: retrieval
  metrics, grounding and faithfulness checks, an LLM judge, a baseline-and-diff
  regression gate, a pluggable provider interface with a deterministic stub, and
  HTML / JSON reports with a dashboard.
