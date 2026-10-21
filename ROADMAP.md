# RAGProbe roadmap

Where the project is and where it's going. RAGProbe is an open-source AI security
testing platform: it attacks your LLM / RAG / agent app the way real attackers
do, measures which defences actually work, and blocks releases that make security
worse. The goal is research-grade evidence with a polished product experience.

Legend: ✅ done · 🚧 in progress · ⏳ next · 🧊 later · ⛔ blocked

## Shipped (merged to `main`)
- ✅ Core evaluation + regression harness (retrieval metrics, grounding/faithfulness,
  LLM-judge, baseline+diff gate, stub provider).
- ✅ Security suite across 8 OWASP LLM risks: canary oracle, simulated + live
  (Groq/Gemini) victims, 8 defences + `layered`, chat/RAG/agent scenarios, A–F
  scorecard, Wilson intervals.
- ✅ Detector benchmark on deepset/prompt-injections with per-language recall.
- ✅ Self-contained HTML site (landing, security, dashboard, quality report),
  unified dark theme + shared nav + animation, published to GitHub Pages.
- ✅ CI: unit tests, security gate, regression gate, Pages publish.

## Phase 1 — research-grade core
- 🚧 **Stats upgrade** — Wilson everywhere, **McNemar** (paired defence/model
  comparison), **bootstrap** CIs for recall/F1, effect sizes; `docs/methodology.md`.
- ⏳ **Bench v1 dataset** — a frozen, versioned attack set (~400) tagged with
  id / OWASP / technique / language / source / licence, from our own attacks +
  deepset (Apache-2.0) + vetted garak (Apache-2.0) & PyRIT (MIT) imports, with a
  train/dev/test split and a datasheet.
- ⏳ **`ragprobe bench run`** — one command, `--suite v1 --seed 42`, full manifest
  + on-disk response cache; committed baseline runs under `results/`.
- ⏳ **Benign set (200+)** — public data; every defence reports false-block rate.
- ⏳ **Live model leaderboard** — Bench v1 across free models (Groq, Gemini),
  rate-limited and cached over several days.

## Phase 2 — attacks that matter in 2026
- 🧊 MCP / tool-poisoning tests (sandboxed agent only).
- 🧊 Indirect injection through real content types (PDF, HTML, Markdown, CSV, email).
- 🧊 Multi-turn / agent hijack chains with canary data and fake tools.
- 🧊 Automated red-teaming (optional attacker LLM, reviewed before promotion).
- 🧊 Multilingual deep dive (4–6 languages, offline translation + back-translation check).

## Phase 3 — product experience
- 🧊 SaaS-style dashboard (OWASP matrix, attack explorer, defence scatter, leaderboard,
  runs, methodology) as a static site with a real design system.
- 🧊 Professional CLI (Rich output, `init`, `doctor`, `--json`).
- 🧊 Ship as a package (PyPI, semver, CHANGELOG, extras).
- 🧊 GitHub Action `ragprobe/security-gate` on the Marketplace.
- 🧊 MkDocs documentation site.
- 🧊 Demo victim app ("Acme Helpdesk", fictional) for the end-to-end story.

## Phase 4 — proof and polish
- 🧊 Technical report (`paper/`), README landing page, quality bar (mypy, ruff,
  coverage, CodeQL, SECURITY.md), launch kit drafts.

## Notes / decisions
- Free tiers and open source only; no company data; attacks target our own
  simulated/local victims only.
- Branches off `main`, one feature per PR; **Khushi merges, Claude never does**.
- Live free-tier runs are spaced, cached and resumable; code ships tested offline
  and live numbers are marked pending until a run fills them.
