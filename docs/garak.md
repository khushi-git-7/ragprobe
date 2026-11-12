# garak and RAGProbe, side by side

[garak](https://github.com/NVIDIA/garak) (NVIDIA, Apache-2.0) scans a **model**: it
sends hundreds of probes (jailbreaks, encodings, prompt injection, data leaks, unsafe
code) and scores the replies with its detectors. RAGProbe scans the **app** built on
the model: the retrieved documents, the tools and the defences around it. The two
answer different questions, so a team that runs both has two reports in two
vocabularies.

`ragprobe security garak` reads garak's report and puts its results in RAGProbe's
terms: one row per OWASP risk, and, given a RAGProbe run, the two side by side.

```bash
# 1. garak against the model (its report path is printed at the end of the run)
garak --target_type openai --target_name gpt-4o-mini --probes dan,encoding,web_injection

# 2. RAGProbe against the app
ragprobe security run --victim live --model gpt-4o-mini --out reports/security.json

# 3. both, by OWASP risk
ragprobe security garak ~/.local/share/garak/garak_runs/garak.<run>.report.jsonl \
    --with reports/security.json --md
```

Here, garak's `web_injection` probes against its `test.Repeat` generator (a stand-in
model that echoes every prompt back, so it "falls" for every injection), beside
RAGProbe's built-in simulated victim:

```
garak 0.17.2.pre1 against test.Repeat
------------------------------------------------------------
  risk          garak (model)   RAGProbe (app, layered)
  LLM01            not probed   100% -> 0%  A
  LLM02          349/626  56%   100% -> 0%  A
  LLM05          349/626  56%   not probed
  LLM06            not probed   100% -> 0%  A
  LLM07            not probed   100% -> 0%  A
  LLM08            not probed   100% -> 0%  A

  most hits: web_injection.TaskXSS (85/85, 100%)
```

It writes `reports/garak.json` (`--out`) and, with `--md`, `reports/garak.md`: the
side-by-side table, garak's results by risk with 95% Wilson intervals, and the
probes with the most hits.

## How garak's numbers are read

- **Only garak's own counts.** For each probe and detector garak records how many
  outputs the detector passed and how many it failed. A fail is a hit: the attack
  worked. RAGProbe re-scores nothing. An output garak could not score (`nones`) is
  left out of the rate, as garak leaves it out.
- **A probe counts once.** garak runs several detectors over the same outputs, so
  adding them up would count each output several times. Each probe counts by its
  detector with the highest hit rate, the worst case.
- **OWASP v1.1 to 2025.** garak tags its probes with the OWASP Top 10 for LLM
  Applications v1.1 (2023); RAGProbe uses the 2025 list, which renumbered it. Each
  tag is mapped to the 2025 risk it became:

  | garak tag (v1.1) | 2025 risk |
  |---|---|
  | `owasp:llm01` Prompt Injection | LLM01 Prompt Injection |
  | `owasp:llm02` Insecure Output Handling | LLM05 Improper Output Handling |
  | `owasp:llm03` Training Data Poisoning | LLM04 Data and Model Poisoning |
  | `owasp:llm04` Model Denial of Service | LLM10 Unbounded Consumption |
  | `owasp:llm05` Supply Chain Vulnerabilities | LLM03 Supply Chain |
  | `owasp:llm06` Sensitive Information Disclosure | LLM02 Sensitive Information Disclosure |
  | `owasp:llm08` Excessive Agency | LLM06 Excessive Agency |
  | `owasp:llm09` Overreliance | LLM09 Misinformation |
  | `owasp:llm07` Insecure Plugin Design | no 2025 entry: shown as `v1.1-LLM07` |
  | `owasp:llm10` Model Theft | no 2025 entry: shown as `v1.1-LLM10` |

  A probe with two tags counts under both risks. A probe with no OWASP tag is counted
  apart, as "no OWASP tag".

## What the two columns can and can't tell you

- They measure different targets. garak's column is the model on its own; RAGProbe's
  is the app, with its documents, tools and defence. A high garak rate and an A for
  the app is a model that the app's defence holds back, not a contradiction.
- The rates are not comparable as numbers: different attacks, different counts, and
  each tool's own definition of a hit. Read each column against its own interval.
- "not probed" means that tool sent nothing for that risk. It is not a pass.
- One report is one garak run. Probes run in separate garak runs are separate
  reports.
