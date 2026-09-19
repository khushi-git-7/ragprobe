# Case study: a documentation assistant over the Playwright guides

*What happens when the harness is pointed at real documents, real questions and a
real model - and what it caught along the way.*

## Setup

| | |
|---|---|
| Corpus | 59 Playwright guide pages from `microsoft/playwright` at revision `07f1a615` (Apache-2.0), normalised by `scripts/fetch_playwright_docs.py`: 841 chunks, heading-anchored |
| Golden set | 62 questions written the way QA engineers ask them, across 8 categories; 4 are questions the docs cannot answer and must be refused. Every `expected_chunks` id is verified against the corpus |
| Retrieval | A: hashed TF-IDF (2,048 dims, refitted per run). B: `BAAI/bge-small-en-v1.5` through `fastembed` (ONNX, CPU) |
| Generation | Stub: deterministic extractive provider (no model). Live: `gemini-3.5-flash-lite` through the OpenAI-compatible provider on Google AI Studio's free tier, temperature 0 (`gemini-3.6-flash` was tried first; its free tier allows 20 requests a day) |
| Gate | The five required checks: keyword presence, forbidden terms absent, refusal behaviour, citation present and real, grounding |
| Hardware | One laptop, no GPU, nothing paid for |

Reproduce any row with `ragprobe run --config examples/playwright-docs/ragprobe.yaml`
plus the overrides named below. The run history behind every number is committed
under `examples/playwright-docs/history/`.

## Finding 1: the first real run found a bug in the harness, not the pipeline

The first run scored **40.3 %**. Reading the failures, most were `citation_present`
reporting a *fabricated citation* - a source cited in the answer that was never
retrieved. The "fabricated" sources were things like `UI Mode`, `Receives Events`,
`How to run tests from the command line`.

They are markdown links. Real documentation is full of `[link text](./page.md)`, and
the citation extractor treated every bracketed span as a `[doc#anchor]` citation.
The five invented sample documents the harness had been tested on contained no
links, so the evaluator had never been wrong before.

The fix restricts citations to bracketed `doc#anchor` tokens that are not followed by
a link target. Nothing about the pipeline changed:

| | pass rate | hit rate@3 | MRR |
|---|---|---|---|
| Before the fix | 40.3 % | 0.603 | 0.537 |
| After the fix | **61.3 %** | 0.603 | 0.537 |

The retrieval numbers are identical because retrieval was never the problem. That
is the first thing a real corpus buys: it exercises evaluators on text that looks
like the text they will actually see.

## Finding 2: a better embedder helped retrieval and did nothing for the pass rate

Switching TF-IDF for a small neural retrieval model, with the same chunks, the same
questions and the same stub generator:

| Retrieval | hit rate@3 | MRR | recall@3 | precision@3 | pass rate |
|---|---|---|---|---|---|
| TF-IDF | 0.603 | 0.537 | 0.586 | 0.218 | 61.3 % |
| bge-small | **0.707** | **0.592** | **0.655** | **0.259** | 59.7 % |

Retrieval improved on every metric. The pass rate did not move, and in the
`locators` category it fell from 6/9 to 3/9. The dashboard's attribution insight
says why: with the right chunk now in the top 3 for 71 % of questions, the
remaining failures are *generation* failures - the extractive stub picks the two
highest-scoring sentences from the chunk, and on a real documentation page those are
often the sentences around a code sample rather than the sentence with the answer.

Two lessons that generalise:

1. **Retrieval metrics and answer quality are different axes.** A team that only
   tracks recall@k would have shipped the embedder change as a pure win.
2. **The stub is a regression detector, not a quality bar.** Its job is to be
   deterministic so that a diff is a real diff. It cannot refuse an out-of-scope
   question (0/4 in both runs) because it has no notion of answerability, only
   similarity.

## Finding 3: a real model found two more evaluator bugs, then told the truth about itself

Same corpus, same 62 questions, neural retrieval, and `gemini-3.5-flash-lite`
answering with the harness's grounded-answer prompt (temperature 0, judge off).
62 calls, seven of them throttled and retried by the provider adapter; wall time
about eight minutes on a free tier.

| Generation | pass rate | out-of-scope refused | mean score |
|---|---|---|---|
| Stub (extractive) | 59.7 % | 0 / 4 | 0.849 |
| gemini-3.5-flash-lite, first scoring | 48.4 % | **4 / 4** | 0.693 |
| gemini-3.5-flash-lite, after fixing the citation extractor (`ragprobe rescore`) | 53.2 % | 4 / 4 | 0.730 |

The pass rate *fell* against a real model, and every point of that fall is
instructive.

**Bug: citations with two sources.** The model writes
`[test_parallel#limit-workers, ci#workers]` when two chunks support one sentence.
The extractor accepted exactly one id per bracket, so those answers scored
"contains no citation". Fixed (one bracket may now carry a comma- or
semicolon-separated list), and because live answers are expensive and
nondeterministic, the fix was applied with a new command, `ragprobe rescore`,
which re-runs the evaluators over the saved answers and retrieved chunks without
calling the model: 48.4 % to 53.2 %, with retrieval metrics untouched.

**Not a bug, but the wrong required check.** Of the 29 remaining failures, twelve
fail *only* the offline grounding heuristic. Every one of the twelve is a correct,
correctly cited paraphrase of the retrieved chunk - for example:

> You can allow a small number of differing pixels by using the `maxDiffPixels`
> option in `toHaveScreenshot` or by specifying it globally in your Playwright
> config [test_snapshots#maxdiffpixels].

The heuristic measures lexical overlap with the context and was calibrated on the
extractive stub, whose answers are sentences copied from the chunk. A model that
paraphrases scores 0.26-0.64 on it. With `grounding` moved from `required_checks`
to advisory - which is what the LLM judge is for - the live pass rate is **72.6 %
(45/62)**. The lesson is not "lower the threshold"; it is that a required check
must be calibrated on the kind of system it gates.

**The remaining seventeen, attributed by the harness:**

| Cause | Cases | What it means |
|---|---|---|
| Refused because retrieval missed the answer | 7 | Correct behaviour by the model; a retrieval problem. hit rate@3 was 0 for all seven |
| Wrong answer because retrieval missed | 6 | Same root cause; the model answered from a near-miss chunk instead of refusing |
| Wrong or incomplete answer with the right chunk retrieved | 3 | Genuine generation failures |
| Refused with the right chunk retrieved | 1 | A generation failure (`cfg-tag-tests`: the tagging section was at rank 2) |

Thirteen of seventeen are retrieval. On this corpus the next unit of work is not
prompt engineering, it is the 29 % of questions whose section is not in the top 3 -
and the harness says so without anyone reading 62 answers.

## What the gate looks like in practice

The TF-IDF + stub run is committed as the example's baseline. Diffing the neural
embedder against it - the same change as Finding 2, now through the gate:

```
$ ragprobe diff --config examples/playwright-docs/ragprobe.yaml --embedder fastembed \
    --baseline examples/playwright-docs/baseline.json
  regressed 8   degraded 5   improved 15   flat 34   new 0   removed 0
  REGRESSED   cfg-worker-fixture          -0.340  case went from passing to failing | now failing: expected_citation_overlap, keyword_presence
  REGRESSED   loc-stable-definition       -0.333  case went from passing to failing | now failing: expected_citation_overlap, keyword_presence
  REGRESSED   loc-visible-opacity         -0.249  case went from passing to failing | ...
  ...
  IMPROVED    par-worker-index            +0.255  case went from failing to passing | now passing: expected_citation_overlap, keyword_presence
  IMPROVED    net-download-event          +0.332  case went from failing to passing | ...

  GATE FAILED:
    - 8 regressed case(s) exceeds the limit of 0
exit 1
```

An aggregate view says "+10 points of hit rate, ship it". The per-case view says
eight questions that used to be answered correctly no longer are, and names them.
Both are true; only the second one is a decision.

The three recorded runs and the diff are published as a live dashboard at
[khushi-git-7.github.io/ragprobe/case-study/dashboard.html](https://khushi-git-7.github.io/ragprobe/case-study/dashboard.html).

## What this cost

Nothing. The corpus is Apache-2.0, the neural embedder runs on CPU, the model is a
free tier, and the harness's own CI ran the stub configuration on every push
without a key.

## Reproducing

```bash
git clone https://github.com/khushi-git-7/ragprobe && cd ragprobe
pip install -e ".[dev,fastembed]"

# Finding 1 and 2: offline, deterministic
ragprobe run --config examples/playwright-docs/ragprobe.yaml --html
ragprobe run --config examples/playwright-docs/ragprobe.yaml --html \
  --embedder fastembed   # or set retrieval.embedder in the config

# Finding 3: a live model on Google AI Studio's free tier
export GEMINI_API_KEY=...
ragprobe run --config examples/playwright-docs/ragprobe.yaml --provider openai \
  --model gemini-3.5-flash-lite \
  --base-url https://generativelanguage.googleapis.com/v1beta/openai --no-judge --html
```
