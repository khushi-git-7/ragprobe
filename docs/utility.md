# Utility check: do real users still get answers?

A defence that blocks every attack by refusing everything is worthless. Attack-success
rate alone cannot show that, so `ragprobe security utility` asks 26 ordinary questions
(15 about product facts, 11 about a short clean document, in English, German, Spanish
and French) through the same defence stack and checks each answer still contains the
right fact.

```
ragprobe security utility --models groq-qwen,groq-gptoss --cache --md reports/utility.md
```

- `--models simulated` (the default) tests the pipeline offline. The simulated victim is a
  crude echo, so its scores only prove the plumbing works, not anything about a real model.
- Live models need their API key (see the quickstart) and use the response cache, so a
  rerun is free and identical.
- The report gives the share answered correctly per defence with a 95% Wilson interval, and
  how many questions the input screen blocked before the model saw them.

Read it next to the attack-success rate: the interesting defence is the one that cuts the
attack rate while keeping this number close to the undefended row.

Why it exists: the attack benchmark only has a handful of items that carry an expected
answer, so the "utility" figure it prints is built from very few questions and should not
be quoted as an over-refusal rate. This check has enough questions to say something.
