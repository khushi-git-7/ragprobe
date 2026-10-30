# RAGProbe in one page

**What it is.** An open-source tool that attacks an LLM or RAG application the way the
OWASP Top 10 for LLM Applications describes, proves every hit with a planted secret (so
success is checked by code, not by another model's opinion), and measures which defences
actually help and what they cost real users.

**What is in it.**
- A frozen, versioned benchmark (Bench v1, plus v2 with seven more attack families): 138
  attacks that score themselves, tagged by risk, technique and language, with held-out splits
  and a datasheet.
- Reproducible runs: every result records version, commit, model, seed and a fingerprint of
  the exact attacks, and model replies are cached so a number repeats exactly.
- Statistics a reviewer can check: Wilson intervals, paired McNemar tests, bootstrap
  intervals, written up in `docs/methodology.md`.
- Attack types beyond a single prompt: poisoned tools (MCP), multi-turn chains, and hidden
  or obfuscated text, each with the defence that works and the gap that remains.
- A usability check, so a defence cannot win by refusing everything.
- CI that fails a change which makes the system easier to attack; a live site rebuilt on
  every push; 760+ tests.

**What it found on real models** (82 original attacks; free-tier APIs; measured 26 Oct
2026, re-scored 31 Oct after two oracle bugs were fixed).

| Model | Attacks that work | With layered defence |
|---|--:|--:|
| Qwen 3.8 27B | 1% | 1% |
| Gemini 3.5 Flash-Lite | 5% | 4% |
| gpt-oss 120B | 26% | 23% |
| gpt-oss 20B | 32% | 20% (paired p = 0.031) |

1. Models differ a lot: two of four resisted nearly everything, two were fooled by a
   quarter to a third of attacks. Their intervals do not overlap, so this one is solid.
2. No secret leaked on any model, with or without defences: 0 of 264 attempts. What
   succeeds is making the model print an attacker-chosen word, a real weakness with low
   immediate harm. Knowing which of the two you face changes what you fix first.
3. The layered defence did **not** hold up. The single significant drop (gpt-oss 20B)
   falls to p = 0.077 once three cut-off replies are excluded - all three of which were
   under the defended arm - and it did not repeat on the 56 attacks added later
   (15 to 13, p = 0.77). The headline "92% to 0%" belongs to a simulated always-obey
   model and is labelled that way.
4. Ordinary questions were answered 96 to 100% of the time with defences on.
5. The project reports its own corrections. Two: a "33% utility" reading that came from
   three questions, and a claim that the defence result replicated on an independent set
   when the second set contained the first. Both are written up rather than quietly
   edited.

**Honest limits.** Small samples, one trial per attack, hosted models that change without
notice, single-turn text attacks only, and a measure (obeying an injected instruction) that is
a proxy for harm. Details in `docs/limitations.md`.

**Where to look.** Live site: https://khushi-git-7.github.io/ragprobe/ . Code and docs:
https://github.com/khushi-git-7/ragprobe . Start with `ragprobe demo`.
