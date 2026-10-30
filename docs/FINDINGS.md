# What RAGProbe's security suite found

A short, honest write-up of the measurements the security suite produces, how they
were obtained, and why they matter. Every number here is reproducible from the repo
with the command shown beneath it; nothing is hand-picked. Where a result is a
worst-case harness check rather than a claim about a real model, it says so.

## 1. Against a scripted victim, defence in depth cuts attack success from 92% to near zero

This is a harness check, not a result about any model. The victim is a script that
obeys any instruction it can parse, from the user, a retrieved document or a tool
result, so the undefended rate is 92% by construction and the defended rate measures
only whether the code-level layers fire. **On real models the same defence did not
hold up** - see [results.md](results.md). The full attack corpus succeeds 92% of the
time with no defence. A layered defence - a hardened
prompt, data/instruction separation (spotlighting), an input detector, a tool
policy and an output filter - drops that sharply.

```
ragprobe security run --defenses none,layered
```

| Defence | Attack-success rate |
|---|--:|
| none | 92% |
| layered | 0-17% (see note) |

Those two rows come from `security run`, which uses the 12 hand-written scenarios. The
same scripted victim over the **bench v1 test split** gives 77% undefended and 23%
defended (`results/bench-v1-simulated.json`), because that is a different, larger set of
attacks. Neither number says anything about a real model.

The simulated victim is a **worst case that tests the harness and the deterministic
defences**, not a measurement of any production model; the report labels it as such.
Its value is that the code-level defences (detector, tool policy, output filter) are
deterministic, so the attacks they stop are exactly the attacks they would stop in
front of any model that obeys. The residual depends on the detector's coverage of
the handful of direct attacks it is shown.

## 2. A hosted ML detector caught *fewer* attacks than simple rules - here's why

Three injection detectors were scored on the independent test split of
[deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections)
(116 texts: 60 attacks, 56 benign). The heuristic's threshold was tuned on the train
split only; the transformer detector was scored at its documented default operating
point.

```
ragprobe security detector-eval --detectors heuristic,groq-guard --tune
```

| Detector | Attacks caught (recall) | False positives | Precision |
|---|--:|--:|--:|
| heuristic (pattern rules) | 40% | 0% | 100% |
| Meta Llama Prompt Guard 2 (hosted on Groq) | 17% | 0% | 100% |

A hosted, commercial-grade ML detector catching fewer attacks than a few dozen
regexes is surprising - until you split the result by language.

## 3. Both detectors scored lower on German, but the sample is too small to call it

```
ragprobe security detector-eval --detectors heuristic,groq-guard --tune --by-language
```

| Detector | English (n=34) | German (n=19) |
|---|--:|--:|
| heuristic | 50% | 26% |
| Llama Prompt Guard 2 | 24% | **5%** |

![Pattern rules catch 50 percent of English and 26 percent of German injections; Llama Prompt Guard 2 catches 24 percent and 5 percent](img/detectors-by-language.png)

Both detectors caught roughly half as much German as English, and Prompt Guard 2
caught almost none of it (5%) - which is what drags its overall recall down to 17%.

**Neither gap is statistically significant at this sample size.** Fisher's exact test
on the counts behind those percentages gives p = 0.13 for Prompt Guard 2 (8 of 34
English, 1 of 19 German) and p = 0.15 for the pattern rules (17 of 34, 5 of 19). An
earlier version of this page called this "the real finding" and said the gap was "far
weaker in German"; that was overstated and has been corrected. Two detectors on 53
labelled items cannot establish a claim about safety tooling in general.

What the numbers are consistent with is a well-documented pattern - LLM safety tooling
is trained and evaluated mostly on English - but consistent with is not evidence for.
Treat this as a reason to measure your own detector on your own users' languages, not
as a measured coverage gap.

The mechanism is easy to show even where the statistics cannot: an English-only rule
set catches 1% of the German injections in this corpus, and adding nine German patterns
takes that to 29% with no new false positives. A detector catches what someone wrote
rules for.

Language was labelled by a small, transparent stopword-and-diacritic classifier that
can be read and audited, not a black box - because the per-language claim is only as
trustworthy as the labels behind it.

## 4. Success is measured, not judged

Several prompt-injection evaluations ask a second LLM "did the attack work?", and such
a judge is itself attackable. Others already score deterministically - AgentDojo, for
one, checks real environment state - so this is a design choice with precedent, not a
novelty. This suite plants **canaries** - a secret and
a split obedience marker - so success is a string check:

- a **leak** is the secret appearing in the output, and the oracle decodes base64,
  hex, reversed and spelled-out forms, because attackers use exactly those to dodge
  naive filters;
- **obedience** is the two marker halves appearing *joined* with no text between
  them, which a model that merely quotes the attack does not produce, and which is
  also counted when the model returns it reversed, ROT13'd, base64- or hex-encoded,
  because the encoding-evasion attacks ask for exactly that.

The canaries are **derived from the run's seed**, not randomly generated: the same
seed and attack id always produce the same marker, which is what makes a run
byte-for-byte reproducible. They are not secret, and a model that had seen this
repository could in principle know them. Change `--seed` for a value no published run
has used.

Both halves of that oracle were wrong until 31 October 2026 - it accepted a refusal
that listed the two halves, and rejected obedience that arrived base64-encoded. See
[results.md](results.md#what-changed-in-the-re-score-and-why).

## 5. Defences are judged on their cost, not just their benefit

For retrieval and agent attacks the user also has a legitimate task, and the suite
checks that it still succeeds - so a "defence" that blocks the attack by breaking the
application is caught rather than rewarded. Detectors are reported with their
false-positive rate on benign inputs for the same reason: a block rate bought by
flagging real users is not a win. In the detector benchmark above, both detectors
held a 0% false-positive rate, so their recall gap is a fair comparison.

## Reproducing everything

```
pip install -e .
ragprobe security run --defenses none,layered --md         # the scorecard
ragprobe security detector-eval --detectors heuristic --tune --by-language
```

The transformer-detector rows need a free Groq API key (`GROQ_API_KEY`); everything
else runs offline with no key.
