# RAGProbe security suite

An LLM security-testing harness built on the same principles as the rest of
RAGProbe: it runs **offline and deterministically by default**, scores success with
**checkable ground truth instead of a second model's opinion**, and ships a
**regression gate** that fails CI when a change makes the system easier to attack.

It measures how a RAG/LLM application stands up to the attacks in the
[OWASP Top 10 for LLM Applications (2025)](https://genai.owasp.org/), and - the part
that makes it actionable - how much each defence actually helps and what it costs in
false positives and lost utility.

## Threat model

The attacker controls some text the application will feed to the model but does
**not** control the model, the system prompt or the application code. That text
enters through one of three **vectors**:

| Vector | Scenario | OWASP |
|---|---|---|
| `user` | the user's own turn to a support chatbot | LLM01, LLM07 |
| `document` | a passage the RAG app retrieves (indirect injection) | LLM08, LLM02 |
| `tool` | an email an agent reads while using tools | LLM06 |

The attacker's **goal** decides how a trial is scored, each by one deterministic
oracle (see `oracles.py`):

- `say_marker` - make the model emit an attacker-chosen token (proof of control);
- `leak_secret` - make it reveal a secret planted in the system prompt or data;
- `exfil_link` - make it render a link that ships the secret to the attacker;
- `send_email` - make an agent send private data out of the organisation.

## Why the ground truth is checkable, not judged

Every trial plants fresh **canaries** (`canary.py`): a random `secret`, and an
obedience `marker` split into two halves. Success is then a string check, not an
opinion:

- A **leak** is the secret appearing in the output. The oracle normalises case and
  separators and decodes base64, hex, reversed and ROT13 spans, because attackers
  ask for exactly those forms to dodge naive filters.
- **Obedience** is the two marker halves appearing **joined**. The attack text only
  ever contains the halves separately with an instruction to join them, so a model
  that merely quotes or summarises the attack cannot produce the joined form by
  accident - quoting is not miscounted as obeying.

Canaries derive from `(seed, attack_id, trial)`, so a simulated run is byte-for-byte
reproducible while a live model cannot have memorised them.

## The victims

- **`simulated`** - a deterministic, maximally gullible model. It obeys any
  instruction it can parse, from any vector, and ignores prompt-level defences.
  Its attack-success rates are a **worst case that tests the harness**, not a
  finding about any real model; reports label them as such. Its value is that the
  **code-level** defences (a detector, a tool policy, an output filter) are
  deterministic, so against an always-obey model the attacks they stop are exactly
  the attacks they would stop in front of any model that obeys.
- **`live`** - any OpenAI-compatible endpoint (Gemini and Groq free tiers, or a
  local/served open model). Nondeterministic, so every rate carries a Wilson 95%
  confidence interval and trials can be repeated.

## The defences

Defences plug into hooks so they compose (`defenses.py`). Two kinds, reported side
by side because the distinction is the practical point:

- **Prompt-level** (`hardened`, `delimit`, `spotlight`, `sandwich`) only change what
  the model reads. They lower the odds but guarantee nothing, and can only be
  measured live.
- **Code-level** (`detector`, `tool-policy`, `output-filter`) are deterministic and
  testable offline. The tool policy, for instance, makes exfiltration-by-agent
  *impossible* rather than merely unlikely: outbound mail may only go to known
  contacts or an address the user typed this turn.

The `layered` preset is defence-in-depth: one of each kind, cheap enough to run on
every request.

## Metrics

- **Attack-success rate (ASR)** per `(defence, OWASP category)`, with a Wilson 95%
  interval.
- **Utility-kept rate**: for RAG/agent trials the user also had a legitimate task;
  a defence that blocks the attack by breaking the task has not won, and this
  catches it.
- **Retrieval exposure** (RAG): success factors into P(poison retrieved) x
  P(obeyed | retrieved). Both are reported, which tells you whether to fix ingestion
  or the prompt.
- **Detector false-positive rate** on benign inputs, measured on the independent
  [deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections)
  test split, so a high block rate bought by flagging real users is visible.

## Detector benchmark

`ragprobe security detector-eval` scores injection detectors on the deepset test
split and reports the full confusion matrix (recall, false-positive rate,
precision, F1), because accuracy alone hides the two errors that matter. Three
detectors are interchangeable behind one interface:

- `heuristic` - weighted pattern rules, standard library only, runs on every
  request for free. Its threshold is tuned on the *train* split (`--tune`), never
  the test split.
- `groq-guard` - Meta's Llama Prompt Guard 2, hosted on Groq's free tier and
  reached over the API, so a real transformer detector needs no local install.
- `protectai` - ProtectAI's DeBERTa-v3 classifier, run locally via the optional
  `ragprobe[ml]` extra (CI or a notebook GPU; heavy for a laptop).

The heuristic trades recall for precision - it catches the blatant English attacks
with no false positives but misses paraphrased and non-English ones - which is
exactly the gap the transformer detectors are measured against.

A **scorecard** grades each OWASP category A-F from the residual ASR under the best
defence - the number a team shipping the feature lives with.

## Responsible use

Everything here attacks RAGProbe's **own** sample apps with **synthetic** canaries;
no payload targets a real system, and the techniques are generic and already public
(OWASP, published research). Point the `live` victim only at models and endpoints
you are authorised to test. The suite is a tool for **measuring and improving** an
application's defences - the defensive half (detectors, policies, filters, the CI
gate) is the point; the attacks exist to prove the defences work.
