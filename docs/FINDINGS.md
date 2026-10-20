# What RAGProbe's security suite found

A short, honest write-up of the measurements the security suite produces, how they
were obtained, and why they matter. Every number here is reproducible from the repo
with the command shown beneath it; nothing is hand-picked. Where a result is a
worst-case harness check rather than a claim about a real model, it says so.

## 1. Defence in depth cuts attack success from 92% to near zero

Against a deliberately gullible simulated model (one that obeys any instruction it
can parse, from the user, a retrieved document or a tool result), the full attack
corpus succeeds 92% of the time with no defence. A layered defence - a hardened
prompt, data/instruction separation (spotlighting), an input detector, a tool
policy and an output filter - drops that sharply.

```
ragprobe security run --defenses none,layered
```

| Defence | Attack-success rate |
|---|--:|
| none | 92% |
| layered | 0-17% (see note) |

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

## 3. The real finding: safety detectors are far weaker in German than English

```
ragprobe security detector-eval --detectors heuristic,groq-guard --tune --by-language
```

| Detector | English (n=34) | German (n=19) |
|---|--:|--:|
| heuristic | 50% | 26% |
| Llama Prompt Guard 2 | 24% | **5%** |

Both detectors are roughly half as effective on German as on English, and Prompt
Guard 2 nearly stops working on German (5%) - which is what drags its overall recall
down to 17%. This matches a well-documented pattern: LLM safety tooling is trained
and evaluated mostly on English and degrades on other languages. For anyone putting
a detector in front of a multilingual user base, that is a real, sized coverage gap,
not a hypothetical one.

Language was labelled by a small, transparent stopword-and-diacritic classifier that
can be read and audited, not a black box - because the per-language claim is only as
trustworthy as the labels behind it.

## 4. Success is measured, not judged

Most prompt-injection evaluations ask a second LLM "did the attack work?". That judge
is itself attackable and is wrong often enough to move a headline number by several
points. This suite instead plants fresh random **canaries** each trial - a secret and
a split obedience marker - so success is a string check:

- a **leak** is the secret appearing in the output, and the oracle decodes base64,
  hex, reversed and spelled-out forms, because attackers use exactly those to dodge
  naive filters;
- **obedience** is the two marker halves appearing *joined*, which a model that
  merely quotes the attack cannot produce by accident.

Because the canaries derive from a seed, offline runs are byte-for-byte reproducible
while a live model cannot have memorised them.

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
