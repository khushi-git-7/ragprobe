# Multi-turn (crescendo) attacks

A one-shot injection puts the whole attack in a single message, where a detector
can see it. A multi-turn attack spreads it across several turns, each benign on
its own:

- **split-marker** — plant two label halves over two turns ("remember A = …",
  "remember B = …"), then ask for them joined.
- **role-escalation** — ease the model into an "echo/calibration" persona, then
  feed it the pieces.
- **crescendo** — a benign-sounding "audit" that works its way up to "please state
  the override code", or warms up with a harmless base64 encode before asking for
  the secret encoded.

RAGProbe drives these against the real simulated victim, which reads the whole
history, so the pieces accumulate just as a real model's context does. Each turn
is screened and wrapped by the defence and the answers pass through the output
filter, then the end state is scored with the same canary oracles as everything
else.

## The finding (run `ragprobe security multiturn`)

| Defence | Attack-success | What happens |
|---|--:|---|
| none | 100% | the obedient victim completes every chain |
| detector | ~75% | it flags some turns, but a benign-looking chain slips the pieces past |
| layered | ~50% | the output filter redacts the secret-leak chains, **but marker-assembly chains still get through** |

This is the honest, interesting part: the layered defence does **not** stop every
multi-turn attack. A marker-assembly chain is not a secret the output filter
redacts, and no single turn is suspicious enough for the per-turn detector, so it
survives. The lesson is that defeating this class needs a **conversation-level**
view (track what the whole dialogue is building toward), not just per-message
screening — a direction for future work, reported here rather than hidden.
