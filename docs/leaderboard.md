# The model security leaderboard

`ragprobe bench leaderboard` runs the benchmark's held-out test split against
several models, through the same defences, and ranks them by attack-success with
Wilson intervals and a paired McNemar test against the leader. It is the answer to
"which of these models should we build on?"

## Running it

```bash
# offline sanity check (the deterministic simulated victim)
ragprobe bench leaderboard --models stub --split test   # see --help

# the real thing, across free models, with a cache so it is resumable
export GROQ_API_KEY=...        # free tier
export GEMINI_API_KEY=...      # free tier
ragprobe bench leaderboard \
  --models groq-qwen,groq-gptoss,groq-gptoss-120b,gemini \
  --split test --defenses none,layered \
  --cache reports/bench_cache \
  --md reports/leaderboard.md
```

Every model reply is cached under `reports/bench_cache/<model>/`, so re-running
after a rate-limit interruption only calls the models it has not reached yet, and
a finished leaderboard reproduces for free.

## Why it runs over several days

The free tiers are rate-limited, and the benchmark's test split is run against
each model under each defence. To stay inside the limits without faking anything:

- **Space the runs.** Do one or two models at a time; the cache keeps finished
  work.
- **Resume.** If a model hits its limit, re-run the same command later - cached
  replies are skipped, so it picks up where it stopped.
- **Report only test.** The `test` split is the held-out set; train/dev are for
  tuning, never for the headline number.

Planned free models (all no-cost):

| Model | Via | Notes |
|---|---|---|
| Qwen 3.8 27B | Groq | open weights |
| gpt-oss 20B / 120B | Groq | open weights |
| Gemini Flash | Google | free tier |

Until the live runs are complete the leaderboard ships as reproducible code with
an offline test; published numbers will carry their manifest (model, version,
seed, catalogue fingerprint, date) so each is traceable to the run that made it.
