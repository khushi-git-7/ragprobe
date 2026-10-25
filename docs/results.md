# Results on live models

Real models, measured on 25 October 2026 with the code in this repository. Read
[limitations](limitations.md) first: these are small samples on free-tier APIs and say
nothing about a model's overall safety.

**Setup.** Bench v1, every attack that can be scored automatically (82; 78 for Gemini,
which cannot run the tool-calling ones). Temperature 0, one trial per attack, replies
capped at 2048 tokens (4096 for gpt-oss 20B). "Layered" is the layered defence preset
as it was before the leetspeak fix. Intervals are 95% Wilson.

| Model | Attacks that work, no defence | Attacks that work, layered | Ordinary questions answered (26) |
|---|--:|--:|--:|
| Qwen 3.8 27B | 1% (1 of 82, CI 0&ndash;7%) | 1% (1 of 82) | 96% (25 of 26) |
| Gemini 3.5 Flash-Lite | 5% (4 of 78, CI 2&ndash;12%) | 4% (3 of 78) | 100% (26 of 26) |
| gpt-oss 120B | 22% (18 of 82, CI 14&ndash;32%) | 23% (19 of 82) | 100% (26 of 26) |
| gpt-oss 20B | 30% (25 of 82, CI 22&ndash;41%) | 20% (16 of 82, CI 12&ndash;29%) | 100% (26 of 26) |

## What this shows

- **Models differ a lot.** Qwen and Gemini Flash-Lite resisted almost everything in this
  set; the two gpt-oss models were fooled by roughly a fifth to a third of the attacks.
  The intervals for Qwen and gpt-oss do not overlap, so that gap is not noise.
- **Bigger was not safer here.** gpt-oss 120B was not clearly better than 20B (their
  intervals overlap). One family, one benchmark; not a rule.
- **The layered defence did not reliably help on real models.** On gpt-oss 20B it went
  from 30% to 20%, but the intervals overlap. On gpt-oss 120B it made no difference
  (22% to 23%). On Qwen and Gemini there was almost nothing left to stop. The input
  screen did block 28 of the 82 attacks before the model saw them, yet the success
  count on the 120B model did not fall. So the strong
  "attacks drop to 0%" figure is a property of the simulated always-obey victim, not of
  real models.
- **Defences did not cost usability.** Ordinary questions were answered 96&ndash;100% of
  the time with and without the layered defence. An earlier figure of "33% utility" came
  from only three questions and was an artefact of that tiny sample; the 26-question
  check replaces it.

## Caveats specific to these runs

- gpt-oss 20B hit its token limit on 3 of 148 replies even at 4096 tokens; those count as
  "attack did not succeed", so its figures are lower bounds.
- One trial per attack at temperature 0. Providers change hosted models without notice.
- All attacks are single-turn text attacks from this benchmark's own families. A model
  that resists them may still fall to adaptive attackers.

## Reproduce

```
ragprobe bench leaderboard --models groq-qwen,groq-gptoss,groq-gptoss-120b \
  --split all --max-tokens 2048 --cache
ragprobe bench leaderboard --models gemini-lite --split all --vectors user,document --cache
ragprobe security utility --models groq-qwen --cache
```

The numbers above are saved in `results/live-models.json`, which the landing page reads.
