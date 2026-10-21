# Bench v1 - datasheet

A versioned benchmark for testing LLM / RAG / agent applications against the
OWASP Top 10 for LLM Applications. Written in the spirit of *Datasheets for
Datasets* (Gebru et al.).

## What it is

**744 items**: **82 verifiable attacks** (canary-structured,
scored automatically by the suite's oracles) and **662 detection probes**
(labelled injection / benign strings for benchmarking detectors and measuring
false positives). The two kinds are tagged by `kind` so the runner selects only
what it can actually score, while totals stay honest.

## Composition

**By kind**

| value | count |
|---|--:|
| attack | 82 |
| probe | 662 |

**By OWASP risk**

| value | count |
|---|--:|
| LLM01 | 705 |
| LLM02 | 1 |
| LLM06 | 4 |
| LLM07 | 32 |
| LLM08 | 2 |


**By technique**

| value | count |
|---|--:|
| direct-request | 1 |
| encoding-evasion | 9 |
| external | 662 |
| fake-authority | 13 |
| indirect | 7 |
| instruction-override | 13 |
| many-shot | 8 |
| obfuscation | 9 |
| payload-splitting | 4 |
| persona-switch | 9 |
| refusal-suppression | 8 |
| task-deflection | 1 |

**By language**

| value | count |
|---|--:|
| de | 108 |
| en | 176 |
| es | 25 |
| fr | 17 |
| other | 418 |


**By source**

| value | count |
|---|--:|
| deepset | 662 |
| ragprobe-generated | 70 |
| ragprobe-seed | 12 |

**By split**

| value | count |
|---|--:|
| dev | 109 |
| test | 196 |
| train | 439 |


Of the 662 probes, 263 are injections (label 1) and
the rest benign (label 0).

## How it was made

- **Seed attacks** - hand-written technique templates (`datasets/security/attacks.yaml`).
- **Generated attacks** - every injection technique crossed with four languages
  (English, German, Spanish, French) and two checkable goals; non-English
  wrappers are hand-written, not machine-translated, so the language axis is clean.
- **Detection probes** - the deepset/prompt-injections dataset.

Splits are assigned by hashing each item id (train / dev / test ~ 60 / 15 / 25),
so the assignment is deterministic and reproducible and nothing moves between
splits on a rebuild. **Detectors are tuned on dev and reported only on test.**

## Intended use

Defensive testing of systems you own or are authorised to test: measure attack
success per OWASP risk and per defence, and benchmark detectors. **Not** for
attacking third-party systems.

## Known gaps

- Verifiable attacks use planted canaries, so they measure *obedience to an
  injected instruction*, not every possible harm.
- Four languages so far; more are planned.
- garak and PyRIT imports are added in a later version.

## Licence and provenance

Each item records its `source` and `licence`; see `NOTICE.md`. RAGProbe-authored
items are MIT; imported items keep their upstream licence.

## Reproduce

`ragprobe bench build` rebuilds this catalogue from the sources above; the result
is byte-for-byte stable given the same inputs.
