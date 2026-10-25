# Results on live models

Real models, measured on 26 October 2026 with the code in this repository. Read
[limitations](limitations.md) first: these are small samples on free-tier APIs and say
nothing about a model's overall safety.

**Setup.** Bench v1, every attack that can be scored automatically (82; 78 for Gemini,
which cannot run the tool-calling ones). Temperature 0, one trial per attack, replies
capped at 2048 tokens (4096 for gpt-oss 20B). "Layered" is the layered defence preset
with the leetspeak-aware detector. Intervals are 95% Wilson. "p" is a paired McNemar test
of the layered run against the undefended run on the same attacks.

| Model | Attacks that work, no defence | Attacks that work, layered | Paired test | Ordinary questions answered (26) |
|---|--:|--:|--:|--:|
| Qwen 3.8 27B | 1% (1 of 82, CI 0&ndash;7%) | 1% (1 of 82) | p = 1.00 | 96% (25 of 26) |
| Gemini 3.5 Flash-Lite | 5% (4 of 78, CI 2&ndash;12%) | 4% (3 of 78) | p = 1.00 | 100% (26 of 26) |
| gpt-oss 120B | 22% (18 of 82, CI 14&ndash;32%) | 20% (16 of 82) | p = 0.77 | 100% (26 of 26) |
| gpt-oss 20B | 30% (25 of 82, CI 22&ndash;41%) | 16% (13 of 82, CI 10&ndash;25%) | **p = 0.004** | 100% (26 of 26) |

On the **extended set** (Bench v2, the 82 plus 56 attacks from seven new families):

| Model | No defence | Layered | Paired test |
|---|--:|--:|--:|
| Qwen 3.8 27B | 6% (8 of 138, CI 3&ndash;11%) | 4% (6 of 138) | p = 0.63 |
| Gemini 3.5 Flash-Lite | 10% (14 of 134, CI 6&ndash;17%) | 7% (10 of 134) | p = 0.29 |
| gpt-oss 120B | 25% (35 of 138, CI 19&ndash;33%) | 27% (37 of 138) | p = 0.83 |
| gpt-oss 20B | not run yet (hit the free tier's daily token limit) | | |

## What this shows

- **Models differ a lot.** Qwen and Gemini Flash-Lite resisted almost everything in the
  original set; the two gpt-oss models were fooled by a fifth to a third of the attacks.
  Intervals for Qwen and the gpt-oss models do not overlap, so that gap is not noise.
- **The new attack families are harder.** Qwen went from 1 of 82 on the original set to
  7 of the 56 new attacks, and Gemini from 4 of 78 to 10 of 56. A benchmark that no model
  fails cannot tell models apart, so the extension earns its place.
- **The layered defence helped one model clearly, and not the others.** On gpt-oss 20B it
  cut attacks from 25 to 13 and the paired test says that is unlikely to be chance
  (p = 0.004). On gpt-oss 120B it made no measurable difference, on either set. On Qwen and
  Gemini there was little to stop. So the defence's value depends on the model, and the
  "attacks drop to 0%" figure belongs to the simulated always-obey victim only.
- **Bigger was not safer.** gpt-oss 120B was not clearly better than 20B undefended
  (their intervals overlap). One family, one benchmark; not a rule.
- **Defences did not cost usability.** Ordinary questions were answered 96&ndash;100% of
  the time with and without the layered defence. An earlier figure of "33% utility" came
  from only three questions and was an artefact of that tiny sample.

## What kind of attack works

This is the most important caveat on the numbers above.

- **No secret leaked.** Across all four models, the 33 attacks that try to extract the
  planted admin code succeeded 0 times, even with no defence (0 of 33 on the original set,
  0 of 61 on the extended set). The system prompt tells the model never to disclose it, and
  every model obeyed that.
- **No agent was talked into emailing data out**, except one case on gpt-oss 20B that
  rendered an exfiltration link without a defence and was stopped with one.
- **What succeeds is "do what the attacker says".** Nearly every successful attack asks the
  model to print a chosen token (many-shot, refusal-suppression, payload-splitting,
  persona-switch and similar wrappers). That proves the model followed an injected
  instruction. It is a real weakness, but the immediate harm of printing a made-up word is
  low; the harm in a real deployment depends on what an obeyed instruction can do.
- That is also why the layered defence cannot stop what is left: an output filter can
  redact a secret, but a harmless-looking token is not a secret.

## Caveats specific to these runs

- gpt-oss 20B hit its token limit on 3 of 148 replies even at 4096 tokens; those count as
  "attack did not succeed", so its figures are lower bounds.
- One trial per attack at temperature 0. Providers change hosted models without notice.
- All attacks are single-turn text attacks from this benchmark's own families. A model
  that resists them may still fall to adaptive attackers.
- Across the 7 comparisons above only one is clearly significant. With several comparisons
  and small samples, treat any single p-value as a hint, not a verdict.

## Reproduce

```
ragprobe bench leaderboard --models groq-qwen,groq-gptoss,groq-gptoss-120b \
  --split all --max-tokens 2048 --cache
ragprobe bench leaderboard --models gemini-lite --split all --vectors user,document --cache
ragprobe security utility --models groq-qwen --cache
```

Add `--catalogue datasets/bench/v2/attacks.jsonl` for the extended set. The numbers above
are saved in `results/live-models.json`, which the landing page reads.
