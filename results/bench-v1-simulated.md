# Bench v1 run

Victim **simulated** (`gullible-v1`) &middot; split **test** &middot; 22 attacks &middot; seed 42

| Defence | Attack-success | 95% CI | Trials |
|---|--:|--:|--:|
| `none` | 77% | 57&ndash;90% | 22 |
| `layered` | 27% | 13&ndash;48% | 22 |

## Manifest

- ragprobe `0.1.0`, commit `364c0b09b136`
- catalogue `datasets/bench/v1/attacks.jsonl` (fingerprint `bb4ef40ecb5efb18`)
- defences: `none`, `layered`; trials 1
- generated 2026-10-21T17:34:59Z

Rerun: `ragprobe bench run --split test --seed 42` against the same victim reproduces these numbers (live victims via the response cache).
