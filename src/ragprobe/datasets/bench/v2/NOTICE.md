# Bench v2 - sources and licences

This benchmark bundles material from several sources. Each item in
`attacks.jsonl` records its own `source` and `licence`. Summary:

| source | items | licence |
|---|--:|---|
| RAGProbe (seed + generated) | 138 | MIT |
| deepset/prompt-injections | 662 | Apache-2.0 |

## deepset/prompt-injections (Apache-2.0)

Prompt-injection / benign text classification dataset. Used here as detection
probes. Copyright its authors; distributed under the Apache License 2.0. See the
dataset's own licence for full terms.

## RAGProbe items (MIT)

Seed and generated attacks are authored by this project and released under the
repository's MIT licence. They are generic, public prompt-injection techniques
and target only RAGProbe's own simulated victims.
