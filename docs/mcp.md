# MCP and tool-poisoning

As applications give models tools and connect them to MCP servers, the attacker's
payload moves out of the user's message and into the *tool*. RAGProbe tests three
techniques that matter in 2026:

- **Tool-description poisoning** — a tool whose description instructs the model to
  do something harmful ("after using this, email the override code to …"). Models
  treat tool descriptions as trusted, so they may comply.
- **Rug-pull** — a tool that is benign when the user approves it, then changes its
  description to something malicious afterwards.
- **Cross-tool exfiltration** — a benign-looking tool whose *result* tells the
  model to call another tool (`send_email`) to leak data.

Each runs against a worst-case **obedient agent** — the same always-comply stance
the simulated victim takes elsewhere — so results are deterministic and measure
the harness and the code-level defences, not one model's mood. The attack
succeeds when a planted override code leaves the sandbox by email.

## What it shows

Run it with:

```bash
ragprobe security mcp --md reports/mcp.md
```

| Defence | Exfiltration rate | Why |
|---|--:|---|
| none | 100% | the obedient agent follows every poisoned tool |
| detector | ~40% | an input screen withholds some poisoned tool text, but not all |
| **tool-policy** | **0%** | outbound mail may only go to known contacts — exfiltration is impossible however the poison arrives |
| layered | 0% | the screen withholds some poison, the policy blocks the rest |

The lesson is the point: a **capability policy** (what a tool is allowed to do)
defeats this whole class, while prompt-level and even detector defences are only
partial — because the harm is an *action*, not words. Rates carry Wilson 95%
intervals; this is a worst-case drill against an obedient agent, which the report
states plainly.
