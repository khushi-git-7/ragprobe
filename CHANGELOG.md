# Changelog

All notable changes to RAGProbe are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Project

- `SECURITY.md`, `CONTRIBUTING.md`, this changelog, and a roadmap (`ROADMAP.md`).
- Free and offline by default; the only runtime dependency is PyYAML.

## [0.1.0]

- Initial evaluation and regression-testing harness for RAG pipelines: retrieval
  metrics, grounding and faithfulness checks, an LLM judge, a baseline-and-diff
  regression gate, a pluggable provider interface with a deterministic stub, and
  HTML / JSON reports with a dashboard.
