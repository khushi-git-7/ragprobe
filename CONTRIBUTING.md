# Contributing to RAGProbe

Thanks for your interest. RAGProbe aims to be a dependable, honest tool, so the
bar is: changes are tested, numbers are reproducible, and the project stays free
and offline-by-default.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

No API key is needed to install, test, or run the core and the simulated security
victim. Keys are only for *live* model runs, and are read from the environment
(`GROQ_API_KEY`, `GEMINI_API_KEY`).

## Ground rules

- **Tests pass.** Run `pytest` before opening a pull request; the suite is
  deterministic and offline. Add tests for new behaviour.
- **Numbers are reproducible.** Every reported figure must come from a committed
  run and the command that produced it. If a result is from a live model, cache
  the responses and say so; do not hand-edit numbers.
- **Free and offline by default.** No paid services, and nothing that needs the
  network to install or to run the core.
- **Defensive only.** New attacks target RAGProbe's own simulated or local
  victims. See `SECURITY.md`.
- **Self-contained reports.** The HTML pages load no external scripts, styles or
  fonts; keep them that way.

## Pull requests

- One focused change per pull request, with a plain-English description of what it
  does and how it was tested.
- Keep the public CLI and report headings stable, or update their tests in the
  same change.
- Document data provenance and licences for anything imported into `datasets/`.

## Project layout

- `src/ragprobe/` - the package (core eval, `security/`, `bench/`, `dashboard/`,
  `reporting/`, `webui.py`).
- `datasets/` - attack corpora, the benchmark, benign requests, imported data.
- `docs/` - methodology, findings, the datasheet, the leaderboard plan.
- `tests/` - the test suite.
